WITH totals AS (
  SELECT
    (SELECT SUM(IF(NOT is_cancelled, sale_price, 0))
     FROM `{{project}}.{{dataset_star}}.fct_order_items`) AS star_gross_revenue,
    (SELECT SUM(IF(status <> 'Cancelled', sale_price, 0))
     FROM `{{project}}.{{dataset_raw}}.order_items`) AS raw_gross_revenue
)
SELECT * FROM totals WHERE ABS(star_gross_revenue - raw_gross_revenue) > 0.01;
