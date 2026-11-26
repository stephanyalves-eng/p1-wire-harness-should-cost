-- Analytical views over the purchasing base. Recreated by src/db.py on every connection setup.

-- One row per PO line with its spend and the dimensions used everywhere else.
CREATE OR REPLACE VIEW v_po_lines AS
SELECT
    p.po_id,
    p.po_line,
    p.order_date,
    date_trunc('month', p.order_date)::DATE AS month,
    p.material_id,
    m.family,
    m.ncm,
    m.single_source,
    p.supplier_id,
    s.country,
    p.qty,
    p.unit_price_usd,
    p.qty * p.unit_price_usd AS spend_usd
FROM purchase_orders AS p
JOIN materials AS m USING (material_id)
JOIN suppliers AS s USING (supplier_id);

-- Spend cube: every combination of family, supplier country and year, with subtotals.
-- A NULL dimension means "all"; the row with all three NULL is the grand total.
CREATE OR REPLACE VIEW v_spend_cube AS
SELECT
    family,
    country,
    year(month) AS year,
    sum(spend_usd) AS spend_usd,
    count(*) AS po_lines
FROM v_po_lines
GROUP BY CUBE (family, country, year(month));

-- ABC classification of materials by spend. An item is A while the spend before it is
-- under 80% of the total, B under 95%, C otherwise, so the item crossing 80% is still A.
CREATE OR REPLACE VIEW v_abc AS
WITH by_material AS (
    SELECT material_id, family, sum(spend_usd) AS spend_usd
    FROM v_po_lines
    GROUP BY material_id, family
),
ranked AS (
    SELECT
        *,
        spend_usd / sum(spend_usd) OVER () AS spend_share,
        sum(spend_usd) OVER (ORDER BY spend_usd DESC, material_id
                             ROWS UNBOUNDED PRECEDING) / sum(spend_usd) OVER () AS cum_share,
        row_number() OVER (ORDER BY spend_usd DESC, material_id) AS rank
    FROM by_material
)
SELECT
    *,
    CASE
        WHEN cum_share - spend_share < 0.80 THEN 'A'
        WHEN cum_share - spend_share < 0.95 THEN 'B'
        ELSE 'C'
    END AS abc_class
FROM ranked;

-- Share of materials and of spend that depend on a single supplier.
CREATE OR REPLACE VIEW v_single_source AS
SELECT
    (SELECT avg(single_source::INTEGER) FROM materials) AS material_share,
    sum(spend_usd) FILTER (WHERE single_source) / sum(spend_usd) AS spend_share,
    sum(spend_usd) FILTER (WHERE single_source) AS single_source_spend_usd
FROM v_po_lines;

-- Purchase price variance against the last price paid for the same material, any supplier.
-- Positive PPV means the buyer paid more than last time.
CREATE OR REPLACE VIEW v_ppv AS
WITH ordered AS (
    SELECT
        *,
        lag(unit_price_usd) OVER (
            PARTITION BY material_id ORDER BY order_date, po_id, po_line
        ) AS last_price_usd
    FROM v_po_lines
)
SELECT
    po_id,
    po_line,
    order_date,
    month,
    material_id,
    family,
    supplier_id,
    qty,
    unit_price_usd,
    last_price_usd,
    (unit_price_usd - last_price_usd) * qty AS ppv_usd,
    unit_price_usd / last_price_usd - 1 AS ppv_pct
FROM ordered;

-- Implied import prices per month and NCM, pooling all origins: total FOB over total weight
-- and over the statistical quantity (units for connectors, kg for harnesses).
CREATE OR REPLACE VIEW v_market_implied AS
SELECT
    month,
    ncm,
    sum(usd_fob) AS usd_fob,
    sum(kg_net) AS kg_net,
    sum(qty_stat) AS qty_stat,
    sum(usd_fob) / nullif(sum(kg_net), 0) AS usd_per_kg,
    sum(usd_fob) / nullif(sum(qty_stat), 0) AS usd_per_unit
FROM market_monthly
GROUP BY month, ncm;

-- Share of each country of origin in the yearly import value of each NCM.
CREATE OR REPLACE VIEW v_market_origin_share AS
WITH by_country AS (
    SELECT ncm, year(month) AS year, country, sum(usd_fob) AS usd_fob
    FROM market_monthly
    GROUP BY ncm, year(month), country
)
SELECT
    *,
    usd_fob / sum(usd_fob) OVER (PARTITION BY ncm, year) AS share
FROM by_country
WHERE usd_fob > 0;

-- Herfindahl-Hirschman index of origin concentration, 0 to 10,000. Above 2,500 is
-- usually read as highly concentrated.
CREATE OR REPLACE VIEW v_market_hhi AS
SELECT
    ncm,
    year,
    sum(power(share * 100, 2)) AS hhi,
    count(*) AS origins,
    arg_max(country, share) AS top_country,
    max(share) AS top_share
FROM v_market_origin_share
GROUP BY ncm, year;
