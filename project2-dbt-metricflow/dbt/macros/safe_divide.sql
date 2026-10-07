{#- BigQuery's SAFE_DIVIDE: NULL instead of an error when the denominator is 0. -#}
{% macro safe_divide(numerator, denominator) -%}
  ({{ numerator }}) / nullif({{ denominator }}, 0)
{%- endmacro %}
