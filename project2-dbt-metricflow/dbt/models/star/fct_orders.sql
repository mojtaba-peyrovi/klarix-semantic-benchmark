-- Grain: one row per order (including fully-cancelled orders, at gross_revenue = 0).
-- order_sequence_number and is_first_order only rank "real" orders (gross_revenue >
-- 0, matching the `orders` catalog metric); a fully-cancelled order gets NULL/false
-- for both, since nothing was actually sold to sequence.
-- Port note: the ranking adds order_id as a tie-breaker (91 users have two orders at
-- the identical timestamp), so a rebuild always gives the same sequence. The BigQuery
-- version left ties to chance.
with items as (
    select
        order_id,
        count(*) as item_count,
        sum(case when status <> 'Cancelled' then sale_price else 0 end) as gross_revenue,
        sum(case when status = 'Returned' then sale_price else 0 end) as returned_revenue
    from {{ ref('stg_order_items') }}
    group by 1
),

orders as (
    select
        o.order_id,
        o.user_id,
        o.status,
        o.created_at,
        o.created_date,
        i.item_count,
        coalesce(i.gross_revenue, 0) as gross_revenue,
        coalesce(i.gross_revenue, 0) - coalesce(i.returned_revenue, 0) as net_revenue
    from {{ ref('stg_orders') }} o
    left join items i on i.order_id = o.order_id
),

sequenced as (
    select
        order_id,
        row_number() over (partition by user_id order by created_at, order_id) as order_sequence_number
    from orders
    where gross_revenue > 0
)

select
    o.order_id,
    coalesce(dc.customer_key, -1) as customer_key,
    {{ date_key('o.created_date') }} as order_date_key,
    o.status,
    o.item_count,
    o.gross_revenue,
    o.net_revenue,
    coalesce(s.order_sequence_number = 1, false) as is_first_order,
    s.order_sequence_number
from orders o
left join {{ ref('dim_customer') }} dc on dc.user_id = o.user_id
left join sequenced s on s.order_id = o.order_id
