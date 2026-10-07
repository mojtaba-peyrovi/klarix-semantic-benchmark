-- Grain: one row per customer. Supports return-rate-by-cohort/channel and
-- repeat-purchase questions. Includes every customer, internal or not -- exclusion
-- is dim_customer.is_internal's job (a metric filter in the MetricFlow layer), not
-- this mart's.
with order_dates as (
    select
        fo.customer_key,
        d.date as order_date,
        fo.order_sequence_number
    from {{ ref('fct_orders') }} fo
    join {{ ref('dim_date') }} d on d.date_key = fo.order_date_key
    where fo.order_sequence_number is not null
),

first_and_second as (
    select
        customer_key,
        min(case when order_sequence_number = 1 then order_date end) as first_order_date,
        min(case when order_sequence_number = 2 then order_date end) as second_order_date
    from order_dates
    group by 1
),

item_stats as (
    select
        customer_key,
        sum(case when not is_cancelled then sale_price else 0 end) as lifetime_gross_revenue,
        sum(net_sale_price) as lifetime_net_revenue,
        count(*) filter (where not is_cancelled) as items_bought,
        count(*) filter (where is_returned) as items_returned
    from {{ ref('fct_order_items') }}
    group by 1
)

select
    dc.customer_key,
    dc.user_id,
    dc.customer_cohort_month,
    dc.acquisition_channel,
    dc.is_internal,
    fs.first_order_date,
    (fs.second_order_date is not null
        and date_diff('day', fs.first_order_date, fs.second_order_date) <= 90) as repeat_within_90d,
    coalesce(i.lifetime_gross_revenue, 0) as lifetime_gross_revenue,
    coalesce(i.lifetime_net_revenue, 0) as lifetime_net_revenue,
    {{ safe_divide('i.items_returned', 'i.items_bought') }} as return_rate
from {{ ref('dim_customer') }} dc
left join first_and_second fs on fs.customer_key = dc.customer_key
left join item_stats i on i.customer_key = dc.customer_key
where dc.customer_key <> -1
