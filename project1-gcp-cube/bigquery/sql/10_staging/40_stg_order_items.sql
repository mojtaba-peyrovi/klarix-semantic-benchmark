-- Grain: one row per order item.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_order_items` AS
SELECT
  id AS order_item_id,
  order_id,
  user_id,
  product_id,
  inventory_item_id,
  status,
  sale_price,
  created_at,
  DATE(created_at) AS created_date,
  shipped_at,
  DATE(shipped_at) AS shipped_date,
  delivered_at,
  DATE(delivered_at) AS delivered_date,
  returned_at,
  DATE(returned_at) AS returned_date
FROM `{{project}}.{{dataset_raw}}.order_items`;
