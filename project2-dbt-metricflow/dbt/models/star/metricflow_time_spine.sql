-- Grain: one row per calendar day. MetricFlow requires a time spine model; it is derived
-- from dim_date so the date range has exactly one definition.
select date as date_day
from {{ ref('dim_date') }}
where date_key <> -1
