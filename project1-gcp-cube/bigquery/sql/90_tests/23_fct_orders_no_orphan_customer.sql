SELECT f.order_id, f.customer_key
FROM `{{project}}.{{dataset_star}}.fct_orders` f
LEFT JOIN `{{project}}.{{dataset_star}}.dim_customer` d ON d.customer_key = f.customer_key
WHERE d.customer_key IS NULL;
