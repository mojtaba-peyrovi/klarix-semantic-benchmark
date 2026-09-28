-- Grain: one row per user. Typed, snake_case, no business logic -- see 20_star for
-- surrogate keys, cohort logic, and the is_internal rule.
CREATE OR REPLACE VIEW `{{project}}.{{dataset_staging}}.stg_users` AS
SELECT
  id AS user_id,
  first_name,
  last_name,
  email,
  age,
  gender,
  state,
  street_address,
  postal_code,
  city,
  country,
  latitude,
  longitude,
  traffic_source,
  created_at,
  DATE(created_at) AS created_date
FROM `{{project}}.{{dataset_raw}}.users`;
