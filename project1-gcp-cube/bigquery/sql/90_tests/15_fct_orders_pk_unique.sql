SELECT order_id, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.fct_orders`
GROUP BY 1 HAVING COUNT(*) > 1;
