from datetime import date

import pytest

from src.db import connect, create_schema
from src.generate.config import DEFAULT
from src.generate.purchasing import generate, load
from src.validate import run_checks


@pytest.fixture(scope="module")
def base():
    return generate(DEFAULT)


@pytest.fixture
def con(base):
    con = connect(":memory:")
    create_schema(con)
    load(con, base)
    yield con
    con.close()


def failed(checks):
    return {c.name for c in checks if not c.passed}


def test_generated_base_passes_every_check(con, base):
    checks = run_checks(con, DEFAULT, base.truth)
    assert failed(checks) == set()
    assert len(checks) >= 6


def test_spend_mismatch_is_caught(con, base):
    truth = {**base.truth, "total_spend_usd": base.truth["total_spend_usd"] * 1.01}
    assert "spend_matches_truth" in failed(run_checks(con, DEFAULT, truth))


def test_spend_check_is_skipped_without_truth(con):
    assert "spend_matches_truth" not in {c.name for c in run_checks(con, DEFAULT, None)}


def test_order_outside_window_is_caught(con):
    con.execute(
        "UPDATE purchase_orders SET order_date = ?, delivery_date = ? "
        "WHERE po_id = (SELECT min(po_id) FROM purchase_orders)",
        [date(2030, 1, 1), date(2030, 2, 1)],
    )
    assert "orders_inside_window" in failed(run_checks(con, DEFAULT, None))


def test_second_supplier_on_single_source_item_is_caught(con):
    material, supplier = con.execute(
        "SELECT m.material_id, s.supplier_id FROM materials m, suppliers s "
        "WHERE m.single_source AND s.supplier_id NOT IN "
        "(SELECT supplier_id FROM purchase_orders WHERE material_id = m.material_id) LIMIT 1"
    ).fetchone()
    con.execute(
        "INSERT INTO purchase_orders VALUES ('PO99999', 1, ?, ?, ?, ?, 1, 1.0)",
        [material, supplier, date(2025, 6, 2), date(2025, 7, 2)],
    )
    assert "single_source_has_one_supplier" in failed(run_checks(con, DEFAULT, None))


def test_material_without_orders_is_caught(con):
    con.execute(
        "INSERT INTO materials VALUES "
        "('M999', 'Unused harness', 'harness_door', '85443000', 'unit', 200.0, FALSE)"
    )
    assert "every_material_ordered" in failed(run_checks(con, DEFAULT, None))
