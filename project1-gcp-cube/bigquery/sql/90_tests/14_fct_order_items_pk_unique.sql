SELECT order_item_id, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.fct_order_items`
GROUP BY 1 HAVING COUNT(*) > 1;
