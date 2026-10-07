-- NULL checks live in _star.yml (not_null). This returns a row (= fails) if the
-- "Unattributed" bucket is missing from either column: the lost-source users/sessions
-- must be visible as their own bucket, not silently dropped or merged.
select 'dim_customer.acquisition_channel' as column_name
where not exists (select 1 from {{ ref('dim_customer') }} where acquisition_channel = 'Unattributed' and customer_key <> -1)
union all
select 'fct_sessions.session_traffic_source'
where not exists (select 1 from {{ ref('fct_sessions') }} where session_traffic_source = 'Unattributed')
