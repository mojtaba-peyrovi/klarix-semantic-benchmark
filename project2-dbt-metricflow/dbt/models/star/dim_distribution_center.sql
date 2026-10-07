-- Grain: one row per distribution center, plus the -1 unknown member.
select
    {{ surrogate_key(['distribution_center_id']) }} as distribution_center_key,
    distribution_center_id,
    name,
    latitude,
    longitude
from {{ ref('stg_distribution_centers') }}

union all

select -1, -1, 'Unknown', cast(null as double), cast(null as double)
