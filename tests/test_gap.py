"""Known-answer tests for price-vs-should-cost gaps, flags, savings and the tornado."""

from dataclasses import replace
from datetime import date

import pandas as pd
import pytest

from src import gap
from src import should_cost as sc
from src.db import connect, create_schema
from src.generate.config import DEFAULT
from src.generate.purchasing import generate, load, synthetic_copper

COPPER = 10_000.0
ENGINE = sc.BY_FAMILY["harness_engine"]


def should(country="BR"):
    return sc.cost_tree(ENGINE, COPPER, sc.LABOR_USD_H[country])["ex_works"]


@pytest.fixture
def con():
    """Two Brazilian suppliers of one engine harness: S1 at should-cost + 5%, S2 at + 30%."""
    con = connect(":memory:")
    create_schema(con)
    con.executemany(
        "INSERT INTO copper_monthly VALUES (?, ?)",
        [(date(2025, m, 1), COPPER) for m in range(1, 13)],
    )
    con.executemany(
        "INSERT INTO suppliers VALUES (?, ?, 'BR', 30, 100.0)", [("S1", "A"), ("S2", "B")]
    )
    con.execute(
        "INSERT INTO materials VALUES "
        "('M1', 'Engine', 'harness_engine', '85443000', 'unit', ?, FALSE)",
        [ENGINE.copper_g],
    )
    con.executemany(
        "INSERT INTO purchase_orders VALUES (?, 1, 'M1', ?, ?, ?, ?, ?)",
        [
            ("PO1", "S1", date(2025, 6, 2), date(2025, 7, 2), 100, should() * 1.05),
            ("PO2", "S2", date(2025, 6, 2), date(2025, 7, 2), 100, should() * 1.30),
        ],
    )
    con.executemany(
        "INSERT INTO quotes VALUES ('RFQ1', 'M1', ?, ?, ?)",
        [("S1", date(2025, 9, 1), should() * 1.04), ("S2", date(2025, 9, 1), should() * 1.25)],
    )
    yield con
    con.close()


def test_line_should_cost_uses_lagged_copper_and_supplier_country(con):
    lines = gap.priced_lines(con, "purchase_orders")
    assert lines["should_cost_usd"].tolist() == pytest.approx([should(), should()])


def test_supplier_gap_is_spend_weighted(con):
    g = gap.supplier_gaps(con).set_index("supplier_id")
    assert g.loc["S1", "gap"] == pytest.approx(0.05)
    assert g.loc["S2", "gap"] == pytest.approx(0.30)


def test_quote_gaps(con):
    q = gap.quote_gaps(con).set_index("supplier_id")
    assert q.loc["S1", "gap"] == pytest.approx(0.04)
    assert q.loc["S2", "gap"] == pytest.approx(0.25)


def test_savings_only_count_pairs_above_the_materiality_threshold(con):
    pairs = gap.savings_potential(con, since=date(2025, 1, 1))
    # Only S2 is above 10%: 100 units x 0.30 x should-cost.
    assert pairs["savings_usd"].sum() == pytest.approx(100 * 0.30 * should())
    assert set(pairs["supplier_id"]) == {"S2"}


def test_flag_needs_materiality_and_outlier():
    frame = pd.DataFrame(
        {"supplier_id": list("ABCDEFG"), "gap": [0.03, 0.04, 0.05, 0.05, 0.06, 0.25, 0.09]}
    )
    flagged = gap.flag(frame)
    assert set(flagged.loc[flagged["flagged"], "supplier_id"]) == {"F"}  # G is under both bars


def test_flags_recover_the_hidden_overpriced_suppliers():
    base = generate(DEFAULT)
    con = connect(":memory:")
    create_schema(con)
    load(con, base)
    copper = synthetic_copper(DEFAULT).rename("copper_usd_t").rename_axis("month").reset_index()
    con.register("synthetic_copper", copper)
    con.execute("INSERT INTO copper_monthly SELECT month::DATE, copper_usd_t FROM synthetic_copper")
    g = gap.supplier_gaps(con)
    flagged = set(g.loc[g["flagged"], "supplier_id"])
    truth = set(base.truth["overpriced_suppliers"])
    assert truth <= flagged
    assert len(flagged - truth) <= 1


def test_tornado_copper_swing_on_round_numbers():
    t = gap.tornado(ENGINE, COPPER, "BR", swing=0.20).set_index("driver")
    base = should()
    copper_line = sc.cost_tree(ENGINE, COPPER, sc.LABOR_USD_H["BR"])["copper"]
    assert t.loc["copper price", "high"] - base == pytest.approx(0.2 * copper_line * 1.08 * 1.08)
    assert t.loc["copper price", "low"] - base == pytest.approx(-0.2 * copper_line * 1.08 * 1.08)


def test_tornado_is_sorted_by_swing():
    t = gap.tornado(ENGINE, COPPER, "BR")
    swings = (t["high"] - t["low"]).abs().tolist()
    assert swings == sorted(swings, reverse=True)


def test_tornado_margin_driver_moves_by_points():
    t = gap.tornado(ENGINE, COPPER, "BR", points=0.03).set_index("driver")
    rates = sc.Rates()
    high = sc.cost_tree(ENGINE, COPPER, 9.0, replace(rates, margin=rates.margin + 0.03))
    assert t.loc["margin", "high"] == pytest.approx(high["ex_works"])
