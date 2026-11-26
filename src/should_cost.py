"""Bottom-up should-cost for wire harnesses and connectors.

Cost tree per unit, built from the analyst's own premises (not the generator's):

    copper          = copper kg x (1 + scrap) x copper price (USD/t / 1000)
    other material  = insulation, terminals, housings, tape
    labour          = labour minutes / 60 x fully loaded labour cost of the producing country
    overhead        = share of labour
    manufacturing   = copper + other material + labour + overhead
    SG&A            = share of manufacturing
    margin          = share of manufacturing + SG&A
    ex works        = manufacturing + SG&A + margin
    landed (Brazil) = ex works x (1 + freight) x (1 + import duty, outside Mercosur)

Every premise lives in this module and is explained in docs/assumptions.md. Values marked
"to verify" there are engineering estimates waiting for a public source.
"""

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.db import ROOT
from src.generate.config import DEFAULT, FAMILIES

DUTY_TABLE = ROOT / "data" / "reference" / "import_duty.csv"
COMPONENTS = ("copper", "other_material", "labor", "overhead", "sga", "margin")


@dataclass(frozen=True)
class FamilyPremise:
    family: str
    kind: str  # "harness" or "connector"
    ncm: str
    copper_g: float  # reference copper content for the family
    other_material_usd: float  # at the reference copper content
    labor_min: float  # at the reference copper content


@dataclass(frozen=True)
class Rates:
    copper_scrap: float = 0.05
    overhead_on_labor: float = 0.15
    sga: float = 0.08
    margin: float = 0.08
    copper_mass_share: float = 0.60  # copper as a share of harness mass, for USD/kg calibration


# Analyst premises per family. Labour minutes cover cutting, crimping, assembly board work,
# taping and electrical test for harnesses; moulding, stamping and assembly for connectors.
FAMILY_PREMISES = (
    FamilyPremise("harness_engine", "harness", "85443000", 600, 10.0, 45),
    FamilyPremise("harness_body", "harness", "85443000", 1200, 18.0, 75),
    FamilyPremise("harness_instrument_panel", "harness", "85443000", 900, 14.0, 60),
    FamilyPremise("harness_door", "harness", "85443000", 250, 3.5, 15),
    FamilyPremise("harness_hv_battery", "harness", "85443000", 3500, 55.0, 120),
    FamilyPremise("connector_signal", "connector", "85366990", 3, 0.08, 0.25),
    FamilyPremise("connector_power", "connector", "85366990", 25, 0.35, 0.8),
    FamilyPremise("connector_hv_shielded", "connector", "85366910", 120, 3.5, 6),
)
BY_FAMILY = {p.family: p for p in FAMILY_PREMISES}

# Fully loaded manufacturing labour cost, USD per hour (to verify against ILO / national data).
LABOR_USD_H = {
    "BR": 9.0,
    "PY": 6.0,
    "AR": 10.0,
    "MX": 8.0,
    "CN": 7.0,
    "TH": 6.0,
    "IN": 4.0,
    "KR": 30.0,
    "JP": 35.0,
    "DE": 45.0,
    "US": 38.0,
}

# Freight and insurance to the plant in Brazil, as a share of ex-works value.
FREIGHT = {
    "BR": 0.02,
    "PY": 0.03,
    "AR": 0.03,
    "MX": 0.05,
    "US": 0.05,
    "DE": 0.05,
    "CN": 0.06,
    "TH": 0.06,
    "IN": 0.06,
    "JP": 0.06,
    "KR": 0.06,
}

# Mercosur members trade duty-free inside the zone (subject to rules of origin).
MERCOSUR = {"BR", "AR", "PY", "UY"}

# Country names as Comex Stat reports them, for calibration.
COMEX_COUNTRY = {
    "Brazil": "BR",
    "Paraguay": "PY",
    "Argentina": "AR",
    "Mexico": "MX",
    "China": "CN",
    "Thailand": "TH",
    "India": "IN",
    "South Korea": "KR",
    "Japan": "JP",
    "Germany": "DE",
    "United States": "US",
}


def _duty_table(path: Path = DUTY_TABLE) -> dict[str, float]:
    duty = pd.read_csv(path, dtype={"ncm": str})
    return dict(zip(duty["ncm"], duty["ii_pct"] / 100, strict=True))


DUTY = _duty_table()


def import_duty(ncm: str, origin: str) -> float:
    """Import duty rate (0–1) for goods of this NCM from this origin country."""
    return 0.0 if origin in MERCOSUR else DUTY[ncm]


