-- Grain: one row per event.
select
    id as event_id,
    user_id,
    session_id,
    sequence_number,
    event_type,
    traffic_source,
    {{ utc_ts('created_at') }} as created_at,
    cast({{ utc_ts('created_at') }} as date) as created_date
from {{ source('observed', 'events') }}
