"""The backend interface (DEV_PLAN section 11.1): anything the agent can run a
SemanticQuery against. `naive_bigquery` (this milestone) and `cube` (Milestone 7)
both implement this so the agent loop never needs to know which one it's talking to.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from shared.semantic.query import SemanticQuery, SemanticResult


class MetricInfo(BaseModel):
    name: str
    description: str
    unit: str
    available: bool = True
    unavailable_reason: str | None = None


class DimensionInfo(BaseModel):
    name: str
    description: str
    type: str
    grains: list[str] = []


class Backend(ABC):
    name: str

    @abstractmethod
    def list_metrics(self) -> list[MetricInfo]: ...

    @abstractmethod
    def list_dimensions(self) -> list[DimensionInfo]: ...

    @abstractmethod
    def run(self, query: SemanticQuery) -> SemanticResult: ...
