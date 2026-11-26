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

*Status: spend baseline, market intelligence, should-cost, supplier gaps and the copper clause. Category strategy, TCO and recommendations come next.*

**Spend baseline (synthetic base, about USD 50 M per year).** Harnesses take 82% of spend; body harnesses alone are 23%. 104 of 300 materials (35%) make up 80% of spend, and single-source items are 20% of materials but 26% of spend.

![Annual spend by part family](reports/figures/spend_by_family.png)
![ABC Pareto](reports/figures/abc_pareto.png)

**Market (real Comex Stat imports, 2019–2026).** Harness imports cost about USD 30/kg in 2025–2026, up from USD 25.6/kg in 2019. Month to month, import prices barely follow copper, so the should-cost will take copper pass-through from its cost tree rather than from market correlation. The April 2020 spike is a low-volume pandemic month.

![Harness import price vs. copper](reports/figures/harness_price_vs_copper.png)

**Origin risk.** Harness imports are highly concentrated, with Paraguay supplying 46–58% of value every year; shielded connectors depend on China for about 60%.

![Concentration of import origins](reports/figures/origin_hhi.png)

**Should-cost.** A bottom-up cost tree (copper, other material, labour by country, overhead, SG&A, margin, freight and import duty) lands within 3% of the 2025 import price per kg for Paraguay, Thailand and Germany, and within 12% for Japan. China, India and the small, likely more complex volumes from Mexico, the United States and Argentina import above the model. Connectors can't be calibrated on Comex Stat units, so their should-cost rests on the cost tree alone.

![Harness should-cost vs. import price by origin](reports/figures/should_cost_calibration.png)

**Supplier gaps.** Regular suppliers price a median 4.7% above should-cost. Three suppliers stand out on both tests used to flag overpricing, a gap above 10% and more than two robust standard deviations above the other suppliers: S019 (+21.6%), S032 (+18.5%) and S023 (+11.7%). Their quotes rank the same way. S042 (+10.6%) passes the materiality bar but not the outlier test, so it is a watch item, not a negotiation target. Bringing every material-supplier pair above 10% back to should-cost is worth about USD 0.83 M per year, 72% of it with the three flagged suppliers.

![Suppliers with the largest gap](reports/figures/supplier_gap.png)

**What moves the should-cost.** For a body harness made in Brazil, other material and copper are the largest drivers (±7–8% of should-cost for a ±20% change), followed by labour cost and labour minutes (±5.5%). Margin and SG&A move it ±2.8% for ±3 points. Negotiations should therefore start from the material bill and the copper index, not from margin.

![Should-cost tornado](reports/figures/cost_tornado.png)

**Copper clause.** Four price-adjustment designs, backtested on real copper from 2016 to 2026 for a body harness made in Brazil:

| Design | Budget drift in the year | Price changes in 10 years | Paid vs. monthly | Supplier margin: spread | Supplier margin: worst month |
|---|---|---|---|---|---|
| Fixed annual | 0.0% | 10 | −1.1% | 2.6 points | −0.5% |
| Monthly pass-through | 2.0% | 128 | 0.0% | 1.0 point | 4.3% |
| Quarterly, 3-month lag | 1.7% | 43 | −0.4% | 1.9 points | 2.1% |
| ±5% band | 1.9% | 33 | 0.0% | 1.2 points | 4.2% |

A fixed annual price gives the buyer a certain budget and the lowest total cost, but pushes all copper risk onto the supplier, whose yearly margin fell below 3% in 2021 and 2026 and went negative in December 2025. Monthly pass-through protects the supplier but moves the price every month. **Buyer's opening position: fixed annual. Supplier's: monthly pass-through. Recommended landing zone: quarterly adjustment on the previous quarter's average copper**, the design whose weaker side is least weak; the ±5% band is the alternative if the supplier insists on margin protection, at the cost of a little more budget drift. The same ranking holds for a harness made in China and for signal connectors.

![Copper clause backtest](reports/figures/clause_backtest.png)

Figures are regenerated from the database with `python -m src.figures`.

## Data

- **Synthetic purchasing base** for a fictional automaker: 60 suppliers, 300 materials, about 5,600 purchase order lines over 24 months and 300 RFQs with 3 quotes each, about USD 50 M of spend per year. Prices are built bottom-up from the real copper price (World Bank Pink Sheet, lagged 3 months), other material and labour priced in each supplier's country; three suppliers carry a hidden markup. Every assumption is listed in [docs/assumptions.md](docs/assumptions.md).
- Public sources and extraction dates are logged in [data/README.md](data/README.md).

## Method

1. **Spend baseline** ([notebooks/01_spend.ipynb](notebooks/01_spend.ipynb)): spend cube by family, supplier country and year; ABC Pareto (A while cumulative spend before the item is under 80%, B under 95%); single-source exposure; purchase price variance against the last price paid. The SQL lives in [sql/views.sql](sql/views.sql), and `python -m src.validate` checks the base before any analysis.
2. **Market intelligence** ([notebooks/02_market.ipynb](notebooks/02_market.ipynb)): Comex Stat implied import prices (USD/kg, and USD/unit for connectors), origin concentration (HHI) and the correlation of import prices with copper at lags of 0 to 6 months. Harness imports run at about USD 30/kg with Paraguay supplying close to half; month-to-month import prices barely follow copper, so the should-cost takes copper pass-through from its cost tree and calibrates on annual averages.
3. **Should-cost** ([notebooks/03_should_cost.ipynb](notebooks/03_should_cost.ipynb), [src/should_cost.py](src/should_cost.py)): cost tree per unit for every material and supplier, priced with the supplier country's labour cost, then landed in Brazil with freight and import duty (Mercosur origins duty-free). Calibrated against Comex Stat USD/kg by origin; premises are listed in [docs/assumptions.md](docs/assumptions.md).
4. **Gaps and sensitivity** ([notebooks/04_gap.ipynb](notebooks/04_gap.ipynb), [src/gap.py](src/gap.py)): each PO line and quote is compared with its should-cost at the same date (copper lagged 3 months). A supplier is flagged when its spend-weighted gap is above 10% and more than two robust standard deviations (MAD) above the median supplier. Savings potential counts the last 12 months of spend above should-cost for material-supplier pairs above 10%. The tornado moves one driver at a time.
5. **Copper clause backtest** ([notebooks/05_clause.ipynb](notebooks/05_clause.ipynb), [src/clause.py](src/clause.py)): the contract price is the should-cost at an index value of copper; four designs (fixed annual on December copper, monthly on the previous month, quarterly on the previous quarter's average, a ±5% band) are run on the Pink Sheet series from 2016. The supplier buys copper at spot, so its margin shows who carries the risk. Buyer metric: mean drift of the price from the January price; supplier metric: spread of its margin.

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
