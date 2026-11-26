# Wire harness and connector should-cost

Technical design and backlog map: [docs/BLUEPRINT.md](docs/BLUEPRINT.md).

## Business question

What target price and sourcing strategy should a fictional automaker use for wire harnesses and connectors, and which copper price-adjustment clause minimizes total risk for both buyer and supplier?

**Problem statement**

1. Wire harnesses and connectors are critical, copper-heavy parts, and their prices move with copper, the exchange rate and supplier concentration.
2. The buyer pays quotes without an independent cost reference, so overpricing and single-source exposure go unnoticed.
3. Contracts either freeze prices for a year or pass every copper move through, shifting all the risk to one side of the table.
4. This project builds a bottom-up should-cost, calibrated on public import prices, and backtests four copper clauses over 2016–2026.
5. The output is a target price per part family, a sourcing strategy per supplier and a recommended clause for each side.

**KPIs**

| KPI | Definition | Unit |
|---|---|---|
| Should-cost gap | (quoted price − should-cost) / should-cost, per part family and supplier | % |
| Potential savings | Σ (quoted price − should-cost) × annual volume, for items with a gap above 10% | USD/year |
| Copper exposure | Change in annual spend for a 10% move in the copper price | USD per 10% |

**Scope of the category**

| NCM | Official description (Comex Stat) | Statistical unit | Import duty (II) |
|---|---|---|---|
| 8544.30.00 | Jogos de fios para velas de ignição e outros jogos de fios dos tipos utilizados em quaisquer veículos | kg (net) | 16.0% |
| 8536.69.10 | Tomada polarizada e tomada blindada, para uma tensão não superior a 1.000 V | units | 14.4% |
| 8536.69.90 | Outras tomadas de corrente, para uma tensão não superior a 1.000 V | units | 16.0% |

Connectors are counted in units, not kilograms, so the market analysis reports USD/kg for harnesses and both USD/kg (from net weight) and USD/unit for connectors.

Import duty rates are the reference TEC rates consulted on 2026-11-26 and are applied to imported supplies in the should-cost and TCO. They are kept in [data/reference/import_duty.csv](data/reference/import_duty.csv).

## Result

## Data

- **Synthetic purchasing base** for a fictional automaker: 60 suppliers, 300 materials, about 5,500 purchase order lines over 24 months and 300 RFQs with 3 quotes each, about USD 55 M of spend per year. Prices are built bottom-up from the real copper price (World Bank Pink Sheet, lagged 3 months), other material and conversion cost; three suppliers carry a hidden markup. Every assumption is listed in [docs/assumptions.md](docs/assumptions.md).
- Public sources and extraction dates are logged in [data/README.md](data/README.md).

## Method

1. **Spend baseline** ([notebooks/01_spend.ipynb](notebooks/01_spend.ipynb)): spend cube by family, supplier country and year; ABC Pareto (A while cumulative spend before the item is under 80%, B under 95%); single-source exposure; purchase price variance against the last price paid. The SQL lives in [sql/views.sql](sql/views.sql), and `python -m src.validate` checks the base before any analysis.
2. **Market intelligence** ([notebooks/02_market.ipynb](notebooks/02_market.ipynb)): Comex Stat implied import prices (USD/kg, and USD/unit for connectors), origin concentration (HHI) and the correlation of import prices with copper at lags of 0 to 6 months. Harness imports run at about USD 30/kg with Paraguay supplying close to half; month-to-month import prices barely follow copper, so the should-cost takes copper pass-through from its cost tree and calibrates on annual averages.

## Limitations

## How to run

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
nbstripout --install            # once per clone: strips notebook outputs on commit
python -m src.data.download_pinksheet   # loads the copper series into copper_monthly
python -m src.generate.purchasing   # builds data/processed/purchasing.duckdb
python -m src.data.download_comexstat   # loads Comex Stat imports into market_monthly
```

Before committing:

```bash
ruff check .
ruff format .
pytest
```

## How AI was used
