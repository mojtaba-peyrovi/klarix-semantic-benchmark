SELECT session_key, COUNT(*) AS n
FROM `{{project}}.{{dataset_star}}.fct_sessions`
GROUP BY 1 HAVING COUNT(*) > 1;
