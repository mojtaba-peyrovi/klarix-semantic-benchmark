-- Grain: one row per order.
select
    order_id,
    user_id,
    status,
    gender,
    num_of_item,
    {{ utc_ts('created_at') }} as created_at,
    cast({{ utc_ts('created_at') }} as date) as created_date,
    {{ utc_ts('shipped_at') }} as shipped_at,
    cast({{ utc_ts('shipped_at') }} as date) as shipped_date,
    {{ utc_ts('delivered_at') }} as delivered_at,
    cast({{ utc_ts('delivered_at') }} as date) as delivered_date,
    {{ utc_ts('returned_at') }} as returned_at,
    cast({{ utc_ts('returned_at') }} as date) as returned_date
from {{ source('observed', 'orders') }}
