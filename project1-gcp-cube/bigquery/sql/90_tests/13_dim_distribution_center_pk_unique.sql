SELECT distribution_center_key, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.dim_distribution_center`
GROUP BY 1 HAVING COUNT(*) > 1;
