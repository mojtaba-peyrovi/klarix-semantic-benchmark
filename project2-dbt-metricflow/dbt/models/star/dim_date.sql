-- Grain: one row per calendar day, covering every date any fact table could
-- reference (from the earliest activity in the data through the benchmark end
-- date), not just the 24-month analysis window -- a customer's order history goes
-- back further than the window, and every fact date must resolve to a real row
-- here or the -1 unknown member (see the relationships tests in _star.yml).
with bounds as (
    select min(d) as min_date
    from (
        select min(created_date) as d from {{ ref('stg_users') }}
        union all select min(created_date) from {{ ref('stg_orders') }}
        union all select min(created_date) from {{ ref('stg_events') }}
        union all select min(created_date) from {{ ref('stg_inventory_items') }}
    )
),

days as (
    select cast(d as date) as date
    from bounds, generate_series(bounds.min_date, cast('{{ var("window_end") }}' as date), interval 1 day) as t(d)
)

select
    cast(strftime(date, '%Y%m%d') as bigint) as date_key,
    date,
    cast(date_trunc('week', date) as date) as week_start,   -- DuckDB weeks start on Monday
    cast(date_trunc('month', date) as date) as month,
    cast(date_trunc('quarter', date) as date) as quarter,
    cast(extract(year from date) as bigint) as year,
    dayofweek(date) + 1 as day_of_week,                      -- 1 = Sunday ... 7 = Saturday, as in BigQuery
    (dayofweek(date) + 1) in (1, 7) as is_weekend
from days

union all

select
    -1,
    cast(null as date),
    cast(null as date),
    cast(null as date),
    cast(null as date),
    cast(null as bigint),
    cast(null as bigint),
    cast(null as boolean)
