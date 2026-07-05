-- itc_summary_bigquery.sql
-- =========================
-- BigQuery SQL against the table bigquery_sync.py loads.
-- Run these in the BigQuery Sandbox console after syncing.
-- Replace `apac-01072016` with your actual GCP project ID if different.
--
-- QUERY 1: Overall ITC total — matches /itc-summary's total_claimable_itc
-- QUERY 2: By vendor — matches /itc-summary's by_vendor breakdown
-- QUERY 3: By HSN status — matches /itc-summary's by_hsn_status breakdown
-- QUERY 4: ITC trend by month — ONLY possible in BigQuery, not cheap in Postgres
-- QUERY 5: Vendor reliability score — cross-invoice consistency, BigQuery's strength

-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 1 — Overall ITC total (paste and run this one first to verify sync)
-- ─────────────────────────────────────────────────────────────────────────────
WITH computed AS (
  SELECT
    line_item_id,
    invoice_id,
    vendor_name,
    hsn_code,
    COALESCE(hsn_status, 'unknown') AS hsn_status,
    COALESCE(business_use_percent, 100) / 100.0 AS biz_pct,
    CASE
      WHEN line_tax_rate_percent IS NOT NULL
        THEN amount * line_tax_rate_percent / 100.0
      WHEN taxable_amount > 0
        THEN total_gst_amount * (amount / taxable_amount)
      ELSE 0
    END AS line_tax
  FROM `apac-01072016.invoice_intel.line_items_flat`
),
claimable AS (
  SELECT *, line_tax * biz_pct AS claimable
  FROM computed
)
SELECT
  ROUND(SUM(claimable), 2)  AS total_claimable_itc,
  COUNT(*)                  AS line_items_counted,
  COUNT(DISTINCT invoice_id) AS invoices_covered
FROM claimable;


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 2 — By vendor (uncomment to run)
-- ─────────────────────────────────────────────────────────────────────────────
/*
WITH computed AS (
  SELECT
    vendor_name,
    COALESCE(business_use_percent, 100) / 100.0 AS biz_pct,
    CASE
      WHEN line_tax_rate_percent IS NOT NULL
        THEN amount * line_tax_rate_percent / 100.0
      WHEN taxable_amount > 0
        THEN total_gst_amount * (amount / taxable_amount)
      ELSE 0
    END AS line_tax
  FROM `apac-01072016.invoice_intel.line_items_flat`
)
SELECT
  COALESCE(vendor_name, '(unknown vendor)') AS vendor_name,
  ROUND(SUM(line_tax * biz_pct), 2)         AS claimable_itc,
  COUNT(*)                                   AS line_item_count
FROM computed
GROUP BY vendor_name
ORDER BY claimable_itc DESC;
*/


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 3 — By HSN profile status (uncomment to run)
-- ─────────────────────────────────────────────────────────────────────────────
/*
WITH computed AS (
  SELECT
    COALESCE(hsn_status, 'unknown') AS hsn_status,
    COALESCE(business_use_percent, 100) / 100.0 AS biz_pct,
    CASE
      WHEN line_tax_rate_percent IS NOT NULL
        THEN amount * line_tax_rate_percent / 100.0
      WHEN taxable_amount > 0
        THEN total_gst_amount * (amount / taxable_amount)
      ELSE 0
    END AS line_tax
  FROM `apac-01072016.invoice_intel.line_items_flat`
)
SELECT
  hsn_status,
  ROUND(SUM(line_tax * biz_pct), 2) AS claimable_itc,
  COUNT(*)                           AS line_item_count
FROM computed
GROUP BY hsn_status
ORDER BY claimable_itc DESC;
*/


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 4 — ITC trend by month
-- This is the query that justifies BigQuery vs just using Postgres.
-- Scanning and aggregating across all invoices ordered by month is a
-- full-table columnar scan — exactly what BigQuery's storage format is
-- optimised for. The same query in Postgres degrades as invoice volume grows
-- because Postgres stores rows, not columns; BigQuery stores columns, so
-- pulling only invoice_date + amount + line_tax_rate_percent + total_gst_amount
-- touches far less data than the equivalent Postgres sequential scan.
-- ─────────────────────────────────────────────────────────────────────────────
/*
WITH computed AS (
  SELECT
    FORMAT_DATE('%Y-%m', invoice_date)          AS month,
    vendor_name,
    COALESCE(business_use_percent, 100) / 100.0 AS biz_pct,
    CASE
      WHEN line_tax_rate_percent IS NOT NULL
        THEN amount * line_tax_rate_percent / 100.0
      WHEN taxable_amount > 0
        THEN total_gst_amount * (amount / taxable_amount)
      ELSE 0
    END AS line_tax
  FROM `apac-01072016.invoice_intel.line_items_flat`
  WHERE invoice_date IS NOT NULL
)
SELECT
  month,
  ROUND(SUM(line_tax * biz_pct), 2)         AS claimable_itc,
  ROUND(SUM(line_tax), 2)                    AS gross_itc,
  COUNT(DISTINCT vendor_name)                AS unique_vendors,
  COUNT(*)                                   AS line_items
FROM computed
GROUP BY month
ORDER BY month ASC;
*/


-- ─────────────────────────────────────────────────────────────────────────────
-- QUERY 5 — Vendor reliability score
-- For each vendor: what % of their invoices have amount mismatches or
-- FAILED/WARNING status? High-risk vendors float to the top.
-- This kind of cross-invoice aggregate scan is the second reason BigQuery
-- earns its place: it gives you a vendor risk ranking that would require
-- a custom materialized view or slow sequential scan in Postgres.
-- ─────────────────────────────────────────────────────────────────────────────
/*
SELECT
  COALESCE(vendor_name, '(unknown)')                     AS vendor,
  COUNT(DISTINCT invoice_id)                             AS total_invoices,
  COUNTIF(status IN ('FAILED', 'WARNING'))               AS flagged_invoices,
  ROUND(
    100.0 * COUNTIF(status IN ('FAILED', 'WARNING'))
    / NULLIF(COUNT(DISTINCT invoice_id), 0),
  1)                                                     AS flag_rate_pct,
  ROUND(SUM(
    CASE
      WHEN line_tax_rate_percent IS NOT NULL
        THEN amount * line_tax_rate_percent / 100.0
      WHEN taxable_amount > 0
        THEN total_gst_amount * (amount / taxable_amount)
      ELSE 0
    END * COALESCE(business_use_percent, 100) / 100.0
  ), 2)                                                  AS total_claimable_itc
FROM `apac-01072016.invoice_intel.line_items_flat`
GROUP BY vendor_name
HAVING total_invoices >= 1
ORDER BY flag_rate_pct DESC, total_invoices DESC;
*/