-- Grain: one row per physical inventory item. Not used by the star schema's facts
-- directly; kept staged for completeness and for any future inventory-level question.
select
    id as inventory_item_id,
    product_id,
    cost,
    product_category,
    product_name,
    product_brand,
    product_retail_price,
    product_department,
    product_distribution_center_id,
    {{ utc_ts('created_at') }} as created_at,
    cast({{ utc_ts('created_at') }} as date) as created_date,
    {{ utc_ts('sold_at') }} as sold_at,
    cast({{ utc_ts('sold_at') }} as date) as sold_date
from {{ source('observed', 'inventory_items') }}
