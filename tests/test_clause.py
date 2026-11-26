"""Known-answer tests for the copper price-adjustment clause backtest."""

import numpy as np
import pandas as pd
import pytest

from src import clause
from src import should_cost as sc

BODY = sc.BY_FAMILY["harness_body"]


def series(values, start="2019-10-01"):
    return pd.Series(
        values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float
    )


def price_at(copper):
    return sc.cost_tree(BODY, copper, sc.LABOR_USD_H["BR"])["ex_works"]


def test_constant_copper_gives_the_same_flat_price_for_every_design():
    copper = series([10_000.0] * 30)
    paths = clause.price_paths(copper, BODY, "BR", start="2020-01-01")
    for design in clause.DESIGNS:
        assert paths[design].nunique() == 1
        assert paths[design].iloc[0] == pytest.approx(price_at(10_000))


def test_monthly_pass_through_follows_the_previous_month():
    copper = series([10_000.0] * 3 + [12_000.0] * 27)  # copper steps up in 2020-01
    p = clause.price_paths(copper, BODY, "BR", start="2020-01-01")["monthly"]
    assert p.loc["2020-01-01"] == pytest.approx(price_at(10_000))  # still December's index
    assert p.loc["2020-02-01"] == pytest.approx(price_at(12_000))


def test_fixed_annual_moves_only_in_january():
    copper = series([10_000.0] * 3 + [12_000.0] * 27)
    p = clause.price_paths(copper, BODY, "BR", start="2020-01-01")["fixed_annual"]
    assert p.loc["2020"].tolist() == pytest.approx([price_at(10_000)] * 12)  # set on Dec 2019
    assert p.loc["2021"].tolist() == pytest.approx([price_at(12_000)] * 12)


def test_quarterly_uses_the_previous_quarter_average():
    copper = series([9_000.0, 10_000.0, 11_000.0] + [12_000.0] * 27)
    p = clause.price_paths(copper, BODY, "BR", start="2020-01-01")["quarterly_lag3"]
    assert p.loc["2020-01-01":"2020-03-01"].tolist() == pytest.approx([price_at(10_000)] * 3)
    assert p.loc["2020-04-01":"2020-06-01"].tolist() == pytest.approx([price_at(12_000)] * 3)


def test_band_ignores_small_moves_and_resets_on_large_ones():
    # +4% stays inside the ±5% band; +10% breaks it and resets the reference.
    copper = series([10_000.0] * 3 + [10_400.0] * 3 + [11_000.0] * 24)
    p = clause.price_paths(copper, BODY, "BR", start="2020-01-01")["band_5pct"]
    assert p.loc["2020-01-01":"2020-04-01"].tolist() == pytest.approx([price_at(10_000)] * 4)
    assert p.loc["2020-05-01"] == pytest.approx(price_at(11_000))


def test_metrics_on_round_cases():
    copper = series([10_000.0] * 3 + [12_000.0] * 27)
    result = clause.backtest(copper, BODY, "BR", start="2020-01-01", index_lag=0)
    m = result.metrics.set_index("design")
    # With no lag, monthly pass-through tracks the supplier's cost exactly: margin never moves.
    assert m.loc["monthly", "margin_sd"] == pytest.approx(0.0, abs=1e-12)
    # Fixed annual never changes price inside a calendar year.
    p = result.prices["fixed_annual"]
    assert (p.groupby(p.index.year).nunique() == 1).all()


def test_supplier_margin_uses_spot_copper():
    copper = series([10_000.0] * 3 + [20_000.0] * 27)
    result = clause.backtest(copper, BODY, "BR", start="2020-01-01")
    margin = result.margins["fixed_annual"]
    # In 2020 the price is set on 10,000 but copper is 20,000: the supplier's margin drops.
    assert (margin.loc["2020"] < sc.Rates().margin).all()


def test_metrics_columns_and_ranking_on_real_like_series():
    rng = np.random.default_rng(1)
    copper = series(9_000 * np.exp(np.cumsum(rng.normal(0, 0.05, 120))))
    m = clause.backtest(copper, BODY, "BR", start="2020-01-01").metrics.set_index("design")
    assert set(m.index) == set(clause.DESIGNS)
    # Monthly pass-through protects the supplier best; fixed annual protects the buyer's
    # budget best (no drift at all inside a year).
    assert m["margin_sd"].idxmin() == "monthly"
    assert m["price_changes"].idxmin() == "fixed_annual"
    assert m.loc["fixed_annual", "budget_deviation"] == pytest.approx(0.0)


def test_recommend_picks_each_side_and_a_compromise():
    metrics = pd.DataFrame(
        {
            "design": ["fixed_annual", "monthly", "quarterly_lag3", "band_5pct"],
            "budget_deviation": [0.00, 0.06, 0.04, 0.03],
            "margin_sd": [0.030, 0.010, 0.020, 0.012],
        }
    )
    rec = clause.recommend(metrics)
    assert rec == {"buyer": "fixed_annual", "supplier": "monthly", "balanced": "band_5pct"}
