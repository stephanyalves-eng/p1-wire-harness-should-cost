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

| NCM | Official description (Comex Stat) | Statistical unit |
|---|---|---|
| 8544.30.00 | Jogos de fios para velas de ignição e outros jogos de fios dos tipos utilizados em quaisquer veículos | kg (net) |
| 8536.69.10 | Tomada polarizada e tomada blindada, para uma tensão não superior a 1.000 V | units |
| 8536.69.90 | Outras tomadas de corrente, para uma tensão não superior a 1.000 V | units |

Connectors are counted in units, not kilograms, so the market analysis reports USD/kg for harnesses and both USD/kg (from net weight) and USD/unit for connectors.

Import duty (II) for each code: **to be confirmed in the TEC in force** (Resolução Gecex nº 272 and amendments), including the exception lists.

## Result

## Data

## Method

## Limitations

## How to run

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
nbstripout --install            # once per clone: strips notebook outputs on commit
```

Before committing:

```bash
ruff check .
ruff format .
pytest
```

## How AI was used
