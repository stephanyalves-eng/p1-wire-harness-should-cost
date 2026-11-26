# Assumptions

Two sets of assumptions, kept apart on purpose:

- **The synthetic purchasing base** describes a fictional automaker and its suppliers' true
  costs. No real company data is used. Values live in
  [`src/generate/config.py`](../src/generate/config.py).
- **The analyst's should-cost premises** are what a buyer would estimate without seeing those
  true costs. Values live in [`src/should_cost.py`](../src/should_cost.py); see the last section.

Values marked **to verify** are engineering estimates that still need a public source.

## Company

| Assumption | Value | Why |
|---|---|---|
| Vehicles built per year | 150,000 | A mid-size plant; keeps annual harness and connector spend around USD 50 M |
| Share of electric vehicles | 30% | Drives the volume of high-voltage harnesses and shielded connectors |
| Purchase order window | 24 months, Nov 2024 to Oct 2026 | Two full years for trend and PPV analysis |

## Part families

These are the "true" costs behind supplier prices. They sit close to, but deliberately not on,
the analyst's should-cost premises below, so the should-cost model has a realistic error.
Copper, labour minutes and other material are means per unit across the family's variants;
each variant is scaled by a size factor (lognormal, σ = 0.25).

| Family | NCM | Variants | Copper (g/unit) | Labour (min/unit) | Other material (USD) | Units per vehicle |
|---|---|---|---|---|---|---|
| Engine harness | 8544.30.00 | 25 | 600 | 50 | 11.00 | 1 |
| Body harness | 8544.30.00 | 30 | 1,200 | 80 | 19.00 | 1 |
| Instrument panel harness | 8544.30.00 | 25 | 900 | 62 | 15.00 | 1 |
| Door harness | 8544.30.00 | 25 | 250 | 16 | 3.80 | 4 |
| HV battery harness (EV only) | 8544.30.00 | 15 | 3,500 | 130 | 58.00 | 1 |
| Signal connector | 8536.69.90 | 90 | 3 | 0.28 | 0.09 | 120 |
| Power connector | 8536.69.90 | 60 | 25 | 0.85 | 0.37 | 20 |
| HV shielded connector (EV only) | 8536.69.10 | 30 | 120 | 6.5 | 3.70 | 3 |

True fully loaded labour cost by plant country, USD per hour: BR 9.5, MX 8.5, CN 7.5, PY 6.5,
RO 9.0, MA 4.5, DE 46, US 40, JP 36, KR 31. Overhead adds 18% to labour.

**To verify:** copper grams per family. The harness values add up to about 4 kg of copper per
combustion vehicle and about 7 kg per EV across these five families, a fraction of the
vehicle's total wiring. With 2025 copper and Brazilian labour, copper is 20–30% of a harness
price.

**Calibrated against the market (v1.0).** A first version of these costs (v0.1) used a flat
conversion cost per unit that put the base at about USD 41/kg for harnesses, against USD 23–29/kg
for the main import origins in Comex Stat, and 35–80% above the should-cost. Pricing labour in
the supplier's country brings low-cost origins to USD 25–26/kg and high-wage origins to
USD 44–58/kg, in line with import prices by origin.

**Plants, not headquarters (v1.0).** With every supplier producing in its home country, 48% of
spend sat with German, US, Korean and Japanese plants that cost 50–60% more in TCO than the
alternatives, which no real buyer would sustain. Global harness groups build in low-cost plants
close to their customers, so each supplier now has a plant country (which sets labour, freight
and import duty) and a headquarters country (context only). Most spend now comes from Brazil,
Mexico, Romania, Paraguay, China and Morocco; high-wage plants keep about 16%.

## Suppliers

| Assumption | Value | Why |
|---|---|---|
| Suppliers | 60: 36 harness makers, 24 connector makers | Each supplier sells only its own kind of part |
| Plant country mix | BR 30%, MX 15%, CN 15%, PY 12%, RO 8%, MA 7%, DE 5%, US 4%, JP 2%, KR 2% | Low-cost plants of global groups plus a local base; a few specialised high-wage plants |
| Headquarters | Drawn per plant: e.g. Romania mostly German groups, Paraguay Japanese and Korean, Mexico US | Context for the playbook; does not affect cost |
| Lead time | PY 10–20 d, BR 20–35, MX 30–45, MA 35–50, US 35–50, RO 40–55, DE 45–60, CN 60–90, JP/KR 60–80 | Distance and transport mode |
| Quality | PPM lognormal, median 150 | Used later in TCO as cost of quality |

## Sourcing and pricing

