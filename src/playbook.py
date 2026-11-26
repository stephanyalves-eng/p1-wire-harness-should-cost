"""Negotiation playbook per supplier: position, BATNA, ZOPA and concessions.

For a supplier's materials over a period, the bounds are spend amounts:

    current    what the buyer paid
    walk_away  the buyer's reservation: the spend at which this supplier's TCO would equal the
               best alternative's TCO (never above current). Above it, switching is cheaper.
    target     should-cost, a fair price with an 8% margin
    floor      the supplier's cost without margin, its likely reservation

The zone of possible agreement (ZOPA) runs from the floor to the walk-away. The opening offer
sits just under the target, and the concessions trade what the buyer can give for price.

Run:  python -m src.playbook   writes reports/negotiation_playbook.md
"""

import argparse
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from src import gap, strategy, tco
from src.db import DEFAULT_DB, ROOT, connect, create_schema
from src.should_cost import Rates

OUT = ROOT / "reports" / "negotiation_playbook.md"
OPENING_DISCOUNT = 0.03  # open 3% under should-cost to leave room to concede


def _lines(con, supplier_id: str, since: date) -> pd.DataFrame:
    lines = gap.priced_lines(con, "purchase_orders")
    lines = lines[
        (lines["supplier_id"] == supplier_id)
        & (pd.to_datetime(lines["order_date"]) >= pd.Timestamp(since))
    ]
    return lines


def zopa(con: duckdb.DuckDBPyConnection, supplier_id: str, since: date) -> dict:
    lines = _lines(con, supplier_id, since)
    pairs = tco.pair_tco(con, since)
    pairs = pairs[pairs["supplier_id"] == supplier_id].set_index("material_id")

    current = float((lines["qty"] * lines["unit_price_usd"]).sum())
    target = float((lines["qty"] * lines["should_cost_usd"]).sum())
    margin = Rates().margin
    floor = target * (1 - margin / (1 + margin))  # should-cost without its margin

    # Walk-away per material: scale today's price by best-alternative TCO / own TCO.
    walk = 0.0
    for m, g in lines.groupby("material_id"):
        spend = float((g["qty"] * g["unit_price_usd"]).sum())
        row = pairs.loc[m]
        ratio = 1.0 if pd.isna(row["batna_tco"]) else min(1.0, row["batna_tco"] / row["tco"])
        walk += spend * ratio
    covered = float(pairs["batna_tco"].notna().mean()) if len(pairs) else 0.0
    # Aim at should-cost, or lower if the best alternative already beats it.
    aim = min(target, walk)
    return {
        "current": current,
        "walk_away": walk,
        "has_zopa": walk >= floor,
        "target": target,
        "aim": aim,
        "opening": max(floor, aim * (1 - OPENING_DISCOUNT)),
        "floor": floor,
        "materials": int(lines["material_id"].nunique()),
        "batna_coverage": covered,
    }


def _concessions(
    quadrants: pd.Series, risk_tier: str, flagged: bool
) -> tuple[list[str], list[str]]:
    """What the buyer can give, and what it asks for in return."""
    give = []
    if quadrants.get("strategic", 0) > 0.5:
        give.append("a 3-year agreement instead of yearly renewals")
    give.append("the quarterly copper clause, which protects its margin better than a fixed price")
    give.append("a larger share of volume on items it already shares with other suppliers")
    give.append("payment at 45 days instead of 60")
    ask = ["price at should-cost, phased in over two quarters if needed"]
    ask.append("an open cost breakdown (copper, material, labour) at each quarterly review")
    if risk_tier == "high":
        ask.append("a consignment or safety stock in Brazil sized to its lead time")
    if flagged:
        ask.append("a retroactive credit if the next quarterly review confirms the gap")
    return give, ask


