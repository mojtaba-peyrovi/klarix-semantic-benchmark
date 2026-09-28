-- Grain: one row per customer. Supports P5 (return rate by cohort/channel) and
-- repeat-purchase questions. Includes every customer, internal or not -- exclusion
-- is dim_customer.is_internal's job (Cube, Milestone 7), not this mart's.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_marts}}.mart_customer_cohorts` AS
WITH order_dates AS (
  SELECT
    fo.customer_key,
    d.date AS order_date,
    fo.order_sequence_number
  FROM `{{project}}.{{dataset_star}}.fct_orders` fo
  JOIN `{{project}}.{{dataset_star}}.dim_date` d ON d.date_key = fo.order_date_key
  WHERE fo.order_sequence_number IS NOT NULL
),
first_and_second AS (
  SELECT
    customer_key,
    MIN(IF(order_sequence_number = 1, order_date, NULL)) AS first_order_date,
    MIN(IF(order_sequence_number = 2, order_date, NULL)) AS second_order_date
  FROM order_dates
  GROUP BY 1
),
item_stats AS (
  SELECT
    customer_key,
    SUM(IF(NOT is_cancelled, sale_price, 0)) AS lifetime_gross_revenue,
    SUM(net_sale_price) AS lifetime_net_revenue,
    COUNTIF(NOT is_cancelled) AS items_bought,
    COUNTIF(is_returned) AS items_returned
  FROM `{{project}}.{{dataset_star}}.fct_order_items`
  GROUP BY 1
)
SELECT
  dc.customer_key,
  dc.user_id,
  dc.customer_cohort_month,
  dc.acquisition_channel,
  dc.is_internal,
  fs.first_order_date,
  fs.second_order_date IS NOT NULL
    AND DATE_DIFF(fs.second_order_date, fs.first_order_date, DAY) <= 90 AS repeat_within_90d,
  COALESCE(i.lifetime_gross_revenue, 0) AS lifetime_gross_revenue,
  COALESCE(i.lifetime_net_revenue, 0) AS lifetime_net_revenue,
  SAFE_DIVIDE(i.items_returned, i.items_bought) AS return_rate
FROM `{{project}}.{{dataset_star}}.dim_customer` dc
LEFT JOIN first_and_second fs ON fs.customer_key = dc.customer_key
LEFT JOIN item_stats i ON i.customer_key = dc.customer_key
WHERE dc.customer_key <> -1;
