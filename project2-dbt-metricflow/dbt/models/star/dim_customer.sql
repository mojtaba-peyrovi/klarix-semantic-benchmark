-- Grain: one row per user, plus the -1 unknown member.
--
-- is_internal fixes the internal/test-account problem by design: it's rule-based, not a
-- lookup of injected ids -- an email on the internal domain, OR a first name matching
-- one of the known test-account prefixes. Every governed metric excludes
-- is_internal = true (a metric-level filter in the MetricFlow layer).
--
-- customer_cohort_month is the month of the customer's first-ever order with at
-- least one non-cancelled item (a fully cancelled order isn't a real purchase --
-- same "orders" definition as the metric catalog and truth.py).
with first_orders as (
    select o.user_id, min(o.created_at) as first_order_at
    from {{ ref('stg_orders') }} o
    where exists (
        select 1 from {{ ref('stg_order_items') }} oi
        where oi.order_id = o.order_id and oi.status <> 'Cancelled'
    )
    group by 1
)

select
    {{ surrogate_key(['u.user_id']) }} as customer_key,
    u.user_id,
    u.gender,
    u.age,
    case
        when u.age < 25 then '18-24'
        when u.age < 35 then '25-34'
        when u.age < 45 then '35-44'
        when u.age < 55 then '45-54'
        when u.age < 65 then '55-64'
        else '65+'
    end as age_band,
    u.country,
    u.state,
    u.city,
    coalesce(u.traffic_source, 'Unattributed') as acquisition_channel,
    {{ date_key('u.created_date') }} as created_date_key,
    cast(date_trunc('month', fo.first_order_at) as date) as customer_cohort_month,
    (u.email like '%@' || '{{ var("p4_email_domain") }}'
        or u.first_name in ({{ sql_string_list(var('p4_name_prefixes')) }})) as is_internal
from {{ ref('stg_users') }} u
left join first_orders fo on fo.user_id = u.user_id

union all

select -1, -1, 'Unknown', cast(null as bigint), 'Unknown', 'Unknown', 'Unknown', 'Unknown',
    'Unattributed', -1, cast(null as date), false
