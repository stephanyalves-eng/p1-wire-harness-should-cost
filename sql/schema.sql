-- DuckDB schema for the purchasing base and the market data.
-- Grain and keys are documented in docs/BLUEPRINT.md, section 5.
-- The generator's hidden truth (which suppliers are overpriced) is kept out of the database
-- so the analysis cannot read it; it is saved next to the generator output instead.

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id    VARCHAR PRIMARY KEY,
    name           VARCHAR NOT NULL,
    country        VARCHAR NOT NULL,        -- plant country, ISO 3166-1 alpha-2: drives cost,
                                            -- freight and import duty
    lead_time_days INTEGER NOT NULL CHECK (lead_time_days > 0),
    ppm            DOUBLE  NOT NULL CHECK (ppm >= 0),  -- defective parts per million
    hq_country     VARCHAR                  -- headquarters of the supplier group, for context
);
-- Databases created before hq_country existed get the column on the next setup.
ALTER TABLE suppliers ADD COLUMN IF NOT EXISTS hq_country VARCHAR;

CREATE TABLE IF NOT EXISTS materials (
    material_id       VARCHAR PRIMARY KEY,
    description       VARCHAR NOT NULL,
    family            VARCHAR NOT NULL,     -- part family used for should-cost and calibration
    ncm               VARCHAR NOT NULL CHECK (ncm IN ('85443000', '85366910', '85366990')),
    unit_of_measure   VARCHAR NOT NULL,
    copper_g_per_unit DOUBLE  NOT NULL CHECK (copper_g_per_unit >= 0),
    single_source     BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id          VARCHAR NOT NULL,
    po_line        INTEGER NOT NULL,
    material_id    VARCHAR NOT NULL REFERENCES materials (material_id),
    supplier_id    VARCHAR NOT NULL REFERENCES suppliers (supplier_id),
    order_date     DATE    NOT NULL,
    delivery_date  DATE    NOT NULL,
    qty            INTEGER NOT NULL CHECK (qty > 0),
    unit_price_usd DOUBLE  NOT NULL CHECK (unit_price_usd > 0),
    PRIMARY KEY (po_id, po_line),
    CHECK (delivery_date >= order_date)
);

CREATE TABLE IF NOT EXISTS quotes (
    rfq_id         VARCHAR NOT NULL,
    material_id    VARCHAR NOT NULL REFERENCES materials (material_id),
    supplier_id    VARCHAR NOT NULL REFERENCES suppliers (supplier_id),
    quote_date     DATE    NOT NULL,
    unit_price_usd DOUBLE  NOT NULL CHECK (unit_price_usd > 0),
    PRIMARY KEY (rfq_id, supplier_id)
);

-- Comex Stat imports. Connectors are counted in units (qty_stat), harnesses in kg,
-- so both the weight and the statistical quantity are kept.
CREATE TABLE IF NOT EXISTS market_monthly (
    month    DATE    NOT NULL,              -- first day of the month
    ncm      VARCHAR NOT NULL,
    country  VARCHAR NOT NULL,
    usd_fob  DOUBLE  NOT NULL CHECK (usd_fob >= 0),
    kg_net   DOUBLE  NOT NULL CHECK (kg_net >= 0),
    qty_stat DOUBLE  NOT NULL CHECK (qty_stat >= 0),
    PRIMARY KEY (month, ncm, country)
);

-- World Bank Pink Sheet copper price.
CREATE TABLE IF NOT EXISTS copper_monthly (
    month        DATE   PRIMARY KEY,
    copper_usd_t DOUBLE NOT NULL CHECK (copper_usd_t > 0)
);

-- Banco Central do Brasil SGS exchange rate.
CREATE TABLE IF NOT EXISTS fx_daily (
    day     DATE   PRIMARY KEY,
    usd_brl DOUBLE NOT NULL CHECK (usd_brl > 0)
);
