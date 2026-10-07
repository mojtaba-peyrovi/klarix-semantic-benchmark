-- Returns a row (= fails) if the fact has a different number of rows than the observed source.
with counts as (
    select
        (select count(*) from {{ ref('fct_order_items') }}) as star_rows,
        (select count(*) from {{ source('observed', 'order_items') }}) as source_rows
)
select * from counts where star_rows <> source_rows
