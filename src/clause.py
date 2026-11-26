"""Backtest of copper price-adjustment clauses for a harness contract.

The contract price is the should-cost at an index value of copper; designs differ in which
copper value they use and when the price moves:

    fixed_annual    price set each January on December's copper, fixed for the year
    monthly         price reset every month on the previous month's copper
    quarterly_lag3  price reset each quarter on the average copper of the previous quarter
    band_5pct       price reset only when copper moves more than 5% from the last reset

The supplier buys copper at the month's spot price, so its margin is
(price - cost at spot copper, excluding margin) / price. The buyer cares about budget
certainty: how far the price drifts from the price at the start of the year, which is what
the budget assumed. The supplier cares about how much its margin moves.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import should_cost as sc

DESIGNS = ("fixed_annual", "monthly", "quarterly_lag3", "band_5pct")
LABELS = {
    "fixed_annual": "Fixed annual",
    "monthly": "Monthly pass-through",
    "quarterly_lag3": "Quarterly, 3-month lag",
    "band_5pct": "±5% band",
}
BAND = 0.05


@dataclass
class Backtest:
    prices: pd.DataFrame  # contract price per month, one column per design
    margins: pd.DataFrame  # supplier margin on price per month, one column per design
    cost: pd.Series  # supplier cost per unit at spot copper, excluding margin
    metrics: pd.DataFrame


def _price(premise, copper_usd_t, labor_usd_h):
    return sc.cost_tree(premise, copper_usd_t, labor_usd_h)["ex_works"]


def _cost(premise, copper_usd_t, labor_usd_h):
    tree = sc.cost_tree(premise, copper_usd_t, labor_usd_h)
    return tree["ex_works"] - tree["margin"]


def price_paths(
    copper: pd.Series,
    premise: sc.FamilyPremise,
    country: str,
    start: str,
    end: str | None = None,
    index_lag: int = 1,
) -> pd.DataFrame:
    """Contract price per month under each design. `copper` must cover the lead-in months."""
    copper = copper.sort_index()
    labor = sc.LABOR_USD_H[country]
    months = pd.date_range(start, end or copper.index.max(), freq="MS")
    published = copper.shift(index_lag, freq="MS")  # index value known in each month

    def p(value):
        return _price(premise, value, labor)

    out = {}
    out["fixed_annual"] = [p(copper.loc[pd.Timestamp(m.year - 1, 12, 1)]) for m in months]
    out["monthly"] = [p(published.loc[m]) for m in months]

    quarterly = []
    for m in months:
        q_start = pd.Timestamp(m.year, 3 * ((m.month - 1) // 3) + 1, 1)
        prev = pd.date_range(q_start - pd.DateOffset(months=3), periods=3, freq="MS")
        quarterly.append(p(copper.loc[prev].mean()))
    out["quarterly_lag3"] = quarterly

    band, reference = [], published.loc[months[0]]
    for m in months:
        if abs(published.loc[m] / reference - 1) > BAND:
            reference = published.loc[m]
        band.append(p(reference))
    out["band_5pct"] = band

    return pd.DataFrame(out, index=months)


def backtest(
    copper: pd.Series,
    premise: sc.FamilyPremise,
    country: str,
    start: str,
    end: str | None = None,
    index_lag: int = 1,
) -> Backtest:
    prices = price_paths(copper, premise, country, start, end, index_lag)
    labor = sc.LABOR_USD_H[country]
    cost = pd.Series([_cost(premise, copper.loc[m], labor) for m in prices.index], prices.index)
    margins = prices.apply(lambda col: (col - cost) / col)
    changes = prices.pct_change().iloc[1:]
    january = prices.groupby(prices.index.year).transform("first")
    drift = (prices / january - 1).abs()
    reference = prices["monthly"].sum()
    rows = []
    for d in DESIGNS:
        rows.append(
            {
                "design": d,
                "budget_deviation": drift[d].mean(),  # mean |price / January price - 1|
                "max_jump": changes[d].abs().max(),
                "price_changes": int((changes[d].abs() > 1e-12).sum()),
                "paid_vs_monthly": prices[d].sum() / reference - 1,
                "margin_mean": margins[d].mean(),
                "margin_sd": margins[d].std(),
                "margin_min": margins[d].min(),
            }
        )
    return Backtest(prices, margins, cost, pd.DataFrame(rows))


def recommend(metrics: pd.DataFrame) -> dict[str, str]:
    """Best design for each side and the best compromise.

    Buyer: least budget deviation. Supplier: least margin spread. Balanced: the design whose
    worse side is least bad, comparing each metric to the best value any design achieves.
    """
    m = metrics.set_index("design")
    buyer = m["budget_deviation"] / m["budget_deviation"].max()
    supplier = m["margin_sd"] / m["margin_sd"].max()
    return {
        "buyer": m["budget_deviation"].idxmin(),
        "supplier": m["margin_sd"].idxmin(),
        "balanced": np.maximum(buyer, supplier).idxmin(),
    }
