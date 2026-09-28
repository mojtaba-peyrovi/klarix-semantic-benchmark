-- Grain: one row per order (including fully-cancelled orders, at gross_revenue = 0).
-- order_sequence_number and is_first_order only rank "real" orders (gross_revenue >
-- 0, matching the `orders` catalog metric); a fully-cancelled order gets NULL/FALSE
-- for both, since nothing was actually sold to sequence.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.fct_orders` AS
WITH items AS (
  SELECT
    order_id,
    COUNT(*) AS item_count,
    SUM(IF(status <> 'Cancelled', sale_price, 0)) AS gross_revenue,
    SUM(IF(status = 'Returned', sale_price, 0)) AS returned_revenue
  FROM `{{project}}.{{dataset_staging}}.stg_order_items`
  GROUP BY 1
),
orders AS (
  SELECT
    o.order_id,
    o.user_id,
    o.status,
    o.created_at,
    o.created_date,
    i.item_count,
    COALESCE(i.gross_revenue, 0) AS gross_revenue,
    COALESCE(i.gross_revenue, 0) - COALESCE(i.returned_revenue, 0) AS net_revenue
  FROM `{{project}}.{{dataset_staging}}.stg_orders` o
  LEFT JOIN items i ON i.order_id = o.order_id
),
sequenced AS (
  SELECT
    order_id,
    ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at) AS order_sequence_number
  FROM orders
  WHERE gross_revenue > 0
)
SELECT
  o.order_id,
  COALESCE(dc.customer_key, -1) AS customer_key,
  CASE WHEN o.created_date IS NULL THEN -1
       ELSE CAST(FORMAT_DATE('%Y%m%d', o.created_date) AS INT64) END AS order_date_key,
  o.status,
  o.item_count,
  o.gross_revenue,
  o.net_revenue,
  COALESCE(s.order_sequence_number = 1, FALSE) AS is_first_order,
  s.order_sequence_number
FROM orders o
LEFT JOIN `{{project}}.{{dataset_star}}.dim_customer` dc ON dc.user_id = o.user_id
LEFT JOIN sequenced s ON s.order_id = o.order_id;
