SELECT customer_key, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.dim_customer`
GROUP BY 1 HAVING COUNT(*) > 1;
