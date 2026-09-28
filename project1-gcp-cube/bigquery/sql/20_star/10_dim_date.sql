-- Grain: one row per calendar day, covering every date any fact table could
-- reference (from the earliest activity in the data through the benchmark end
-- date), not just the 24-month analysis window -- a customer's order history goes
-- back further than the window, and every fact date must resolve to a real row
-- here or the -1 unknown member (see the orphan-FK tests in 90_tests).
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.dim_date` AS
WITH bounds AS (
  SELECT MIN(d) AS min_date FROM (
    SELECT DATE(MIN(created_at)) AS d FROM `{{project}}.{{dataset_staging}}.stg_users`
    UNION ALL SELECT DATE(MIN(created_at)) FROM `{{project}}.{{dataset_staging}}.stg_orders`
    UNION ALL SELECT DATE(MIN(created_at)) FROM `{{project}}.{{dataset_staging}}.stg_events`
    UNION ALL SELECT DATE(MIN(created_at)) FROM `{{project}}.{{dataset_staging}}.stg_inventory_items`
  )
),
days AS (
  SELECT d AS date
  FROM bounds, UNNEST(GENERATE_DATE_ARRAY(bounds.min_date, DATE '{{window_end}}')) AS d
)
SELECT
  CAST(FORMAT_DATE('%Y%m%d', date) AS INT64) AS date_key,
  date,
  DATE_TRUNC(date, WEEK(MONDAY)) AS week_start,
  DATE_TRUNC(date, MONTH) AS month,
  DATE_TRUNC(date, QUARTER) AS quarter,
  EXTRACT(YEAR FROM date) AS year,
  EXTRACT(DAYOFWEEK FROM date) AS day_of_week,
  EXTRACT(DAYOFWEEK FROM date) IN (1, 7) AS is_weekend
FROM days
UNION ALL
SELECT
  -1,
  CAST(NULL AS DATE),
  CAST(NULL AS DATE),
  CAST(NULL AS DATE),
  CAST(NULL AS DATE),
  CAST(NULL AS INT64),
  CAST(NULL AS INT64),
  CAST(NULL AS BOOL);
