-- Grain: one row per session_id.
-- "Unattributed" (session_traffic_source) makes the consent-tracking loss visible rather
-- than hiding it -- it's the same NULL-handling convention as acquisition_channel in
-- dim_customer.
-- Port note: ANY_VALUE becomes MIN. Every session in the data has exactly one user and
-- one traffic source, so the two are identical, and MIN is deterministic.
with sessions as (
    select
        session_id,
        min(user_id) as user_id,
        min(created_at) as session_start_ts,
        min(traffic_source) as traffic_source,
        count(*) as event_count,
        bool_or(event_type = 'purchase') as has_purchase
    from {{ ref('stg_events') }}
    group by 1
)

select
    {{ surrogate_key(['s.session_id']) }} as session_key,
    coalesce(dc.customer_key, -1) as customer_key,
    s.session_start_ts,
    {{ date_key('cast(s.session_start_ts as date)') }} as session_date_key,
    coalesce(s.traffic_source, 'Unattributed') as session_traffic_source,
    s.event_count,
    s.has_purchase
from sessions s
left join {{ ref('dim_customer') }} dc on dc.user_id = s.user_id
