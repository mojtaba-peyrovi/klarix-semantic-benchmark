-- The map_category_family seed is the one hand-maintained copy of the renamed pair's
-- names. Returns a row (= fails) unless BOTH the old and the new category name from
-- config/settings.yaml are mapped to the configured family.
with expected as (
    select '{{ var("p2_old_category") }}' as category
    union all
    select '{{ var("p2_new_category") }}'
)
select e.category, m.category_family
from expected e
left join {{ ref('map_category_family') }} m on m.category = e.category
where m.category_family is distinct from '{{ var("p2_family") }}'
