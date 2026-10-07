-- Returns a row (= fails) for every real product whose category has no family in the seed.
select product_key, category, category_family
from {{ ref('dim_product') }}
where category_family is null and product_key <> -1
