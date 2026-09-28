SELECT date_key, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.dim_date`
GROUP BY 1 HAVING COUNT(*) > 1;
