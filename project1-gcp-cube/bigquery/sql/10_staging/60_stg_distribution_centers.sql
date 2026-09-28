-- Grain: one row per distribution center.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_distribution_centers` AS
SELECT
  id AS distribution_center_id,
  name,
  latitude,
  longitude
FROM `{{project}}.{{dataset_raw}}.distribution_centers`;
