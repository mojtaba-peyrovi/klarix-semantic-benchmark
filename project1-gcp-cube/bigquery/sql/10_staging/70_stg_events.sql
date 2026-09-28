-- Grain: one row per event.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_events` AS
SELECT
  id AS event_id,
  user_id,
  session_id,
  sequence_number,
  event_type,
  traffic_source,
  created_at,
  DATE(created_at) AS created_date
FROM `{{project}}.{{dataset_raw}}.events`;
