from datetime import date

import duckdb
import pytest

from src.db import TABLES, connect, create_schema


@pytest.fixture
def con():
    con = connect(":memory:")
    create_schema(con)
    yield con
    con.close()


def add_supplier(con, supplier_id="S001"):
    con.execute("INSERT INTO suppliers VALUES (?, 'Supplier A', 'BR', 30, 250.0)", [supplier_id])


def add_material(con, material_id="M001", ncm="85443000", copper=120.0):
    con.execute(
        "INSERT INTO materials VALUES (?, 'Engine harness', 'harness_engine', ?, 'unit', ?, FALSE)",
        [material_id, ncm, copper],
    )


def test_creates_all_tables(con):
    names = {row[0] for row in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    assert names == set(TABLES)


def test_create_schema_is_idempotent(con):
    create_schema(con)
    assert con.execute("SELECT count(*) FROM duckdb_tables()").fetchone()[0] == len(TABLES)


def test_valid_purchase_order_is_stored(con):
    add_supplier(con)
    add_material(con)
    con.execute(
        "INSERT INTO purchase_orders VALUES ('PO1', 1, 'M001', 'S001', ?, ?, 10, 5.0)",
        [date(2025, 1, 2), date(2025, 2, 1)],
    )
    assert con.execute("SELECT sum(qty * unit_price_usd) FROM purchase_orders").fetchone() == (
        50.0,
    )


def test_purchase_order_requires_known_material_and_supplier(con):
    add_supplier(con)
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO purchase_orders VALUES ('PO1', 1, 'M999', 'S001', ?, ?, 10, 5.0)",
            [date(2025, 1, 2), date(2025, 2, 1)],
        )


def test_purchase_order_rejects_non_positive_quantity_or_price(con):
    add_supplier(con)
    add_material(con)
    for qty, price in [(0, 5.0), (10, 0.0), (-1, 5.0)]:
        with pytest.raises(duckdb.ConstraintException):
            con.execute(
                "INSERT INTO purchase_orders VALUES ('PO1', 1, 'M001', 'S001', ?, ?, ?, ?)",
                [date(2025, 1, 2), date(2025, 2, 1), qty, price],
            )


def test_purchase_order_rejects_delivery_before_order(con):
    add_supplier(con)
    add_material(con)
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO purchase_orders VALUES ('PO1', 1, 'M001', 'S001', ?, ?, 10, 5.0)",
            [date(2025, 2, 1), date(2025, 1, 2)],
        )


def test_material_ncm_must_be_in_scope(con):
    with pytest.raises(duckdb.ConstraintException):
        add_material(con, ncm="85444200")


def test_material_rejects_negative_copper(con):
    with pytest.raises(duckdb.ConstraintException):
        add_material(con, copper=-1.0)


def test_quote_is_unique_per_rfq_and_supplier(con):
    add_supplier(con)
    add_material(con)
    insert = "INSERT INTO quotes VALUES ('RFQ1', 'M001', 'S001', ?, 4.8)"
    con.execute(insert, [date(2025, 3, 1)])
    with pytest.raises(duckdb.ConstraintException):
        con.execute(insert, [date(2025, 3, 2)])


def test_market_monthly_keeps_weight_and_statistical_quantity(con):
    con.execute(
        "INSERT INTO market_monthly VALUES (?, '85366990', 'CN', 120000.0, 800.0, 40000.0)",
        [date(2025, 1, 1)],
    )
    usd, kg, qty = con.execute("SELECT usd_fob, kg_net, qty_stat FROM market_monthly").fetchone()
    assert (usd / kg, usd / qty) == (150.0, 3.0)
