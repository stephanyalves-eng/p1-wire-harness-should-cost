"""Static figures for the README, rendered from the project database.

Notebook outputs are stripped on commit, so these PNGs are what a reader sees on GitHub.
They are regenerated from the same views the notebooks use, so they always match the data.

Run:  python -m src.figures  [--db PATH] [--out reports/figures]
"""

import argparse
from pathlib import Path

import duckdb
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import pandas as pd

from src.db import DEFAULT_DB, ROOT, connect, create_schema

OUT_DIR = ROOT / "reports" / "figures"
NCM_NAMES = {
    "85443000": "8544.30.00 harnesses",
    "85366910": "8536.69.10 shielded connectors",
    "85366990": "8536.69.90 other connectors",
}
LEGEND_BELOW = {
    "loc": "upper center",
    "bbox_to_anchor": (0.5, -0.12),
    "ncol": 3,
    "fontsize": 8,
    "frameon": False,
}


def _q(con, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def spend_by_family(con) -> plt.Figure:
    df = _q(
        con,
        """
        SELECT family,
               sum(spend_usd) / ((SELECT count(DISTINCT month) FROM v_po_lines) / 12) AS per_year
        FROM v_po_lines GROUP BY family ORDER BY per_year
        """,
    )
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(df["family"].str.replace("_", " "), df["per_year"] / 1e6, color="tab:blue")
    ax.set(xlabel="USD million per year", title="Annual spend by part family (synthetic base)")
    return fig


def abc_pareto(con) -> plt.Figure:
    df = _q(con, "SELECT rank, cum_share, abc_class FROM v_abc ORDER BY rank")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df["rank"] / len(df), df["cum_share"], color="tab:blue")
    for cut in (0.80, 0.95):
        ax.axhline(cut, ls="--", lw=0.8, color="grey")
    counts = df["abc_class"].value_counts().sort_index()
    ax.text(
        0.98,
        0.05,
        "  ".join(f"{k}: {v} materials" for k, v in counts.items()),
        transform=ax.transAxes,
        ha="right",
        fontsize=9,
    )
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1))
    ax.set(
        xlabel="Share of materials",
        ylabel="Cumulative share of spend",
        title="ABC Pareto of purchased materials",
    )
    return fig


def harness_price_vs_copper(con) -> plt.Figure:
    price = _q(
        con, "SELECT month, usd_per_kg FROM v_market_implied WHERE ncm = '85443000' ORDER BY month"
    )
    price = price.set_index(pd.to_datetime(price["month"]))["usd_per_kg"]
    copper = _q(con, "SELECT month, copper_usd_t FROM copper_monthly ORDER BY month")
    copper = copper.set_index(pd.to_datetime(copper["month"]))["copper_usd_t"] / 1000
    copper = copper[copper.index >= price.index.min()]

    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(price, color="tab:blue", alpha=0.35, label="Harness USD/kg, monthly")
    ax.plot(price.rolling(12).mean(), color="tab:blue", label="Harness USD/kg, 12-month mean")
    ax.set_ylabel("Harness import price, USD/kg")
    ax2 = ax.twinx()
    ax2.plot(copper, color="tab:orange", label="Copper USD/kg (World Bank)")
    ax2.set_ylabel("Copper, USD/kg")
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=3, fontsize=8, frameon=False)
    ax.set_title("Harness import price (Comex Stat, NCM 8544.30.00) vs. copper")
    return fig


def origin_hhi(con) -> plt.Figure:
    df = _q(con, "SELECT ncm, year, hhi FROM v_market_hhi ORDER BY ncm, year")
    wide = df.pivot(index="year", columns="ncm", values="hhi").rename(columns=NCM_NAMES)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    wide.plot(ax=ax, marker="o")
    for cut, label in ((1500, "moderate"), (2500, "high")):
        ax.axhline(cut, ls="--", lw=0.8, color="grey")
        ax.text(wide.index.min(), cut + 40, label, fontsize=8, color="grey")
    ax.set(xlabel="", ylabel="HHI (0–10,000)", title="Concentration of import origins")
    ax.legend(**LEGEND_BELOW)
    return fig


