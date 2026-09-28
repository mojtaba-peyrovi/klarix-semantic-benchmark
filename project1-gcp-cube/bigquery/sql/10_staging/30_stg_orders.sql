-- Grain: one row per order.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_orders` AS
SELECT
  order_id,
  user_id,
  status,
  gender,
  num_of_item,
  created_at,
  DATE(created_at) AS created_date,
  shipped_at,
  DATE(shipped_at) AS shipped_date,
  delivered_at,
  DATE(delivered_at) AS delivered_date,
  returned_at,
  DATE(returned_at) AS returned_date
FROM `{{project}}.{{dataset_raw}}.orders`;
