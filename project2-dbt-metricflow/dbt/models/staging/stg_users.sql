-- Grain: one row per user. Typed, snake_case, no business logic.
select
    id as user_id,
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
    {{ utc_ts('created_at') }} as created_at,
    cast({{ utc_ts('created_at') }} as date) as created_date
from {{ source('observed', 'users') }}
