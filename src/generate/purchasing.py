"""Synthetic purchasing base for a fictional automaker: suppliers, materials, POs and quotes.

Prices are built bottom-up so the should-cost model has something real to recover:

    unit price = (copper cost, lagged + other material + labour x (1 + overhead))
                 x (1 + margin) x supplier factor x order noise

Labour is priced at the supplier's country rate, so a German harness costs more than a
Chinese one, as in the import data.

Three suppliers carry a hidden markup. That truth is returned in `Base.truth` and written to
a JSON file beside the database, never into it, so the analysis has to find them on its own.

Run:  python -m src.generate.purchasing  [--db PATH] [--seed N]
"""

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.db import DEFAULT_DB, connect, create_schema
from src.generate.config import DEFAULT, FAMILIES, Config


@dataclass
class Base:
    suppliers: pd.DataFrame
    materials: pd.DataFrame
    purchase_orders: pd.DataFrame
    quotes: pd.DataFrame
    supplier_kind: pd.DataFrame  # harness or connector; not stored in the database
    truth: dict
    material_costs: pd.DataFrame  # true labour minutes and other material; not stored either


def months(cfg: Config) -> pd.DatetimeIndex:
    return pd.date_range(cfg.start_month, periods=cfg.n_months, freq="MS")


def synthetic_copper(cfg: Config, volatility: float | None = None) -> pd.Series:
    """Monthly copper price in USD/t, a seeded random walk covering the lag before the window."""
    vol = cfg.copper_monthly_vol if volatility is None else volatility
    idx = pd.date_range(
        pd.Timestamp(cfg.start_month) - pd.DateOffset(months=cfg.copper_lag_months),
        periods=cfg.n_months + cfg.copper_lag_months,
        freq="MS",
    )
    rng = np.random.default_rng(cfg.seed + 1)
    steps = rng.normal(cfg.copper_monthly_drift, vol, len(idx)) if vol else np.zeros(len(idx))
    steps[0] = 0.0
    return pd.Series(cfg.copper_start_usd_t * np.exp(np.cumsum(steps)), index=idx)


