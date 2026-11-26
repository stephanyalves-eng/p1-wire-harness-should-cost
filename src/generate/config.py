"""Assumptions for the synthetic purchasing base.

Every number here is a modelling choice, explained in docs/assumptions.md. Change a value
here, not inside the generator, so the base stays reproducible and reviewable.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Family:
    name: str
    kind: str  # "harness" or "connector"
    ncm: str
    n_materials: int
    copper_g: float  # mean copper content per unit, grams
    labor_min: float  # true labour minutes per unit at the family's mean size
    other_material_usd: float  # insulation, terminals, housings, tape per unit
    units_per_vehicle: float  # across all variants of the family
    ev_only: bool = False


# The "true" costs behind supplier prices. They sit close to, but not on, the analyst's
# should-cost premises in src/should_cost.py, so the model has a realistic error to show.
FAMILIES = (
    Family("harness_engine", "harness", "85443000", 25, 600, 50, 11.0, 1),
    Family("harness_body", "harness", "85443000", 30, 1200, 80, 19.0, 1),
    Family("harness_instrument_panel", "harness", "85443000", 25, 900, 62, 15.0, 1),
    Family("harness_door", "harness", "85443000", 25, 250, 16, 3.8, 4),
    Family("harness_hv_battery", "harness", "85443000", 15, 3500, 130, 58.0, 1, ev_only=True),
    Family("connector_signal", "connector", "85366990", 90, 3, 0.28, 0.09, 120),
    Family("connector_power", "connector", "85366990", 60, 25, 0.85, 0.37, 20),
    Family("connector_hv_shielded", "connector", "85366910", 30, 120, 6.5, 3.7, 3, ev_only=True),
)


@dataclass(frozen=True)
class Config:
    seed: int = 42
    start_month: str = "2024-11-01"  # 24 months of purchase orders
    n_months: int = 24

    # Fictional automaker
    vehicles_per_year: int = 150_000
    ev_share: float = 0.30

    # Supplier base
    n_suppliers: int = 60
    harness_supplier_share: float = 0.6  # the rest supply connectors
    countries: dict = field(
        default_factory=lambda: {
            # country: (share of suppliers, lead time range in days)
            "BR": (0.40, (20, 35)),
            "MX": (0.15, (30, 45)),
            "CN": (0.15, (60, 90)),
            "DE": (0.10, (45, 60)),
            "US": (0.10, (35, 50)),
            "JP": (0.05, (60, 80)),
            "KR": (0.05, (60, 80)),
        }
    )
    ppm_median: float = 150.0

    # Sourcing
    single_source_share: float = 0.20
    max_suppliers_per_material: int = 3

    # Pricing: price = (copper + other material + labour x (1 + overhead)) x (1 + margin)
    #                  x supplier factor x order noise, with labour priced in the supplier's country
    copper_lag_months: int = 3
    copper_scrap_rate: float = 0.05
    labor_usd_h: dict = field(
        default_factory=lambda: {
            "BR": 9.5,
            "MX": 8.5,
            "CN": 7.5,
            "DE": 46.0,
            "US": 40.0,
            "JP": 36.0,
            "KR": 31.0,
        }
    )
    overhead_on_labor: float = 0.18
    margin: float = 0.12
    supplier_factor_sd: float = 0.02  # normal pricing spread between suppliers
    price_noise_sd: float = 0.02  # order-to-order noise
    n_overpriced: int = 3
    overprice_range: tuple = (0.08, 0.15)

    # Ordering cadence by material value rank (share of materials, months between orders)
    cadence: tuple = ((0.10, 1), (0.30, 3), (0.60, 4))
    qty_noise_sd: float = 0.15

    # RFQs: one per material in the last months of the window, 3 quotes each
    quotes_per_rfq: int = 3
    rfq_window_months: int = 3

    # Synthetic copper path, used only until the Pink Sheet series is loaded
    copper_start_usd_t: float = 9_300.0
    copper_monthly_drift: float = 0.003
    copper_monthly_vol: float = 0.05


DEFAULT = Config()
