-- Grain: one row per distribution center, plus the -1 unknown member.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.dim_distribution_center` AS
SELECT
  FARM_FINGERPRINT(CAST(distribution_center_id AS STRING)) AS distribution_center_key,
  distribution_center_id,
  name,
  latitude,
  longitude
FROM `{{project}}.{{dataset_staging}}.stg_distribution_centers`
UNION ALL
SELECT -1, -1, 'Unknown', CAST(NULL AS FLOAT64), CAST(NULL AS FLOAT64);
