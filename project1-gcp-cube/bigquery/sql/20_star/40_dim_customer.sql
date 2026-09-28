-- Grain: one row per user, plus the -1 unknown member.
--
-- is_internal fixes P4 by design: it's rule-based, not a lookup of injected ids --
-- an email on the internal domain, OR a first name matching one of the known
-- test-account prefixes (Test/QA/Demo). Every governed measure should exclude
-- is_internal = TRUE by default (Cube, Milestone 7).
--
-- customer_cohort_month is the month of the customer's first-ever order with at
-- least one non-cancelled item (a fully cancelled order isn't a real purchase --
-- same "orders" definition as the metric catalog and truth.py).
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.dim_customer` AS
WITH first_orders AS (
  SELECT o.user_id, MIN(o.created_at) AS first_order_at
  FROM `{{project}}.{{dataset_staging}}.stg_orders` o
  WHERE EXISTS (
    SELECT 1 FROM `{{project}}.{{dataset_staging}}.stg_order_items` oi
    WHERE oi.order_id = o.order_id AND oi.status <> 'Cancelled'
  )
  GROUP BY 1
)
SELECT
  FARM_FINGERPRINT(CAST(u.user_id AS STRING)) AS customer_key,
  u.user_id,
  u.gender,
  u.age,
  CASE
    WHEN u.age < 25 THEN '18-24'
    WHEN u.age < 35 THEN '25-34'
    WHEN u.age < 45 THEN '35-44'
    WHEN u.age < 55 THEN '45-54'
    WHEN u.age < 65 THEN '55-64'
    ELSE '65+'
  END AS age_band,
  u.country,
  u.state,
  u.city,
  COALESCE(u.traffic_source, 'Unattributed') AS acquisition_channel,
  CAST(FORMAT_DATE('%Y%m%d', u.created_date) AS INT64) AS created_date_key,
  DATE_TRUNC(DATE(fo.first_order_at), MONTH) AS customer_cohort_month,
  u.email LIKE CONCAT('%@', '{{p4_email_domain}}')
    OR u.first_name IN ({{p4_name_prefixes_sql}}) AS is_internal
FROM `{{project}}.{{dataset_staging}}.stg_users` u
LEFT JOIN first_orders fo ON fo.user_id = u.user_id
UNION ALL
SELECT -1, -1, 'Unknown', CAST(NULL AS INT64), 'Unknown', 'Unknown', 'Unknown', 'Unknown',
  'Unattributed', -1, CAST(NULL AS DATE), FALSE;
