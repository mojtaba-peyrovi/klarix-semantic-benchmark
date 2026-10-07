-- Returns a row (= fails) unless dim_customer.is_internal flags exactly the number of
-- internal users the benchmark injected (planted_problems.p4_internal_users.count).
select internal_users, {{ var('p4_internal_count') }} as expected_users
from (select count(*) filter (where is_internal) as internal_users from {{ ref('dim_customer') }})
where internal_users <> {{ var('p4_internal_count') }}
