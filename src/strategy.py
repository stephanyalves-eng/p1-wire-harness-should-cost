"""Category strategy: a Kraljic matrix computed from the data, and a supplier risk score.

Kraljic, per material:
    profit impact  ABC class A (the items that make up 80% of spend) is high impact
    supply risk    mean of four factors, each scaled 0 to 1:
                   - supplier concentration: HHI of the item's spend across its suppliers
                     (1 for a single source)
                   - lead time: spend-weighted supplier lead time / 90 days, capped at 1
                   - import exposure: share of spend from outside Mercosur
                   - market concentration: origin HHI of the item's NCM in Comex Stat / 10,000
                   High risk from 0.5, the middle of the scale.

Supplier risk score, 0 to 100:
    35% dependency (share of its spend on items it supplies alone), 25% lead time,
    20% quality (PPM / 500, capped), 20% import exposure (outside Mercosur).
"""

import duckdb
import pandas as pd

from src.should_cost import MERCOSUR

RISK_THRESHOLD = 0.5
LEAD_TIME_SCALE_DAYS = 90
PPM_SCALE = 500
SUPPLIER_WEIGHTS = {"dependency": 0.35, "lead_time": 0.25, "quality": 0.20, "import": 0.20}
FACTORS = ("supplier_concentration", "lead_time", "import_exposure", "market_concentration")

ACTIONS = {
    "strategic": "Long-term agreement (3 years) with the quarterly copper clause; "
    "qualify a second source for single-source items; joint cost reviews against should-cost.",
    "leverage": "Annual competitive RFQ against should-cost; consolidate volume on the best "
    "suppliers; 1-2 year agreements.",
    "bottleneck": "Secure supply: safety stock sized to lead time, qualify an alternative "
    "source or a Mercosur origin; accept a price premium for security.",
    "non_critical": "Simplify: catalogue or framework pricing, fewer suppliers, "
    "low-touch ordering.",
}
LABELS = {
    "strategic": "Strategic",
    "leverage": "Leverage",
    "bottleneck": "Bottleneck",
    "non_critical": "Non-critical",
}


def _market_year(con) -> int:
    return (
        con.execute(
            """
        SELECT max(y) FROM (
            SELECT year(month) AS y FROM market_monthly
            GROUP BY 1 HAVING count(DISTINCT month) = 12
        )
        """
        ).fetchone()[0]
        or con.execute("SELECT max(year(month)) FROM market_monthly").fetchone()[0]
    )


def quadrant(frame: pd.DataFrame) -> pd.Series:
    high_impact = frame["abc_class"] == "A"
    high_risk = frame["supply_risk"] >= RISK_THRESHOLD
    out = pd.Series("non_critical", index=frame.index)
    out[high_impact & high_risk] = "strategic"
    out[high_impact & ~high_risk] = "leverage"
    out[~high_impact & high_risk] = "bottleneck"
    return out


