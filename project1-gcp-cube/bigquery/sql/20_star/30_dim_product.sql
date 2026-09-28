-- Grain: one row per product_id, plus the -1 unknown member.
-- category_family fixes P2 by design: it survives the {{p2_old_category}} ->
-- {{p2_new_category}} rename because both names are mapped to one family in
-- map_category_family (00_map_category_family.sql), a governed table, not a formula.
CREATE OR REPLACE TABLE `{{project}}.{{dataset_star}}.dim_product` AS
SELECT
  FARM_FINGERPRINT(CAST(p.product_id AS STRING)) AS product_key,
  p.product_id,
  p.name,
  p.brand,
  p.category,
  m.category_family,
  p.department,
  p.retail_price,
  p.cost,
  dc.name AS distribution_center_name
FROM `{{project}}.{{dataset_staging}}.stg_products` p
LEFT JOIN `{{project}}.{{dataset_star}}.map_category_family` m ON m.category = p.category
LEFT JOIN `{{project}}.{{dataset_staging}}.stg_distribution_centers` dc
  ON dc.distribution_center_id = p.distribution_center_id
UNION ALL
SELECT -1, -1, 'Unknown', 'Unknown', 'Unknown', 'unknown', 'Unknown',
  CAST(NULL AS FLOAT64), CAST(NULL AS FLOAT64), 'Unknown';
