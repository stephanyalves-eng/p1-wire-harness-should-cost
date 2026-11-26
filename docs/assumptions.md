# Assumptions for the synthetic purchasing base

The base describes a fictional automaker. No real company data is used. All values live in
[`src/generate/config.py`](../src/generate/config.py); this page explains them. Values marked
**to verify** are engineering estimates that still need a public source.

## Company

| Assumption | Value | Why |
|---|---|---|
| Vehicles built per year | 150,000 | A mid-size plant; keeps annual harness and connector spend around USD 50 M |
| Share of electric vehicles | 30% | Drives the volume of high-voltage harnesses and shielded connectors |
| Purchase order window | 24 months, Nov 2024 to Oct 2026 | Two full years for trend and PPV analysis |

## Part families

Copper is the mean per unit across the family's variants; each variant is scaled by a size
factor (lognormal, σ = 0.25) that also scales conversion and other material cost.

| Family | NCM | Variants | Copper (g/unit) | Conversion (USD) | Other material (USD) | Units per vehicle |
|---|---|---|---|---|---|---|
| Engine harness | 8544.30.00 | 25 | 600 | 18.00 | 12.00 | 1 |
| Body harness | 8544.30.00 | 30 | 1,200 | 30.00 | 20.00 | 1 |
| Instrument panel harness | 8544.30.00 | 25 | 900 | 24.00 | 16.00 | 1 |
| Door harness | 8544.30.00 | 25 | 250 | 6.00 | 4.00 | 4 |
| HV battery harness (EV only) | 8544.30.00 | 15 | 3,500 | 90.00 | 60.00 | 1 |
| Signal connector | 8536.69.90 | 90 | 3 | 0.15 | 0.10 | 120 |
| Power connector | 8536.69.90 | 60 | 25 | 0.60 | 0.40 | 20 |
| HV shielded connector (EV only) | 8536.69.10 | 30 | 120 | 6.00 | 4.00 | 3 |

**To verify:** copper grams per family. The harness values add up to about 4 kg of copper per
combustion vehicle and about 7 kg per EV across these five families, a fraction of the
vehicle's total wiring. Conversion and other material costs are set so that copper is roughly
10–20% of a harness price, in line with conversion-heavy manual assembly.

## Suppliers

| Assumption | Value | Why |
|---|---|---|
| Suppliers | 60: 36 harness makers, 24 connector makers | Each supplier sells only its own kind of part |
| Country mix | BR 40%, MX 15%, CN 15%, DE 10%, US 10%, JP 5%, KR 5% | Local base plus typical import origins for the category |
| Lead time | BR 20–35 d, MX 30–45, US 35–50, DE 45–60, CN 60–90, JP/KR 60–80 | Distance and transport mode |
| Quality | PPM lognormal, median 150 | Used later in TCO as cost of quality |

## Sourcing and pricing

| Assumption | Value | Why |
|---|---|---|
| Single-source materials | 20% (60 of 300) | Plan requirement; feeds the risk score |
| Suppliers per multi-source material | 2 or 3, volume split at random | |
| Price formula | (copper × 1.05 scrap + other material + conversion) × 1.12 margin × supplier factor × order noise | Bottom-up cost the should-cost model must recover |
| Copper lag | 3 months | Common lag in index-linked pricing |
| Supplier factor | Normal(1, 0.02) | Normal spread between competitive suppliers |
| Order noise | Normal(0, 0.02) | Order-to-order price variation |
| Overpriced suppliers | 3, markup uniform 8–15% | Hidden truth the analysis must find |

## Ordering and RFQs

| Assumption | Value | Why |
|---|---|---|
| Order cadence | Top 10% of materials by value monthly, next 30% every 3 months, rest every 4 months | Gives ~5,500 PO lines over 24 months |
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
