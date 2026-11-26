"""Price vs. should-cost: supplier and quote gaps, overpricing flags, savings and sensitivity.

A supplier is flagged when its spend-weighted gap is both material (above 10%) and an outlier
among suppliers (more than 2 robust standard deviations above the median gap). The first rule
keeps small differences out of negotiations; the second keeps a supplier from being flagged
only because the premises are off for everyone.
"""

from dataclasses import replace
from datetime import date

import duckdb
import pandas as pd

from src import should_cost as sc
from src.generate.config import DEFAULT

MATERIALITY = 0.10
OUTLIER_Z = 2.0
COPPER_LAG_MONTHS = DEFAULT.copper_lag_months  # same lag the suppliers' index pricing uses


def priced_lines(con: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    """PO lines or quotes with the should-cost per unit at their date, copper lagged."""
    date_col = {"purchase_orders": "order_date", "quotes": "quote_date"}[table]
    lag = COPPER_LAG_MONTHS
    df = con.execute(
        f"""
        SELECT t.*, m.family, m.ncm, m.copper_g_per_unit, s.country, c.copper_usd_t
        FROM {table} AS t
        JOIN materials AS m USING (material_id)
        JOIN suppliers AS s USING (supplier_id)
        LEFT JOIN copper_monthly AS c
            ON c.month = date_trunc('month', t.{date_col}) - INTERVAL {lag} MONTH
        """
    ).df()
    if df["copper_usd_t"].isna().any():
        raise ValueError(f"copper_monthly lacks months needed for {table}; load the Pink Sheet")
    df["should_cost_usd"] = [
        sc.cost_tree(
            sc.BY_FAMILY[r.family],
            r.copper_usd_t,
            sc.LABOR_USD_H[r.country],
            copper_g=r.copper_g_per_unit,
        )["ex_works"]
        for r in df.itertuples()
    ]
    df["gap"] = df["unit_price_usd"] / df["should_cost_usd"] - 1
    return df


def flag(frame: pd.DataFrame) -> pd.DataFrame:
    """Add a robust z-score of `gap` and the overpricing flag."""
    median = frame["gap"].median()
    mad = 1.4826 * (frame["gap"] - median).abs().median()
    out = frame.copy()
    out["z"] = (out["gap"] - median) / mad if mad > 0 else 0.0
    out["flagged"] = (out["gap"] > MATERIALITY) & (out["z"] > OUTLIER_Z)
    return out


def supplier_gaps(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    lines = priced_lines(con, "purchase_orders")
    lines["spend_usd"] = lines["qty"] * lines["unit_price_usd"]
    lines["should_spend_usd"] = lines["qty"] * lines["should_cost_usd"]
    g = (
        lines.groupby(["supplier_id", "country"], as_index=False)
        .agg(
            spend_usd=("spend_usd", "sum"),
            should_spend_usd=("should_spend_usd", "sum"),
            materials=("material_id", "nunique"),
        )
        .assign(gap=lambda d: d["spend_usd"] / d["should_spend_usd"] - 1)
    )
    return flag(g).sort_values("gap", ascending=False).reset_index(drop=True)


def quote_gaps(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Average gap of each supplier's quotes, with the number of quotes."""
    q = priced_lines(con, "quotes")
    return (
        q.groupby(["supplier_id", "country"], as_index=False)
        .agg(gap=("gap", "mean"), quotes=("rfq_id", "count"))
        .sort_values("gap", ascending=False)
        .reset_index(drop=True)
    )


def savings_potential(con: duckdb.DuckDBPyConnection, since: date) -> pd.DataFrame:
    """Spend above should-cost since a date, for material-supplier pairs above materiality."""
    lines = priced_lines(con, "purchase_orders")
    lines = lines[pd.to_datetime(lines["order_date"]) >= pd.Timestamp(since)]
    pairs = (
        lines.assign(
            spend_usd=lines["qty"] * lines["unit_price_usd"],
            should_spend_usd=lines["qty"] * lines["should_cost_usd"],
        )
        .groupby(["material_id", "supplier_id", "family"], as_index=False)[
            ["spend_usd", "should_spend_usd"]
        ]
        .sum()
    )
    pairs["gap"] = pairs["spend_usd"] / pairs["should_spend_usd"] - 1
    pairs = pairs[pairs["gap"] > MATERIALITY].copy()
    pairs["savings_usd"] = pairs["spend_usd"] - pairs["should_spend_usd"]
    return pairs.sort_values("savings_usd", ascending=False).reset_index(drop=True)


def tornado(
    premise: sc.FamilyPremise,
    copper_usd_t: float,
    country: str,
    swing: float = 0.20,
    points: float = 0.03,
) -> pd.DataFrame:
    """Ex-works should-cost when each driver moves alone, sorted by the size of its effect.

    Cost drivers move by +/- `swing` (relative); percentage rates move by +/- `points`.
    """
    rates = sc.Rates()
    labor = sc.LABOR_USD_H[country]

    def run(p=premise, cu=copper_usd_t, lab=labor, r=rates):
        return sc.cost_tree(p, cu, lab, r)["ex_works"]

    up, down = 1 + swing, 1 - swing
    cases = {
        "copper price": (run(cu=copper_usd_t * down), run(cu=copper_usd_t * up)),
        "labour cost per hour": (run(lab=labor * down), run(lab=labor * up)),
        "labour minutes": (
            run(p=replace(premise, labor_min=premise.labor_min * down)),
            run(p=replace(premise, labor_min=premise.labor_min * up)),
        ),
        "other material": (
            run(p=replace(premise, other_material_usd=premise.other_material_usd * down)),
            run(p=replace(premise, other_material_usd=premise.other_material_usd * up)),
        ),
    }
    for field, label in (
        ("margin", "margin"),
        ("sga", "SG&A"),
        ("overhead_on_labor", "overhead"),
        ("copper_scrap", "copper scrap"),
    ):
        value = getattr(rates, field)
        cases[label] = (
            run(r=replace(rates, **{field: max(0.0, value - points)})),
            run(r=replace(rates, **{field: value + points})),
        )
    out = pd.DataFrame(
        [{"driver": k, "low": lo, "high": hi} for k, (lo, hi) in cases.items()]
    ).assign(base=run())
    out["swing"] = (out["high"] - out["low"]).abs()
    out = out.sort_values("swing", ascending=False).drop(columns="swing").reset_index(drop=True)
    out.attrs.update(family=premise.family, country=country, swing=swing, points=points)
    return out
