-- Grain: one row per session_id.
-- "Unattributed" (session_traffic_source) makes P3 visible rather than hiding it --
-- it's the same NULL-handling convention as acquisition_channel in dim_customer.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.fct_sessions` AS
WITH sessions AS (
  SELECT
    session_id,
    ANY_VALUE(user_id) AS user_id,
    MIN(created_at) AS session_start_ts,
    ANY_VALUE(traffic_source) AS traffic_source,
    COUNT(*) AS event_count,
    LOGICAL_OR(event_type = 'purchase') AS has_purchase
  FROM `{{project}}.{{dataset_staging}}.stg_events`
  GROUP BY 1
)
SELECT
  FARM_FINGERPRINT(s.session_id) AS session_key,
  COALESCE(dc.customer_key, -1) AS customer_key,
  s.session_start_ts,
  CAST(FORMAT_DATE('%Y%m%d', DATE(s.session_start_ts)) AS INT64) AS session_date_key,
  COALESCE(s.traffic_source, 'Unattributed') AS session_traffic_source,
  s.event_count,
  s.has_purchase
FROM sessions s
LEFT JOIN `{{project}}.{{dataset_star}}.dim_customer` dc ON dc.user_id = s.user_id;
