SELECT f.order_item_id, f.product_key
FROM `{{project}}.{{dataset_star}}.fct_order_items` f
LEFT JOIN `{{project}}.{{dataset_star}}.dim_product` d ON d.product_key = f.product_key
WHERE d.product_key IS NULL;