def material_risk(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per material: spend, ABC class, the four risk factors, supply risk, quadrant."""
    year = _market_year(con)
    mercosur = ", ".join(f"'{c}'" for c in sorted(MERCOSUR))
    df = con.execute(
        f"""
        WITH by_supplier AS (
            SELECT material_id, supplier_id, sum(spend_usd) AS s
            FROM v_po_lines GROUP BY 1, 2
        ),
        shares AS (
            SELECT material_id, s / sum(s) OVER (PARTITION BY material_id) AS sh
            FROM by_supplier
        ),
        concentration AS (
            SELECT material_id, sum(sh * sh) AS supplier_concentration, count(*) AS suppliers
            FROM shares GROUP BY 1
        ),
        logistics AS (
            SELECT
                l.material_id,
                least(sum(l.spend_usd * s.lead_time_days) / sum(l.spend_usd)
                      / {LEAD_TIME_SCALE_DAYS}, 1) AS lead_time,
                coalesce(sum(l.spend_usd) FILTER (WHERE s.country NOT IN ({mercosur})), 0)
                    / sum(l.spend_usd) AS import_exposure
            FROM v_po_lines AS l JOIN suppliers AS s USING (supplier_id)
            GROUP BY 1
        ),
        market AS (
            SELECT ncm, hhi / 10000 AS market_concentration
            FROM v_market_hhi WHERE year = {int(year)}
        )
        SELECT a.material_id, a.family, m.ncm, a.spend_usd, a.spend_share, a.abc_class,
               c.suppliers, c.supplier_concentration, g.lead_time, g.import_exposure,
               coalesce(k.market_concentration, 0) AS market_concentration
        FROM v_abc AS a
        JOIN materials AS m USING (material_id)
        JOIN concentration AS c USING (material_id)
        JOIN logistics AS g USING (material_id)
        LEFT JOIN market AS k ON k.ncm = m.ncm
        """
    ).df()
    df["supply_risk"] = df[list(FACTORS)].mean(axis=1)
    df["quadrant"] = quadrant(df)
    df.attrs["market_year"] = int(year)
    return df.sort_values("spend_usd", ascending=False).reset_index(drop=True)


def family_summary(materials: pd.DataFrame) -> pd.DataFrame:
    """Spend share, spend-weighted supply risk and spend by quadrant for each family."""
    total = materials["spend_usd"].sum()
    rows = []
    for family, g in materials.groupby("family"):
        by_quadrant = g.groupby("quadrant")["spend_usd"].sum() / g["spend_usd"].sum()
        rows.append(
            {
                "family": family,
                "spend_share": g["spend_usd"].sum() / total,
                "supply_risk": (g["supply_risk"] * g["spend_usd"]).sum() / g["spend_usd"].sum(),
                **{f"{q}_share": by_quadrant.get(q, 0.0) for q in ACTIONS},
            }
        )
    return pd.DataFrame(rows).sort_values("spend_share", ascending=False).reset_index(drop=True)


def supplier_risk(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Risk score per supplier, its components and a tier (high from 50, medium from 30)."""
    mercosur = ", ".join(f"'{c}'" for c in sorted(MERCOSUR))
    df = con.execute(
        f"""
        WITH sole AS (
            SELECT material_id FROM v_po_lines
            GROUP BY 1 HAVING count(DISTINCT supplier_id) = 1
        )
        SELECT
            s.supplier_id, s.country, s.lead_time_days, s.ppm,
            sum(l.spend_usd) AS spend_usd,
            coalesce(sum(l.spend_usd) FILTER (WHERE l.material_id IN (SELECT * FROM sole)), 0)
                / sum(l.spend_usd) AS dependency,
            least(s.lead_time_days / {LEAD_TIME_SCALE_DAYS}, 1) AS lead_time,
            least(s.ppm / {PPM_SCALE}, 1) AS quality,
            CASE WHEN s.country IN ({mercosur}) THEN 0 ELSE 1 END AS import
        FROM suppliers AS s JOIN v_po_lines AS l USING (supplier_id)
        GROUP BY s.supplier_id, s.country, s.lead_time_days, s.ppm
        """
    ).df()
    df["risk_score"] = 100 * sum(w * df[k] for k, w in SUPPLIER_WEIGHTS.items())
    df["tier"] = pd.cut(
        df["risk_score"], [-1, 30, 50, 101], labels=["low", "medium", "high"], right=False
    ).astype(str)
    return df.sort_values("risk_score", ascending=False).reset_index(drop=True)


def supplier_actions(risk: pd.DataFrame, gaps: pd.DataFrame | None = None) -> pd.DataFrame:
    """Actions per supplier: renegotiate when flagged as overpriced, add a second source when
    a high-risk supplier holds mostly items it supplies alone."""
    lines = []
    for r in risk.itertuples():
        action = []
        if gaps is not None:
            flagged = gaps.loc[gaps["supplier_id"] == r.supplier_id, "flagged"]
            if len(flagged) and bool(flagged.iloc[0]):
                action.append("renegotiate against should-cost")
        if r.tier == "high" and r.dependency > 0.5:
            action.append("qualify a second source")
        lines.append({"supplier_id": r.supplier_id, "actions": "; ".join(action)})
    return risk.merge(pd.DataFrame(lines), on="supplier_id")
