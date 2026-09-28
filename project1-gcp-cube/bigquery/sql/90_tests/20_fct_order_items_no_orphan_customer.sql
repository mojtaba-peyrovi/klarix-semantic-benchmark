SELECT f.order_item_id, f.customer_key
FROM `{{project}}.{{dataset_star}}.fct_order_items` f
LEFT JOIN `{{project}}.{{dataset_star}}.dim_customer` d ON d.customer_key = f.customer_key
WHERE d.customer_key IS NULL;
