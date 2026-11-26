"""Known-answer tests for the spend views on a tiny hand-made base."""

from datetime import date

import pytest

from src.db import connect, create_schema


@pytest.fixture
def con():
    con = connect(":memory:")
    create_schema(con)
    con.executemany(
        "INSERT INTO suppliers VALUES (?, ?, ?, 30, 100.0)",
        [("S1", "Supplier 1", "BR"), ("S2", "Supplier 2", "CN")],
    )
    con.executemany(
        "INSERT INTO materials VALUES (?, ?, ?, '85443000', 'unit', 500.0, ?)",
        [
            ("M1", "Harness 1", "harness_engine", False),
            ("M2", "Harness 2", "harness_body", True),
            ("M3", "Harness 3", "harness_door", False),
        ],
    )
    # Spend: M1 = 5 x 10.0 + 2 x 12.5 = 75, M2 = 4 x 5.0 = 20, M3 = 1 x 5.0 = 5. Total 100.
    con.executemany(
        "INSERT INTO purchase_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("PO1", 1, "M1", "S1", date(2025, 1, 10), date(2025, 2, 10), 5, 10.0),
            ("PO2", 1, "M1", "S2", date(2025, 2, 10), date(2025, 3, 10), 2, 12.5),
            ("PO1", 2, "M2", "S1", date(2025, 1, 10), date(2025, 2, 10), 4, 5.0),
            ("PO3", 1, "M3", "S2", date(2026, 1, 5), date(2026, 2, 5), 1, 5.0),
        ],
    )
    yield con
    con.close()


def test_abc_classes(con):
    rows = dict(con.execute("SELECT material_id, abc_class FROM v_abc").fetchall())
    # Cumulative share before each item: M1 0.00 -> A, M2 0.75 -> A, M3 0.95 -> C.
    assert rows == {"M1": "A", "M2": "A", "M3": "C"}


def test_abc_shares_add_up(con):
    total = con.execute("SELECT sum(spend_share), max(cum_share) FROM v_abc").fetchone()
    assert total == pytest.approx((1.0, 1.0))


def test_ppv_against_last_price_paid(con):
    rows = con.execute(
        "SELECT material_id, last_price_usd, ppv_usd, ppv_pct FROM v_ppv "
        "WHERE last_price_usd IS NOT NULL"
    ).fetchall()
    # M1 second order: (12.5 - 10.0) x 2 = 5.0 USD, +25%.
    assert rows == [("M1", 10.0, 5.0, pytest.approx(0.25))]


def test_first_order_has_no_ppv(con):
    assert con.execute("SELECT count(*) FROM v_ppv WHERE ppv_usd IS NULL").fetchone()[0] == 3


def test_single_source_share(con):
    materials, spend = con.execute(
        "SELECT material_share, spend_share FROM v_single_source"
    ).fetchone()
    assert (materials, spend) == pytest.approx((1 / 3, 0.20))


def test_spend_cube_grand_total(con):
    total = con.execute(
        "SELECT spend_usd FROM v_spend_cube "
        "WHERE family IS NULL AND country IS NULL AND year IS NULL"
    ).fetchone()[0]
    assert total == pytest.approx(100.0)


def test_spend_cube_by_country_and_year(con):
    rows = con.execute(
        "SELECT country, year, spend_usd FROM v_spend_cube "
        "WHERE family IS NULL AND country IS NOT NULL AND year IS NOT NULL ORDER BY 1, 2"
    ).fetchall()
    assert rows == [("BR", 2025, 70.0), ("CN", 2025, 25.0), ("CN", 2026, 5.0)]
