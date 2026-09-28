-- Grain: one row per product_id. No dates on this table.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_products` AS
SELECT
  id AS product_id,
  name,
  brand,
  category,
  department,
  cost,
  retail_price,
  sku,
  distribution_center_id
FROM `{{project}}.{{dataset_raw}}.products`;
