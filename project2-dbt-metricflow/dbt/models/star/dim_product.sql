-- Grain: one row per product_id, plus the -1 unknown member.
-- category_family fixes the category rename by design: it survives the
-- {{ var('p2_old_category') }} -> {{ var('p2_new_category') }} rename because both
-- names are mapped to one family in the map_category_family seed, a governed table,
-- not a formula.
select
    {{ surrogate_key(['p.product_id']) }} as product_key,
    p.product_id,
    p.name,
    p.brand,
    p.category,
    m.category_family,
    p.department,
    p.retail_price,
    p.cost,
    dc.name as distribution_center_name
from {{ ref('stg_products') }} p
left join {{ ref('map_category_family') }} m on m.category = p.category
left join {{ ref('stg_distribution_centers') }} dc
    on dc.distribution_center_id = p.distribution_center_id

union all

select -1, -1, 'Unknown', 'Unknown', 'Unknown', 'unknown', 'Unknown',
    cast(null as double), cast(null as double), 'Unknown'