def should_cost_calibration(con) -> plt.Figure:
    calib = harness_calibration(con)
    calib = calib.sort_values("import_usd_m", ascending=False)
    x = range(len(calib))
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(
        [i - 0.2 for i in x], calib["import_usd_kg"], width=0.4, label="Import price (Comex Stat)"
    )
    ax.bar([i + 0.2 for i in x], calib["should_cost_usd_kg"], width=0.4, label="Should-cost")
    ax.set_xticks(list(x), calib["origin"], rotation=0, fontsize=8)
    ax.set(
        ylabel="USD/kg",
        title=f"Harness should-cost vs. import price by origin, {calib.attrs['year']}",
    )
    ax.legend(**LEGEND_BELOW)
    return fig


def harness_calibration(con) -> pd.DataFrame:
    """Should-cost vs. import price per kg by origin for the latest full year of imports."""
    from src.should_cost import calibrate_harness  # local import: figures stay usable without it

    year = con.execute(
        """
        SELECT max(y) FROM (
            SELECT year(month) AS y FROM market_monthly WHERE ncm = '85443000'
            GROUP BY 1 HAVING count(DISTINCT month) = 12
        )
        """
    ).fetchone()[0]
    market = _q(
        con,
        f"""
        SELECT country, sum(usd_fob) AS usd_fob, sum(usd_fob) / sum(kg_net) AS usd_per_kg
        FROM market_monthly WHERE ncm = '85443000' AND year(month) = {int(year)}
        GROUP BY country ORDER BY usd_fob DESC LIMIT 10
        """,
    )
    copper = con.execute(
        f"""
        SELECT avg(copper_usd_t) FROM copper_monthly
        WHERE month BETWEEN DATE '{int(year) - 1}-10-01' AND DATE '{int(year)}-09-01'
        """
    ).fetchone()[0]
    out = calibrate_harness(market, copper)
    out.attrs["year"] = int(year)
    return out


def supplier_gap(con) -> plt.Figure:
    from src.gap import MATERIALITY, supplier_gaps

    g = supplier_gaps(con).head(15).iloc[::-1]
    colors = ["tab:red" if f else "tab:grey" for f in g["flagged"]]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(g["supplier_id"] + " (" + g["country"] + ")", g["gap"], color=colors)
    ax.axvline(MATERIALITY, ls="--", lw=0.8, color="black")
    ax.text(MATERIALITY, len(g) - 0.45, " 10% materiality", fontsize=8, va="bottom")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1))
    ax.set(
        xlabel="Price above should-cost, spend-weighted",
        title="Suppliers with the largest gap (red: flagged as overpriced)",
    )
    ax.tick_params(axis="y", labelsize=8)
    return fig


def cost_tornado(con) -> plt.Figure:
    from src.gap import tornado
    from src.should_cost import BY_FAMILY

    copper = con.execute(
        "SELECT avg(copper_usd_t) FROM (SELECT copper_usd_t FROM copper_monthly "
        "ORDER BY month DESC LIMIT 12)"
    ).fetchone()[0]
    t = tornado(BY_FAMILY["harness_body"], copper, "BR").iloc[::-1]
    base = t["base"].iloc[0]
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(t["driver"], t["low"] / base - 1, color="tab:green", label="driver down")
    ax.barh(t["driver"], t["high"] / base - 1, color="tab:red", label="driver up")
    ax.axvline(0, color="black", lw=0.8)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1))
    ax.set(
        xlabel="Change in should-cost",
        title=f"Body harness made in Brazil: ±20% per cost driver, ±3 points per rate "
        f"(base USD {base:.0f})",
    )
    ax.title.set_fontsize(10)
    ax.legend(**LEGEND_BELOW)
    return fig


def clause_backtest(con) -> plt.Figure:
    from src.clause import DESIGNS, LABELS, backtest
    from src.should_cost import BY_FAMILY

    copper = _q(con, "SELECT month, copper_usd_t FROM copper_monthly ORDER BY month")
    copper = copper.set_index(pd.to_datetime(copper["month"]))["copper_usd_t"]
    # First January with the history every design needs (December and the previous quarter).
    first = copper.index.min()
    year = max(2016, first.year + 1 if first.month <= 10 else first.year + 2)
    result = backtest(copper, BY_FAMILY["harness_body"], "BR", start=f"{year}-01-01")
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True)
    for d in DESIGNS:
        top.plot(result.prices[d], label=LABELS[d], lw=1.4 if d == "fixed_annual" else 1.1)
        yearly = result.margins[d].groupby(result.margins.index.year).mean()
        bottom.plot(pd.to_datetime(yearly.index.astype(str) + "-07-01"), yearly, marker="o")
    top.set(ylabel="Contract price, USD", title="Body harness made in Brazil: four copper clauses")
    bottom.axhline(0, color="black", lw=0.8)
    bottom.yaxis.set_major_formatter(mtick.PercentFormatter(1))
    bottom.set(ylabel="Supplier margin on price", title="Supplier margin, yearly average")
    top.legend(fontsize=8, ncol=2, frameon=False)
    fig.tight_layout()
    return fig


