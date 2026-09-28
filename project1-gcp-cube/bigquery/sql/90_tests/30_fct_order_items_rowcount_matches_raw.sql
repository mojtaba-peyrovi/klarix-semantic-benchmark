WITH counts AS (
  SELECT
    (SELECT COUNT(*) FROM `{{project}}.{{dataset_star}}.fct_order_items`) AS star_rows,
    (SELECT COUNT(*) FROM `{{project}}.{{dataset_raw}}.order_items`) AS raw_rows
)
SELECT * FROM counts WHERE star_rows <> raw_rows;
