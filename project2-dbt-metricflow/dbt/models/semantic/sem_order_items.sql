-- Semantic-layer input: fct_order_items plus the item's creation date. MetricFlow needs a
-- real time column inside the model, and the star schema keeps only date keys.
select oi.*, d.date as order_created
from {{ ref('fct_order_items') }} oi
left join {{ ref('dim_date') }} d on d.date_key = oi.created_date_key
