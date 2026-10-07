-- Grain: one row per order item.
-- Gross vs net revenue is handled by separate columns: net_sale_price/net_cost
-- are 0 for cancelled and returned items, so summing them gives net_revenue/cogs;
-- summing sale_price/cost for non-cancelled items gives gross_revenue.
select
    oi.order_item_id,
    oi.order_id,
    coalesce(dc.customer_key, -1) as customer_key,
    coalesce(dp.product_key, -1) as product_key,
    {{ date_key('oi.created_date') }} as created_date_key,
    {{ date_key('oi.shipped_date') }} as shipped_date_key,
    {{ date_key('oi.delivered_date') }} as delivered_date_key,
    {{ date_key('oi.returned_date') }} as returned_date_key,
    oi.status as item_status,
    oi.status = 'Cancelled' as is_cancelled,
    oi.status = 'Returned' as is_returned,
    oi.sale_price,
    dp.cost,
    case when oi.status in ('Cancelled', 'Returned') then 0.0 else oi.sale_price end as net_sale_price,
    case when oi.status in ('Cancelled', 'Returned') then 0.0 else dp.cost end as net_cost
from {{ ref('stg_order_items') }} oi
left join {{ ref('dim_customer') }} dc on dc.user_id = oi.user_id
left join {{ ref('dim_product') }} dp on dp.product_id = oi.product_id
