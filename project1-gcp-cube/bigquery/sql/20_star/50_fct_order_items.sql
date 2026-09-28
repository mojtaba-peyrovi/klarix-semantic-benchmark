-- Grain: one row per order item.
-- P1 (gross vs net revenue) is handled by separate columns: net_sale_price/net_cost
-- are 0 for cancelled and returned items, so summing them gives net_revenue/cogs;
-- summing sale_price/cost for non-cancelled items gives gross_revenue.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.fct_order_items` AS
SELECT
  oi.order_item_id,
  oi.order_id,
  COALESCE(dc.customer_key, -1) AS customer_key,
  COALESCE(dp.product_key, -1) AS product_key,
  CASE WHEN oi.created_date IS NULL THEN -1
       ELSE CAST(FORMAT_DATE('%Y%m%d', oi.created_date) AS INT64) END AS created_date_key,
  CASE WHEN oi.shipped_date IS NULL THEN -1
       ELSE CAST(FORMAT_DATE('%Y%m%d', oi.shipped_date) AS INT64) END AS shipped_date_key,
  CASE WHEN oi.delivered_date IS NULL THEN -1
       ELSE CAST(FORMAT_DATE('%Y%m%d', oi.delivered_date) AS INT64) END AS delivered_date_key,
  CASE WHEN oi.returned_date IS NULL THEN -1
       ELSE CAST(FORMAT_DATE('%Y%m%d', oi.returned_date) AS INT64) END AS returned_date_key,
  oi.status AS item_status,
  oi.status = 'Cancelled' AS is_cancelled,
  oi.status = 'Returned' AS is_returned,
  oi.sale_price,
  dp.cost,
  IF(oi.status IN ('Cancelled', 'Returned'), 0.0, oi.sale_price) AS net_sale_price,
  IF(oi.status IN ('Cancelled', 'Returned'), 0.0, dp.cost) AS net_cost
FROM `{{project}}.{{dataset_staging}}.stg_order_items` oi
LEFT JOIN `{{project}}.{{dataset_star}}.dim_customer` dc ON dc.user_id = oi.user_id
LEFT JOIN `{{project}}.{{dataset_star}}.dim_product` dp ON dp.product_id = oi.product_id;
