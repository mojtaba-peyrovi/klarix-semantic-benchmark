{#- 20260131-style integer date key, or -1 (the unknown member) for a NULL date. -#}
{% macro date_key(date_expr) -%}
  coalesce(cast(strftime({{ date_expr }}, '%Y%m%d') as bigint), -1)
{%- endmacro %}

{#- A SQL list of string literals from a Python list var, quotes escaped. -#}
{% macro sql_string_list(values) -%}
  {%- for v in values -%}'{{ v | replace("'", "''") }}'{%- if not loop.last %}, {% endif -%}{%- endfor -%}
{%- endmacro %}

{#- Source timestamps are TIMESTAMPTZ (UTC). Cast to a naive UTC TIMESTAMP so every
    later DATE()/date_trunc is independent of the session time zone. -#}
{% macro utc_ts(column) -%}
  cast({{ column }} at time zone 'UTC' as timestamp)
{%- endmacro %}
