SELECT product_key, category, category_family
FROM `{{project}}.{{dataset_star}}.dim_product`
WHERE category_family IS NULL AND product_key <> -1;
