-- Returns a row (= fails) if gross revenue in the fact differs from the observed source by > 0.01.
with totals as (
    select
        (select sum(case when not is_cancelled then sale_price else 0 end)
         from {{ ref('fct_order_items') }}) as star_gross_revenue,
        (select sum(case when status <> 'Cancelled' then sale_price else 0 end)
         from {{ source('observed', 'order_items') }}) as source_gross_revenue
)
select * from totals where abs(star_gross_revenue - source_gross_revenue) > 0.01