def render(con: duckdb.DuckDBPyConnection, suppliers: list[str], since: date) -> str:
    gaps = gap.supplier_gaps(con).set_index("supplier_id")
    risk = strategy.supplier_risk(con).set_index("supplier_id")
    materials = strategy.material_risk(con)
    pairs = tco.pair_tco(con, since)
    sup_tco = tco.supplier_tco(pairs).set_index("supplier_id")
    hq = dict(con.execute("SELECT supplier_id, hq_country FROM suppliers").fetchall())

    out = [
        "# Negotiation playbook",
        "",
        f"Generated from the purchasing base with `python -m src.playbook` for orders since "
        f"{since:%Y-%m-%d}. Amounts are spend over that period at each bound. Method and "
        "definitions: `src/playbook.py`.",
        "",
    ]
    for s in suppliers:
        z = zopa(con, s, since)
        g = gaps.loc[s]
        r = risk.loc[s]
        held = pairs[pairs["supplier_id"] == s]["material_id"]
        mix = materials[materials["material_id"].isin(held)]
        quadrants = mix.groupby("quadrant")["spend_usd"].sum() / mix["spend_usd"].sum()
        give, ask = _concessions(quadrants, r["tier"], bool(g["flagged"]))
        alternatives = pairs[pairs["supplier_id"] == s]["batna_supplier"].dropna().unique()

        def pct(v, base=z["current"]):
            return f"{v / base - 1:+.1%}"

        group = hq.get(s) or "unknown"
        out += [
            f"## {s} (plant in {g['country']}, {group} group)",
            "",
            f"- **Position:** {z['materials']} materials, USD {z['current']:,.0f} since "
            f"{since:%b %Y}; price {g['gap']:+.1%} over should-cost"
            f"{' (flagged as overpriced)' if g['flagged'] else ''}; TCO "
            f"{sup_tco.loc[s, 'tco_uplift']:+.1%} over price; risk score {r['risk_score']:.0f} "
            f"({r['tier']}).",
            "- **Quadrant mix:** "
            + ", ".join(f"{strategy.LABELS[q]} {v:.0%}" for q, v in quadrants.items())
            + ".",
            f"- **BATNA:** an alternative source exists for {z['batna_coverage']:.0%} of its "
            f"materials ({', '.join(sorted(alternatives)) or 'none'}). Moving that volume is "
            f"worth it below a price of {pct(z['walk_away'])} vs today.",
        ]
        if z["has_zopa"]:
            if z["aim"] < z["target"]:
                aim = (
                    f"Aim for the walk-away, {pct(z['aim'])}: the alternatives already beat "
                    f"should-cost ({pct(z['target'])})"
                )
            else:
                aim = f"Target {pct(z['target'])} (should-cost)"
            out += [
                f"- **ZOPA:** from the supplier's floor at {pct(z['floor'])} to the buyer's "
                f"walk-away at {pct(z['walk_away'])}. {aim}, USD "
                f"{z['current'] - z['aim']:,.0f} below today; open at {pct(z['opening'])}.",
                "- **Concessions we can give:** " + "; ".join(give) + ".",
                "- **What we ask for:** " + "; ".join(ask) + ".",
            ]
        else:
            out += [
                f"- **No ZOPA on price:** the alternatives' TCO is {pct(z['walk_away'])} vs "
                f"today, below this supplier's own floor ({pct(z['floor'])}). No price it can "
                "accept beats switching, so the plan is to move volume to the alternatives in "
                "stages, keeping this supplier as second source where risk calls for one.",
                f"- **Bridge while qualifying:** ask for should-cost ({pct(z['target'])}, "
                f"USD {z['current'] - z['target']:,.0f} below today) for the transition "
                "period; offer " + "; ".join(give[1:3]) + ".",
            ]
        out.append("")
    return "\n".join(out)


def targets(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Flagged suppliers first, then suppliers over 10% that are not outliers (watch list)."""
    g = gap.supplier_gaps(con)
    flagged = g.loc[g["flagged"], "supplier_id"].tolist()
    watch = g.loc[~g["flagged"] & (g["gap"] > gap.MATERIALITY), "supplier_id"].tolist()
    return flagged + watch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--since", default="2025-11-01")
    args = parser.parse_args()
    con = connect(args.db)
    create_schema(con)
    since = date.fromisoformat(args.since)
    OUT.write_text(render(con, targets(con), since), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
