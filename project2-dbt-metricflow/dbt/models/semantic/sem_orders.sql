-- Semantic-layer input: fct_orders plus the order date (see sem_order_items).
select o.*, d.date as order_created
from {{ ref('fct_orders') }} o
left join {{ ref('dim_date') }} d on d.date_key = o.order_date_key
