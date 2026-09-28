-- Every date role (created/shipped/delivered/returned) must resolve to a real
-- dim_date row or the -1 unknown member.
WITH keys AS (
  SELECT order_item_id, created_date_key AS date_key FROM `{{project}}.{{dataset_star}}.fct_order_items`
  UNION ALL SELECT order_item_id, shipped_date_key FROM `{{project}}.{{dataset_star}}.fct_order_items`
  UNION ALL SELECT order_item_id, delivered_date_key FROM `{{project}}.{{dataset_star}}.fct_order_items`
  UNION ALL SELECT order_item_id, returned_date_key FROM `{{project}}.{{dataset_star}}.fct_order_items`
)
SELECT k.order_item_id, k.date_key
FROM keys k
LEFT JOIN `{{project}}.{{dataset_star}}.dim_date` d ON d.date_key = k.date_key
WHERE d.date_key IS NULL;
