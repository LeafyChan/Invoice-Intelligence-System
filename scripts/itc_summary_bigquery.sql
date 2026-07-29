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