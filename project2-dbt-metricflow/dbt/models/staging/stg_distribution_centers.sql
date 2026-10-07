-- Grain: one row per distribution center.
select
    id as distribution_center_id,
    name,
    latitude,
    longitude
from {{ source('observed', 'distribution_centers') }}
