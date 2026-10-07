-- Semantic-layer input: fct_sessions plus the session start as a date.
select s.*, cast(s.session_start_ts as date) as session_started
from {{ ref('fct_sessions') }} s
