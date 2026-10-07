-- Semantic-layer input: mart_customer_cohorts, unchanged.
select * from {{ ref('mart_customer_cohorts') }}
