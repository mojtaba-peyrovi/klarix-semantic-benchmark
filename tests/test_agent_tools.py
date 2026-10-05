"""Tests for shared/agent/tools.py's execute_tool, in particular the
MAX_RESULT_ROWS safety net (found live: an uncapped run_semantic_query result
blew up token cost by re-sending ~8,774 rows on every later turn)."""

from __future__ import annotations

from shared.agent.tools import MAX_RESULT_ROWS, execute_tool
from shared.backends.base import Backend, DimensionInfo, MetricInfo
from shared.semantic.query import SemanticQuery, SemanticResult


class _BigResultBackend(Backend):
    name = "big"

    def list_metrics(self) -> list[MetricInfo]:
        return [MetricInfo(name="orders", description="d", unit="count")]

    def list_dimensions(self) -> list[DimensionInfo]:
        return [DimensionInfo(name="category", description="d", type="categorical")]

    def run(self, query: SemanticQuery) -> SemanticResult:
        rows = [[i] for i in range(MAX_RESULT_ROWS + 50)]
        return SemanticResult(
            columns=["orders"], rows=rows, compiled_query="SELECT ...", backend=self.name,
            latency_ms=1,
        )


class _SmallResultBackend(Backend):
    name = "small"

    def list_metrics(self) -> list[MetricInfo]:
        return [MetricInfo(name="orders", description="d", unit="count")]

    def list_dimensions(self) -> list[DimensionInfo]:
        return [DimensionInfo(name="category", description="d", type="categorical")]

    def run(self, query: SemanticQuery) -> SemanticResult:
        return SemanticResult(
            columns=["orders"], rows=[[1], [2]], compiled_query="SELECT ...", backend=self.name,
            latency_ms=1,
        )


def test_oversized_result_is_truncated_with_a_warning():
    result = execute_tool("run_semantic_query", {"metrics": ["orders"]}, _BigResultBackend())
    assert len(result["rows"]) == MAX_RESULT_ROWS
    assert any("truncated" in w for w in result["warnings"])


def test_small_result_is_untouched():
    result = execute_tool("run_semantic_query", {"metrics": ["orders"]}, _SmallResultBackend())
    assert result["rows"] == [[1], [2]]
    assert result["warnings"] == []


def test_invalid_query_returns_readable_error_not_a_crash():
    result = execute_tool("run_semantic_query", {}, _SmallResultBackend())
    assert "error" in result
