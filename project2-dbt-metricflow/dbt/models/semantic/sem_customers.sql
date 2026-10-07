-- Semantic-layer input: dim_customer plus the signup date. customer_cohort_month is
-- left out on purpose: it has exactly one source in the semantic layer, sem_customer_cohorts.
select
    c.customer_key, c.user_id, c.gender, c.age, c.age_band, c.country, c.state, c.city,
    c.acquisition_channel, c.is_internal,
    d.date as user_created
from {{ ref('dim_customer') }} c
left join {{ ref('dim_date') }} d on d.date_key = c.created_date_key