| Assumption | Value | Why |
|---|---|---|
| Single-source materials | 20% (60 of 300) | Plan requirement; feeds the risk score |
| Suppliers per multi-source material | 2 or 3, volume split at random | |
| Price formula | (copper × 1.05 scrap + other material + labour minutes × country rate × 1.18 overhead) × 1.12 margin × supplier factor × order noise | Bottom-up cost the should-cost model must recover |
| Copper lag | 3 months | Common lag in index-linked pricing |
| Supplier factor | Normal(1, 0.02) | Normal spread between competitive suppliers |
| Order noise | Normal(0, 0.02) | Order-to-order price variation |
| Overpriced suppliers | 3, markup uniform 8–15% | Hidden truth the analysis must find |

## Ordering and RFQs

| Assumption | Value | Why |
|---|---|---|
| Order cadence | Top 10% of materials by value monthly, next 30% every 3 months, rest every 4 months | Gives about 5,600 PO lines over 24 months |
| Quantity noise | Normal(1, 0.15) per order | Demand variation |
| RFQs | One per material in the last 3 months, 3 quotes each | Current suppliers plus other qualified suppliers of the same kind |

## Copper price

The generator prices orders with the real World Bank Pink Sheet copper series when it is
loaded in `copper_monthly` (`python -m src.data.download_pinksheet`), and records
`"copper_source": "provided"` in the truth file. Over the lagged window (Aug 2024 to Jul 2026)
copper ran from USD 8,916/t to USD 13,552/t.

Without that table, for example in tests and CI, it falls back to a seeded random walk starting
at USD 9,300/t (drift 0.3% and volatility 5% per month) and records `"copper_source": "synthetic"`.

## Hidden truth

`data/processed/generator_truth.json` lists the overpriced suppliers with their markup, the
number of single-source materials and the total spend. It is not loaded into the database, so
the analysis cannot read it; tests use it to check that the analysis finds what was injected.

## Should-cost premises (analyst)

The cost tree per unit, in [`src/should_cost.py`](../src/should_cost.py):

| Line | Rule |
|---|---|
| Copper | copper kg × (1 + 5% scrap) × Pink Sheet copper price, lagged 3 months |
| Other material | insulation, terminals, housings, tape, per family |
| Labour | labour minutes × fully loaded labour cost of the producing country |
| Overhead | 15% of labour |
| SG&A | 8% of manufacturing cost |
| Margin | 8% of manufacturing cost + SG&A |
| Landed in Brazil | ex works × (1 + freight) × (1 + import duty), duty only outside Mercosur |

| Family | Copper (g/unit) | Labour (min/unit) | Other material (USD) |
|---|---|---|---|
| Engine harness | 600 | 45 | 10.00 |
| Body harness | 1,200 | 75 | 18.00 |
| Instrument panel harness | 900 | 60 | 14.00 |
| Door harness | 250 | 15 | 3.50 |
| HV battery harness | 3,500 | 120 | 55.00 |
| Signal connector | 3 | 0.25 | 0.08 |
| Power connector | 25 | 0.8 | 0.35 |
| HV shielded connector | 120 | 6 | 3.50 |

Each material is scaled from its family by its own copper content.

**Labour cost, USD per hour, to verify** against ILO or national statistics: BR 9, PY 6, AR 10,
MX 8, RO 8.5, MA 4, CN 7, TH 6, IN 4, KR 30, JP 35, DE 45, US 38.

**Freight and insurance to the plant**, share of ex-works value: BR 2%, PY and AR 3%, MX, US, DE,
RO and MA 5%, Asian origins 6%.

## TCO premises

| Line | Rule |
|---|---|
| Landed | price × (1 + freight) × (1 + import duty outside Mercosur) |
| Carrying | landed × 20% a year × (lead time + 15 days of safety stock) / 365 |
| Quality | PPM / 1,000,000 × (landed + USD 200 to sort, rework and handle each defect) |

The 20% carrying rate and the USD 200 per defect are **to verify** against the plant's own
cost of capital and quality cost data.

**Import duty** from [`data/reference/import_duty.csv`](../data/reference/import_duty.csv)
(16% for 8544.30.00 and 8536.69.90, 14.4% for 8536.69.10), applied to the freight-inclusive
value. Mercosur origins (AR, PY, UY) are duty-free, subject to rules of origin.

**Copper as a share of harness mass: 60%, to verify.** Used only to convert should-cost per
unit into USD/kg for calibration against Comex Stat.

**Calibration result (2025, copper averaged over the lagged year).** Should-cost per kg against
the import price per kg: Paraguay 0.97, Thailand 1.02, Germany 0.98, Japan 1.12, China 0.78.
Mexico, the United States and Argentina come in at 0.4–0.6: they ship small, likely more
complex volumes, so they are not used to tune the premises. Connectors could not be calibrated:
Comex Stat unit prices for the same NCM range from USD 0.35 to USD 28 per unit across origins,
because origins count units differently. Connector should-cost relies on the bottom-up tree only.
