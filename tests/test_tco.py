"""Known-answer tests for total cost of ownership, BATNA, ZOPA and the playbook."""

from datetime import date

import pytest

from src import playbook, tco
from src import should_cost as sc
from src.db import connect, create_schema

COPPER = 10_000.0
ENGINE = sc.BY_FAMILY["harness_engine"]


def should(country):
    return sc.cost_tree(ENGINE, COPPER, sc.LABOR_USD_H[country])


def test_unit_tco_on_round_numbers():
    # Chinese supplier: price 100, freight 6%, duty 16% on CIF, lead 60 days, 500 PPM.
    landed = 100 * 1.06 * 1.16
    carry = landed * 0.20 * (60 + 15) / 365
    quality = 500 / 1e6 * (landed + 200)
    out = tco.unit_tco(100.0, "CN", "85443000", lead_time_days=60, ppm=500)
    assert out["landed"] == pytest.approx(landed)
    assert out["carrying"] == pytest.approx(carry)
    assert out["quality"] == pytest.approx(quality)
    assert out["tco"] == pytest.approx(landed + carry + quality)


def test_domestic_supplier_pays_no_duty():
    out = tco.unit_tco(100.0, "BR", "85443000", lead_time_days=30, ppm=0)
    assert out["landed"] == pytest.approx(100 * (1 + sc.FREIGHT["BR"]))


@pytest.fixture
def con():
    """M1 bought from S1 (Brazil, at should-cost + 20%) and S2 (Mexico, at should-cost + 2%)."""
    con = connect(":memory:")
    create_schema(con)
    con.executemany(
        "INSERT INTO copper_monthly VALUES (?, ?)",
        [(date(2025, m, 1), COPPER) for m in range(1, 13)],
    )
    con.executemany(
        "INSERT INTO suppliers VALUES (?, ?, ?, 30, 100.0)",
        [("S1", "Brazil A", "BR"), ("S2", "Mexico A", "MX")],
    )
    con.execute(
        "INSERT INTO materials VALUES "
        "('M1', 'Engine', 'harness_engine', '85443000', 'unit', ?, FALSE)",
        [ENGINE.copper_g],
    )
    d, e = date(2025, 6, 2), date(2025, 7, 2)
    con.executemany(
        "INSERT INTO purchase_orders VALUES (?, 1, 'M1', ?, ?, ?, 100, ?)",
        [
            ("PO1", "S1", d, e, should("BR")["ex_works"] * 1.20),
            ("PO2", "S2", d, e, should("MX")["ex_works"] * 1.02),
        ],
    )
    yield con
    con.close()


def test_pair_tco_and_batna(con):
    pairs = tco.pair_tco(con, since=date(2025, 1, 1)).set_index("supplier_id")
    assert pairs.loc["S1", "price"] == pytest.approx(should("BR")["ex_works"] * 1.20)
    # S1's best alternative for M1 is S2, priced at its own TCO.
    assert pairs.loc["S1", "batna_supplier"] == "S2"
    assert pairs.loc["S1", "batna_tco"] == pytest.approx(pairs.loc["S2", "tco"])


def test_zopa_bounds_are_ordered(con):
    z = playbook.zopa(con, "S1", since=date(2025, 1, 1))
    # Spend at each bound over the period (100 units). Floor: supplier's cost without margin.
    # Target: should-cost. Walk-away: the price at which S1's TCO equals the best
    # alternative's TCO, never above today's price.
    assert z["floor"] == pytest.approx(100 * (should("BR")["ex_works"] - should("BR")["margin"]))
    assert z["target"] == pytest.approx(100 * should("BR")["ex_works"])
    assert z["current"] == pytest.approx(100 * should("BR")["ex_works"] * 1.20)
    assert z["floor"] <= z["target"] <= z["walk_away"] <= z["current"]


def test_no_zopa_when_the_alternative_beats_the_supplier_floor(con):
    # Make S2 far cheaper: its TCO lands under S1's cost without margin.
    con.execute(
        "UPDATE purchase_orders SET unit_price_usd = unit_price_usd * 0.5 WHERE supplier_id = 'S2'"
    )
    z = playbook.zopa(con, "S1", since=date(2025, 1, 1))
    assert z["walk_away"] < z["floor"]
    assert not z["has_zopa"]
    assert "No ZOPA on price" in playbook.render(con, ["S1"], since=date(2025, 1, 1))


def test_playbook_markdown_names_the_supplier_and_its_numbers(con):
    text = playbook.render(con, ["S1"], since=date(2025, 1, 1))
    assert "## S1" in text
    assert "BATNA" in text and "ZOPA" in text
    assert "Concessions" in text
