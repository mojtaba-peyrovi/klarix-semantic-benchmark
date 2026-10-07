-- Grain: one row per product_id. No dates on this table.
select
    id as product_id,
    name,
    brand,
    category,
    department,
    cost,
    retail_price,
    sku,
    distribution_center_id
from {{ source('observed', 'products') }}
