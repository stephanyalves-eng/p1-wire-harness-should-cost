"""Known-answer tests for the data-driven Kraljic matrix and the supplier risk score."""

from datetime import date

import pandas as pd
import pytest

from src import strategy
from src.db import connect, create_schema


@pytest.fixture
def con():
    """M1: single source from China. M2: two Brazilian suppliers, 50/50."""
    con = connect(":memory:")
    create_schema(con)
    con.executemany(
        "INSERT INTO suppliers VALUES (?, ?, ?, ?, ?)",
        [
            ("S1", "China A", "CN", 72, 250.0),
            ("S2", "Brazil A", "BR", 27, 100.0),
            ("S3", "Brazil B", "BR", 27, 600.0),
        ],
    )
    con.executemany(
        "INSERT INTO materials VALUES (?, ?, 'harness_body', '85443000', 'unit', 1000.0, ?)",
        [("M1", "Body 1", True), ("M2", "Body 2", False)],
    )
    d, e = date(2025, 3, 3), date(2025, 5, 3)
    con.executemany(
        "INSERT INTO purchase_orders VALUES (?, 1, ?, ?, ?, ?, ?, ?)",
        [
            ("PO1", "M1", "S1", d, e, 100, 80.0),  # USD 8,000
            ("PO2", "M2", "S2", d, e, 10, 100.0),  # USD 1,000
            ("PO3", "M2", "S3", d, e, 10, 100.0),  # USD 1,000
        ],
    )
    con.executemany(
        "INSERT INTO market_monthly VALUES (?, '85443000', ?, ?, 1.0, 1.0)",
        [(date(2025, 1, 1), "Paraguay", 600.0), (date(2025, 1, 1), "China", 400.0)],
    )
    yield con
    con.close()


def test_material_risk_factors(con):
    m = strategy.material_risk(con).set_index("material_id")
    # M1: one supplier (concentration 1), lead 72/90, all imported outside Mercosur.
    assert m.loc["M1", "supplier_concentration"] == pytest.approx(1.0)
    assert m.loc["M1", "lead_time"] == pytest.approx(72 / 90)
    assert m.loc["M1", "import_exposure"] == pytest.approx(1.0)
    # Market HHI for 8544.30: 60/40 split -> 0.36 + 0.16 = 0.52.
    assert m.loc["M1", "market_concentration"] == pytest.approx(0.52)
    assert m.loc["M1", "supply_risk"] == pytest.approx((1 + 0.8 + 1 + 0.52) / 4)
    # M2: two suppliers 50/50 (0.5), lead 27/90, nothing imported.
    assert m.loc["M2", "supplier_concentration"] == pytest.approx(0.5)
    assert m.loc["M2", "supply_risk"] == pytest.approx((0.5 + 0.3 + 0 + 0.52) / 4)


def test_quadrants_follow_abc_class_and_risk_threshold(con):
    m = strategy.material_risk(con).set_index("material_id")
    # M1 holds 80% of spend -> class A; risk 0.83 -> strategic.
    assert m.loc["M1", "quadrant"] == "strategic"
    # M2 is the item that crosses 80% (spend before it is 80%) -> class B; risk 0.33.
    assert m.loc["M2", "quadrant"] == "non_critical"


def test_quadrant_rule():
    frame = pd.DataFrame({"abc_class": ["A", "A", "B", "C"], "supply_risk": [0.6, 0.4, 0.5, 0.2]})
    assert strategy.quadrant(frame).tolist() == [
        "strategic",
        "leverage",
        "bottleneck",
        "non_critical",
    ]


def test_supplier_risk_score(con):
    s = strategy.supplier_risk(con).set_index("supplier_id")
    # S1: all its spend is single source (1), lead 0.8, ppm 250/500 = 0.5, imported (1).
    expected = 100 * (0.35 * 1 + 0.25 * 0.8 + 0.20 * 0.5 + 0.20 * 1)
    assert s.loc["S1", "risk_score"] == pytest.approx(expected)
    assert s.loc["S1", "tier"] == "high"
    # S3: no dependency, lead 0.3, ppm capped at 1, domestic.
    assert s.loc["S3", "risk_score"] == pytest.approx(100 * (0.25 * 0.3 + 0.20 * 1.0))
    assert s.loc["S3", "tier"] == "low"


def test_family_summary_weights_risk_by_spend(con):
    f = strategy.family_summary(strategy.material_risk(con)).set_index("family")
    risk = (8000 * (1 + 0.8 + 1 + 0.52) / 4 + 2000 * (0.5 + 0.3 + 0 + 0.52) / 4) / 10000
    assert f.loc["harness_body", "supply_risk"] == pytest.approx(risk)
    assert f.loc["harness_body", "spend_share"] == pytest.approx(1.0)


def test_supplier_actions(con):
    risk = strategy.supplier_risk(con)
    gaps = pd.DataFrame({"supplier_id": ["S1", "S2", "S3"], "flagged": [False, True, False]})
    actions = strategy.supplier_actions(risk, gaps).set_index("supplier_id")["actions"]
    assert actions["S1"] == "qualify a second source"  # high risk, all single source
    assert actions["S2"] == "renegotiate against should-cost"
    assert actions["S3"] == ""


def test_every_quadrant_has_an_action():
    assert set(strategy.ACTIONS) == {"strategic", "leverage", "bottleneck", "non_critical"}
