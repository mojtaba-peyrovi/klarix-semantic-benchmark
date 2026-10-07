-- Grain: one row per order item.
select
    id as order_item_id,
    order_id,
    user_id,
    product_id,
    inventory_item_id,
    status,
    sale_price,
    {{ utc_ts('created_at') }} as created_at,
    cast({{ utc_ts('created_at') }} as date) as created_date,
    {{ utc_ts('shipped_at') }} as shipped_at,
    cast({{ utc_ts('shipped_at') }} as date) as shipped_date,
    {{ utc_ts('delivered_at') }} as delivered_at,
    cast({{ utc_ts('delivered_at') }} as date) as delivered_date,
    {{ utc_ts('returned_at') }} as returned_at,
    cast({{ utc_ts('returned_at') }} as date) as returned_date
from {{ source('observed', 'order_items') }}