def kraljic_matrix(con) -> plt.Figure:
    from src.strategy import LABELS, RISK_THRESHOLD, material_risk

    m = material_risk(con)
    colors = {
        "strategic": "tab:red",
        "leverage": "tab:blue",
        "bottleneck": "tab:orange",
        "non_critical": "tab:grey",
    }
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for q, g in m.groupby("quadrant"):
        share = g["spend_usd"].sum() / m["spend_usd"].sum()
        ax.scatter(
            g["spend_share"],
            g["supply_risk"],
            s=14,
            alpha=0.7,
            color=colors[q],
            label=f"{LABELS[q]}: {len(g)} items, {share:.0%} of spend",
        )
    a_cut = m.loc[m["abc_class"] == "A", "spend_share"].min()
    ax.axvline(a_cut, ls="--", lw=0.8, color="black")
    ax.axhline(RISK_THRESHOLD, ls="--", lw=0.8, color="black")
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1, decimals=2))
    ax.set(
        xlabel="Profit impact: item's share of spend (log scale; right of the line = class A)",
        ylabel="Supply risk (0–1)",
        title="Kraljic matrix computed from the data, 300 materials",
    )
    ax.legend(**{**LEGEND_BELOW, "ncol": 2, "bbox_to_anchor": (0.5, -0.15)})
    return fig


def tco_by_plant(con) -> plt.Figure:
    from src.tco import pair_tco

    since = con.execute(
        "SELECT max(order_date) - INTERVAL 12 MONTH FROM purchase_orders"
    ).fetchone()[0]
    p = pair_tco(con, since)
    spend = p["qty"] * p["price"]
    parts = (
        p.assign(
            price_w=spend,
            freight_duty=p["qty"] * (p["landed"] - p["price"]),
            carrying_w=p["qty"] * p["carrying"],
            quality_w=p["qty"] * p["quality"],
        )
        .groupby("country")[["price_w", "freight_duty", "carrying_w", "quality_w"]]
        .sum()
    )
    shares = parts[["freight_duty", "carrying_w", "quality_w"]].div(parts["price_w"], axis=0)
    shares = shares.loc[shares.sum(axis=1).sort_values().index]
    fig, ax = plt.subplots(figsize=(8, 4))
    shares.rename(
        columns={
            "freight_duty": "Freight and import duty",
            "carrying_w": "Inventory carrying",
            "quality_w": "Quality",
        }
    ).plot.barh(stacked=True, ax=ax, color=["tab:blue", "tab:orange", "tab:red"])
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(1))
    ax.set(
        xlabel="Cost on top of the purchase price, last 12 months",
        ylabel="Plant country",
        title="Total cost of ownership above price, by plant country",
    )
    ax.legend(**LEGEND_BELOW)
    return fig


FIGURES = {
    "spend_by_family": spend_by_family,
    "abc_pareto": abc_pareto,
    "harness_price_vs_copper": harness_price_vs_copper,
    "origin_hhi": origin_hhi,
    "should_cost_calibration": should_cost_calibration,
    "supplier_gap": supplier_gap,
    "cost_tornado": cost_tornado,
    "clause_backtest": clause_backtest,
    "kraljic_matrix": kraljic_matrix,
    "tco_by_plant": tco_by_plant,
}


def render_all(con: duckdb.DuckDBPyConnection, out_dir: Path = OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, build in FIGURES.items():
        fig = build(con)
        path = out_dir / f"{name}.png"
        fig.savefig(path, dpi=120, bbox_inches="tight", metadata={"Software": None})
        plt.close(fig)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    matplotlib.use("Agg")  # render without a display; set here so importing stays side-effect free
    con = connect(args.db)
    create_schema(con)
    for path in render_all(con, args.out):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


if __name__ == "__main__":
    main()
