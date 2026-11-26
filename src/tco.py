"""Total cost of ownership per unit, per material and supplier.

    landed    price x (1 + freight) x (1 + import duty, outside Mercosur)    see should_cost.landed
    carrying  landed x 20% a year x (lead time + 15 days of safety stock) / 365
    quality   PPM / 1,000,000 x (landed + USD 200 to sort, rework and handle each defect)
    TCO       landed + carrying + quality

Each supplier's best alternative (its BATNA, from the buyer's side) is the lowest-TCO other
source for the same material: another current supplier or a bidder in the latest RFQ.
"""

from datetime import date

import duckdb
import pandas as pd

from src import should_cost as sc

CARRYING_RATE = 0.20  # cost of capital, storage and obsolescence, per year
SAFETY_DAYS = 15
DEFECT_HANDLING_USD = 200.0


def unit_tco(price: float, country: str, ncm: str, lead_time_days: float, ppm: float) -> dict:
    landed = sc.landed(price, country, ncm)
    carrying = landed * CARRYING_RATE * (lead_time_days + SAFETY_DAYS) / 365
    quality = ppm / 1e6 * (landed + DEFECT_HANDLING_USD)
    return {
        "landed": landed,
        "carrying": carrying,
        "quality": quality,
        "tco": landed + carrying + quality,
    }


def _with_tco(df: pd.DataFrame) -> pd.DataFrame:
    parts = [unit_tco(r.price, r.country, r.ncm, r.lead_time_days, r.ppm) for r in df.itertuples()]
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(parts)], axis=1)


def pair_tco(con: duckdb.DuckDBPyConnection, since: date) -> pd.DataFrame:
    """TCO per material and current supplier since a date, with each pair's best alternative."""
    current = con.execute(
        """
        SELECT p.material_id, p.supplier_id, m.family, m.ncm, s.country, s.lead_time_days, s.ppm,
               sum(p.qty) AS qty, sum(p.qty * p.unit_price_usd) / sum(p.qty) AS price
        FROM purchase_orders AS p
        JOIN materials AS m USING (material_id)
        JOIN suppliers AS s USING (supplier_id)
        WHERE p.order_date >= ?
        GROUP BY ALL
        """,
        [since],
    ).df()
    bidders = con.execute(
        """
        SELECT q.material_id, q.supplier_id, m.ncm, s.country, s.lead_time_days, s.ppm,
               q.unit_price_usd AS price
        FROM quotes AS q
        JOIN materials AS m USING (material_id)
        JOIN suppliers AS s USING (supplier_id)
        """
    ).df()
    current = _with_tco(current)
    options = pd.concat([current[bidders.columns], bidders], ignore_index=True).drop_duplicates(
        ["material_id", "supplier_id"]
    )
    options = _with_tco(options)

    best = []
    for r in current.itertuples():
        alt = options[
            (options["material_id"] == r.material_id) & (options["supplier_id"] != r.supplier_id)
        ]
        if alt.empty:
            best.append((None, None))
        else:
            row = alt.loc[alt["tco"].idxmin()]
            best.append((row["supplier_id"], row["tco"]))
    current["batna_supplier"] = [b[0] for b in best]
    current["batna_tco"] = [b[1] for b in best]
    return current


def supplier_tco(pairs: pd.DataFrame) -> pd.DataFrame:
    """Spend, TCO and TCO uplift over price per supplier."""
    g = pairs.assign(spend=pairs["qty"] * pairs["price"], tco_spend=pairs["qty"] * pairs["tco"])
    out = g.groupby(["supplier_id", "country"], as_index=False)[["spend", "tco_spend"]].sum()
    out["tco_uplift"] = out["tco_spend"] / out["spend"] - 1
    return out.sort_values("tco_spend", ascending=False).reset_index(drop=True)
