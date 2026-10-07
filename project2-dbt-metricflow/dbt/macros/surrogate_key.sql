{#- Deterministic signed 64-bit surrogate key from a null-safe natural key.
    Replaces BigQuery's FARM_FINGERPRINT. md5_number_lower() is the low 64 bits of the MD5
    digest (an unsigned value); shifting by 2^63 maps it onto the signed BIGINT range.
    Deliberately NOT DuckDB's hash(), whose output may change between DuckDB versions.
    Several columns are joined with '|' (a NULL part becomes an empty string). -#}
{% macro surrogate_key(columns) -%}
  cast(
    cast(md5_number_lower(
      {%- for c in columns -%}
        coalesce(cast({{ c }} as varchar), '')
        {%- if not loop.last %} || '|' || {% endif -%}
      {%- endfor -%}
    ) as hugeint) - 9223372036854775808
  as bigint)
{%- endmacro %}