def cost_tree(
    premise: FamilyPremise,
    copper_usd_t: float,
    labor_usd_h: float,
    rates: Rates = Rates(),
    copper_g: float | None = None,
) -> dict[str, float]:
    """Should-cost per unit. A variant is scaled by its copper content against the family's."""
    grams = premise.copper_g if copper_g is None else copper_g
    size = grams / premise.copper_g
    copper = grams / 1000 * (1 + rates.copper_scrap) * copper_usd_t / 1000
    other = premise.other_material_usd * size
    labor = premise.labor_min * size / 60 * labor_usd_h
    overhead = labor * rates.overhead_on_labor
    manufacturing = copper + other + labor + overhead
    sga = manufacturing * rates.sga
    margin = (manufacturing + sga) * rates.margin
    tree = {
        "copper": copper,
        "other_material": other,
        "labor": labor,
        "overhead": overhead,
        "sga": sga,
        "margin": margin,
    }
    tree["ex_works"] = sum(tree.values())
    return tree


def landed(ex_works: float, origin: str, ncm: str) -> float:
    """Cost delivered to the plant in Brazil: freight, then duty on the CIF value."""
    cif = ex_works * (1 + FREIGHT[origin])
    return cif * (1 + import_duty(ncm, origin))


def mass_kg(premise: FamilyPremise, rates: Rates = Rates(), copper_g: float | None = None) -> float:
    grams = premise.copper_g if copper_g is None else copper_g
    return grams / 1000 / rates.copper_mass_share


def material_should_cost(
    materials: pd.DataFrame,
    pairs: pd.DataFrame,
    countries: pd.DataFrame,
    copper_usd_t: float,
    rates: Rates = Rates(),
) -> pd.DataFrame:
    """Should-cost for every material and supplier, using the supplier's country."""
    df = pairs.merge(materials, on="material_id").merge(countries, on="supplier_id")
    rows = []
    for r in df.itertuples():
        premise = BY_FAMILY[r.family]
        tree = cost_tree(premise, copper_usd_t, LABOR_USD_H[r.country], rates, r.copper_g_per_unit)
        rows.append(
            {
                "material_id": r.material_id,
                "supplier_id": r.supplier_id,
                "family": r.family,
                "country": r.country,
                **{f"{k}_usd": v for k, v in tree.items() if k != "ex_works"},
                "ex_works_usd": tree["ex_works"],
                "landed_usd": landed(tree["ex_works"], r.country, r.ncm),
            }
        )
    return pd.DataFrame(rows)


def _vehicle_mix(kind: str) -> dict[str, float]:
    """Units per vehicle by family, EV families weighted by the EV share of production."""
    mix = {}
    for f in FAMILIES:
        if f.kind == kind:
            mix[f.name] = f.units_per_vehicle * (DEFAULT.ev_share if f.ev_only else 1.0)
    return mix


def calibrate_harness(
    market: pd.DataFrame, copper_usd_t: float, rates: Rates = Rates()
) -> pd.DataFrame:
    """Compare should-cost per kg with the import price per kg, origin by origin.

    `market` has one row per origin with `country` (Comex Stat name), `usd_per_kg` and
    `usd_fob`. The should-cost per kg is the mass-weighted average over the harness families,
    weighted by units per vehicle.
    """
    mix = _vehicle_mix("harness")
    rows = []
    for m in market.itertuples():
        origin = COMEX_COUNTRY.get(m.country)
        if origin is None:
            continue
        cost = kg = 0.0
        for family, units in mix.items():
            premise = BY_FAMILY[family]
            cost += units * cost_tree(premise, copper_usd_t, LABOR_USD_H[origin], rates)["ex_works"]
            kg += units * mass_kg(premise, rates)
        rows.append(
            {
                "origin": m.country,
                "import_usd_kg": m.usd_per_kg,
                "import_usd_m": m.usd_fob / 1e6,
                "should_cost_usd_kg": cost / kg,
            }
        )
    out = pd.DataFrame(rows)
    out["ratio"] = out["should_cost_usd_kg"] / out["import_usd_kg"]
    return out


def calibrate_connectors(
    market: pd.DataFrame, copper_usd_t: float, rates: Rates = Rates()
) -> pd.DataFrame:
    """Compare should-cost per unit with the import price per unit, per NCM and origin.

    `market` has `ncm`, `country`, `usd_per_unit` and `usd_fob`. 8536.69.90 mixes signal and
    power connectors, weighted by units per vehicle; 8536.69.10 is the shielded HV connector.
    """
    mix = _vehicle_mix("connector")
    rows = []
    for m in market.itertuples():
        origin = COMEX_COUNTRY.get(m.country)
        if origin is None:
            continue
        families = {f: u for f, u in mix.items() if BY_FAMILY[f].ncm == m.ncm}
        units = sum(families.values())
        cost = sum(
            u * cost_tree(BY_FAMILY[f], copper_usd_t, LABOR_USD_H[origin], rates)["ex_works"]
            for f, u in families.items()
        )
        rows.append(
            {
                "ncm": m.ncm,
                "origin": m.country,
                "import_usd_unit": m.usd_per_unit,
                "import_usd_m": m.usd_fob / 1e6,
                "should_cost_usd_unit": cost / units,
            }
        )
    out = pd.DataFrame(rows)
    out["ratio"] = out["should_cost_usd_unit"] / out["import_usd_unit"]
    return out
