-- Grain: one row per physical inventory item. Not used by the star schema's facts
-- directly (see DEV_PLAN section 9.2), kept staged for completeness and for any
-- future inventory-level question.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_inventory_items` AS
SELECT
  id AS inventory_item_id,
  product_id,
  cost,
  product_category,
  product_name,
  product_brand,
  product_retail_price,
  product_department,
  product_distribution_center_id,
  created_at,
  DATE(created_at) AS created_date,
  sold_at,
  DATE(sold_at) AS sold_date
FROM `{{project}}.{{dataset_raw}}.inventory_items`;
