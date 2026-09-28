SELECT product_key, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.dim_product`
GROUP BY 1 HAVING COUNT(*) > 1;
