"""Static figures for the README, rendered from the project database.

Notebook outputs are stripped on commit, so these PNGs are what a reader sees on GitHub.
They are regenerated from the same views the notebooks use, so they always match the data.

Run:  python -m src.figures  [--db PATH] [--out reports/figures]
"""

import argparse
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # render without a display

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mtick  # noqa: E402
import pandas as pd  # noqa: E402

from src.db import DEFAULT_DB, ROOT, connect, create_schema  # noqa: E402

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


FIGURES = {
    "spend_by_family": spend_by_family,
    "abc_pareto": abc_pareto,
    "harness_price_vs_copper": harness_price_vs_copper,
    "origin_hhi": origin_hhi,
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
    con = connect(args.db)
    create_schema(con)
    for path in render_all(con, args.out):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)


if __name__ == "__main__":
    main()
