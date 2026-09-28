"""The semantic query contract (DEV_PLAN section 8).

This is the only thing an agent is allowed to send to a backend: metrics and
dimensions by name, a time range, filters, sorting, a limit. **The LLM never writes
SQL** -- a backend (naive_bigquery, cube, ...) compiles a SemanticQuery into whatever
it needs to run.

Structural validity (a query well-formed on its own terms -- at least one metric, a
recognized filter operator) is enforced here, by pydantic. Whether the *names* used
actually exist in the metric catalog is a separate concern: see
`shared/semantic/catalog.py:validate_query`, which a backend calls before compiling
anything, so a bad name comes back as a readable error the agent can self-correct
from instead of a stack trace.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

TimeGrain = Literal["day", "week", "month", "quarter", "year"]
FilterOp = Literal["eq", "neq", "in", "not_in", "gte", "lte"]
SortDirection = Literal["asc", "desc"]

FilterValue = str | float | list[str] | list[float]
_LIST_OPS = {"in", "not_in"}
_SCALAR_OPS = {"eq", "neq", "gte", "lte"}


class Filter(BaseModel):
    dimension: str
    op: FilterOp
    value: FilterValue

    @model_validator(mode="after")
    def _value_matches_op(self) -> Filter:
        is_list = isinstance(self.value, list)
        if self.op in _LIST_OPS and not is_list:
            raise ValueError(f"op={self.op!r} needs a list value, got {type(self.value).__name__}")
        if self.op in _SCALAR_OPS and is_list:
            raise ValueError(f"op={self.op!r} needs a scalar value, got a list")
        return self


class TimeRange(BaseModel):
    start: date
    end: date  # inclusive

    @model_validator(mode="after")
    def _start_before_end(self) -> TimeRange:
        if self.start > self.end:
            raise ValueError(f"time_range.start ({self.start}) is after end ({self.end})")
        return self


class SemanticQuery(BaseModel):
    metrics: list[str] = Field(min_length=1)
    dimensions: list[str] = []
    time_dimension: str | None = None
    time_grain: TimeGrain | None = None
    time_range: TimeRange | None = None
    filters: list[Filter] = []
    order_by: list[tuple[str, SortDirection]] = []
    limit: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _grain_and_range_need_a_time_dimension(self) -> SemanticQuery:
        if self.time_dimension is None and (
            self.time_grain is not None or self.time_range is not None
        ):
            raise ValueError("time_grain/time_range were given without a time_dimension")
        return self


class SemanticResult(BaseModel):
    columns: list[str]
    rows: list[list]
    compiled_query: str  # SQL or Cube JSON, for transparency
    backend: str
    latency_ms: int
    warnings: list[str] = []