def _suppliers(cfg: Config, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    countries = list(cfg.countries)
    shares = np.array([cfg.countries[c][0] for c in countries])
    picked = rng.choice(countries, size=cfg.n_suppliers, p=shares / shares.sum())
    lead = [rng.integers(*cfg.countries[c][1], endpoint=True) for c in picked]
    hq = []
    for c in picked:
        groups = cfg.countries[c][2]
        hq.append(rng.choice(list(groups), p=list(groups.values())))
    ids = [f"S{i:03d}" for i in range(1, cfg.n_suppliers + 1)]
    n_harness = round(cfg.n_suppliers * cfg.harness_supplier_share)
    suppliers = pd.DataFrame(
        {
            "supplier_id": ids,
            "name": [f"Supplier {i[1:]}" for i in ids],
            "country": picked,
            "lead_time_days": np.array(lead, dtype=int),
            "ppm": rng.lognormal(np.log(cfg.ppm_median), 0.6, cfg.n_suppliers).round(1),
            "hq_country": hq,
        }
    )
    kind = pd.DataFrame(
        {
            "supplier_id": ids,
            "kind": ["harness"] * n_harness + ["connector"] * (len(ids) - n_harness),
        }
    )
    return suppliers, kind


def _materials(cfg: Config, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for fam in FAMILIES:
        size = rng.lognormal(0.0, 0.25, fam.n_materials)  # variants differ in size
        mix = rng.dirichlet(np.full(fam.n_materials, 2.0))  # share of the family's volume
        vehicles = cfg.vehicles_per_year * (cfg.ev_share if fam.ev_only else 1.0)
        for k in range(fam.n_materials):
            rows.append(
                {
                    "family": fam.name,
                    "kind": fam.kind,
                    "ncm": fam.ncm,
                    "description": f"{fam.name.replace('_', ' ')} variant {k + 1:02d}",
                    "copper_g_per_unit": round(fam.copper_g * size[k], 1),
                    "labor_min": fam.labor_min * size[k],
                    "other_material_usd": fam.other_material_usd * size[k],
                    "annual_volume": fam.units_per_vehicle * vehicles * mix[k],
                }
            )
    mat = pd.DataFrame(rows)
    mat.insert(0, "material_id", [f"M{i:03d}" for i in range(1, len(mat) + 1)])
    mat["unit_of_measure"] = "unit"
    n_single = round(len(mat) * cfg.single_source_share)
    mat["single_source"] = False
    mat.loc[rng.choice(len(mat), n_single, replace=False), "single_source"] = True
    return mat


def _assign(cfg, rng, mat, kind) -> pd.DataFrame:
    """Which suppliers sell each material, and their share of its volume."""
    pools = {
        k: kind.loc[kind["kind"] == k, "supplier_id"].to_numpy() for k in ("harness", "connector")
    }
    rows = []
    for m in mat.itertuples():
        n = 1 if m.single_source else rng.integers(2, cfg.max_suppliers_per_material, endpoint=True)
        chosen = rng.choice(pools[m.kind], n, replace=False)
        shares = rng.dirichlet(np.full(n, 3.0)) if n > 1 else np.array([1.0])
        rows += [
            {"material_id": m.material_id, "supplier_id": s, "share": sh}
            for s, sh in zip(chosen, shares, strict=True)
        ]
    return pd.DataFrame(rows)


def unit_price(cfg, mat_row, country, factor, copper_usd_t, noise=0.0):
    """True price of one unit of a generated material from a supplier in `country`."""
    copper = copper_usd_t / 1e6 * mat_row.copper_g_per_unit * (1 + cfg.copper_scrap_rate)
    labor = mat_row.labor_min / 60 * cfg.labor_usd_h[country] * (1 + cfg.overhead_on_labor)
    cost = copper + mat_row.other_material_usd + labor
    return cost * (1 + cfg.margin) * factor * (1 + noise)


def generate(cfg: Config = DEFAULT, copper: pd.Series | None = None) -> Base:
    rng = np.random.default_rng(cfg.seed)
    copper_source = "provided" if copper is not None else "synthetic"
    copper = synthetic_copper(cfg) if copper is None else copper

    suppliers, kind = _suppliers(cfg, rng)
    mat = _materials(cfg, rng)
    pairs = _assign(cfg, rng, mat, kind)

    # Supplier pricing level, with a hidden markup for a few suppliers that sell something.
    factor = dict(
        zip(kind["supplier_id"], rng.normal(1.0, cfg.supplier_factor_sd, len(kind)), strict=True)
    )
    selling = sorted(pairs["supplier_id"].unique())
    overpriced = {
        s: round(float(rng.uniform(*cfg.overprice_range)), 4)
        for s in rng.choice(selling, cfg.n_overpriced, replace=False)
    }
    for s, markup in overpriced.items():
        factor[s] *= 1 + markup

    # Ordering cadence by expected annual spend rank.
    base_price = mat.apply(lambda r: unit_price(cfg, r, "BR", 1.0, copper.iloc[0]), axis=1)
    rank = (mat["annual_volume"] * base_price).rank(ascending=False, method="first") / len(mat)
    cuts = np.cumsum([c[0] for c in cfg.cadence])
    mat["cadence"] = [cfg.cadence[int(np.searchsorted(cuts, r))][1] for r in rank]

    lead = suppliers.set_index("supplier_id")["lead_time_days"]
    country = suppliers.set_index("supplier_id")["country"]
    by_id = mat.set_index("material_id")
    window = months(cfg)
    lines = []
    for p in pairs.itertuples():
        m = by_id.loc[p.material_id]
        every = int(m.cadence)
        offset = rng.integers(0, every)
        for i in range(offset, len(window), every):
            month = window[i]
            qty = m.annual_volume * p.share * every / 12 * max(0.1, rng.normal(1, cfg.qty_noise_sd))
            order = month + pd.Timedelta(days=int(rng.integers(0, 28)))
            delivery = order + pd.Timedelta(
                days=max(0, int(lead[p.supplier_id] + rng.integers(-3, 8)))
            )
            lagged = copper.loc[month - pd.DateOffset(months=cfg.copper_lag_months)]
            noise = rng.normal(0, cfg.price_noise_sd)
            lines.append(
                {
                    "material_id": p.material_id,
                    "supplier_id": p.supplier_id,
                    "order_date": order,
                    "delivery_date": delivery,
                    "qty": max(1, round(qty)),
                    "unit_price_usd": round(
                        unit_price(
                            cfg, m, country[p.supplier_id], factor[p.supplier_id], lagged, noise
                        ),
                        4,
                    ),
                    "month": month,
                }
            )
    po = pd.DataFrame(lines).sort_values(["month", "supplier_id", "order_date", "material_id"])
    po["po_id"] = (
        po.groupby(["month", "supplier_id"], sort=False).ngroup().map(lambda n: f"PO{n + 1:05d}")
    )
    po["po_line"] = po.groupby("po_id").cumcount() + 1
    po = po[
        [
            "po_id",
            "po_line",
            "material_id",
            "supplier_id",
            "order_date",
            "delivery_date",
            "qty",
            "unit_price_usd",
        ]
    ].reset_index(drop=True)

    quotes = []
    pool = kind.groupby("kind")["supplier_id"].apply(list).to_dict()
    for n, m in enumerate(mat.itertuples(), start=1):
        current = list(pairs.loc[pairs["material_id"] == m.material_id, "supplier_id"])
        others = [s for s in pool[m.kind] if s not in current]
        bidders = current + list(
            rng.choice(others, cfg.quotes_per_rfq - len(current), replace=False)
        )
        month = window[rng.integers(len(window) - cfg.rfq_window_months, len(window))]
        quote_date = month + pd.Timedelta(days=int(rng.integers(0, 28)))
        lagged = copper.loc[month - pd.DateOffset(months=cfg.copper_lag_months)]
        for s in bidders[: cfg.quotes_per_rfq]:
            price = unit_price(
                cfg, m, country[s], factor[s], lagged, rng.normal(0, cfg.price_noise_sd)
            )
            quotes.append(
                {
                    "rfq_id": f"RFQ{n:04d}",
                    "material_id": m.material_id,
                    "supplier_id": s,
                    "quote_date": quote_date,
                    "unit_price_usd": round(price, 4),
                }
            )

    materials = mat[
        [
            "material_id",
            "description",
            "family",
            "ncm",
            "unit_of_measure",
            "copper_g_per_unit",
            "single_source",
        ]
    ]
    truth = {
        "seed": cfg.seed,
        "copper_source": copper_source,
        "overpriced_suppliers": dict(sorted(overpriced.items())),
        "single_source_materials": int(materials["single_source"].sum()),
        "po_lines": len(po),
        "total_spend_usd": float((po["qty"] * po["unit_price_usd"]).sum()),
    }
    costs = mat[["material_id", "copper_g_per_unit", "labor_min", "other_material_usd"]]
    return Base(suppliers, materials, po, pd.DataFrame(quotes), kind, truth, costs)


def load(con: duckdb.DuckDBPyConnection, base: Base) -> None:
    """Replace the purchasing tables with a generated base, children last-in first-out."""
    for table in ("quotes", "purchase_orders", "materials", "suppliers"):
        con.execute(f"DELETE FROM {table}")
    for table in ("suppliers", "materials", "purchase_orders", "quotes"):
        frame = getattr(base, table)  # noqa: F841 - read by DuckDB through the name below
        con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM frame")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--seed", type=int, default=DEFAULT.seed)
    args = parser.parse_args()

    cfg = replace(DEFAULT, seed=args.seed)
    con = connect(args.db)
    create_schema(con)
    copper = con.execute("SELECT month, copper_usd_t FROM copper_monthly ORDER BY month").df()
    series = (
        copper.set_index(pd.to_datetime(copper["month"]))["copper_usd_t"] if len(copper) else None
    )
    base = generate(cfg, copper=series)
    load(con, base)
    truth_path = args.db.with_name("generator_truth.json")
    truth_path.write_text(json.dumps(base.truth, indent=2), encoding="utf-8")
    print(
        f"{len(base.suppliers)} suppliers, {len(base.materials)} materials, "
        f"{len(base.purchase_orders)} PO lines, {len(base.quotes)} quotes, "
        f"spend USD {base.truth['total_spend_usd'] / 1e6:,.1f}M over {cfg.n_months} months "
        f"(copper: {base.truth['copper_source']}). Truth written to {truth_path}."
    )


if __name__ == "__main__":
    main()
