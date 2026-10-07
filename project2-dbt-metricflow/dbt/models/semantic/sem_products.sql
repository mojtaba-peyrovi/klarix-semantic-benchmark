-- Semantic-layer input: dim_product, unchanged.
select * from {{ ref('dim_product') }}
