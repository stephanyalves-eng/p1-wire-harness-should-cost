import pandas as pd
import pytest

from src.db import connect, create_schema
from src.generate.config import DEFAULT, FAMILIES
from src.generate.purchasing import generate, load, synthetic_copper


@pytest.fixture(scope="module")
def base():
    return generate(DEFAULT)


def test_sizes_match_the_plan(base):
    assert len(base.suppliers) == 60
    assert len(base.materials) == 300
    assert 4_000 <= len(base.purchase_orders) <= 7_000


def test_purchase_orders_cover_24_months(base):
    months = base.purchase_orders["order_date"].dt.to_period("M").nunique()
    assert months == 24


def test_single_source_share_is_twenty_percent(base):
    assert base.materials["single_source"].mean() == pytest.approx(0.20)
    pairs = base.purchase_orders.groupby("material_id")["supplier_id"].nunique()
    single = base.materials.set_index("material_id")["single_source"]
    assert (pairs[single[single].index] == 1).all()
    assert (pairs[single[~single].index] >= 2).all()


def test_every_rfq_has_three_quotes_from_distinct_suppliers(base):
    per_rfq = base.quotes.groupby("rfq_id")["supplier_id"].agg(["count", "nunique"])
    assert (per_rfq["count"] == 3).all()
    assert (per_rfq["nunique"] == 3).all()


def test_suppliers_only_sell_their_own_kind(base):
    kind = {f.name: f.kind for f in FAMILIES}
    po = base.purchase_orders.merge(base.materials, on="material_id").merge(
        base.supplier_kind, on="supplier_id"
    )
    assert (po["family"].map(kind) == po["kind"]).all()


def test_three_overpriced_suppliers_in_range(base):
    truth = base.truth["overpriced_suppliers"]
    assert len(truth) == 3
    assert all(0.08 <= markup <= 0.15 for markup in truth.values())


def test_overpricing_is_visible_in_quotes(base):
    """Quotes from overpriced suppliers sit above the RFQ median, so the analysis can find them."""
    q = base.quotes.copy()
    q["ratio"] = q["unit_price_usd"] / q.groupby("rfq_id")["unit_price_usd"].transform("median")
    flagged = q[q["supplier_id"].isin(base.truth["overpriced_suppliers"])]
    assert flagged["ratio"].mean() > 1.05


def test_prices_follow_copper_with_a_lag():
    flat = synthetic_copper(DEFAULT, volatility=0.0)
    doubled = flat * 2
    low = generate(DEFAULT, copper=flat).purchase_orders
    high = generate(DEFAULT, copper=doubled).purchase_orders
    assert high["unit_price_usd"].sum() > low["unit_price_usd"].sum() * 1.05


def test_same_seed_gives_identical_data():
    a, b = generate(DEFAULT), generate(DEFAULT)
    pd.testing.assert_frame_equal(a.purchase_orders, b.purchase_orders)
    assert a.truth == b.truth


def test_generated_base_loads_into_the_schema(base):
    con = connect(":memory:")
    create_schema(con)
    load(con, base)
    counts = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("suppliers", "materials", "purchase_orders", "quotes")
    }
    assert counts == {
        "suppliers": len(base.suppliers),
        "materials": len(base.materials),
        "purchase_orders": len(base.purchase_orders),
        "quotes": len(base.quotes),
    }
    spend = con.execute("SELECT sum(qty * unit_price_usd) FROM purchase_orders").fetchone()[0]
    assert spend == pytest.approx(base.truth["total_spend_usd"])
