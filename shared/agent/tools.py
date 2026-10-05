"""Tool specs and execution for the agent loop (DEV_PLAN section 11.3).

Specs are plain, provider-agnostic dicts (name/description/JSON Schema parameters);
each provider module adapts them to its own function-calling format. `execute_tool`
dispatches a non-terminal tool call by name against a Backend. `ask_clarification`
and `final_answer` are terminal -- the loop (loop.py) handles them itself, ending
the run, rather than routing them through here.
"""

from __future__ import annotations

from typing import Any

from shared.backends.base import Backend
from shared.semantic.query import SemanticQuery

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_metrics",
        "description": (
            "List every metric this backend can compute, with its description, unit, "
            "and whether it's currently available."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_dimensions",
        "description": "List every dimension this backend can group results by or filter on.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "run_semantic_query",
        "description": (
            "Run a semantic query and get numbers back. metrics and dimensions must be "
            "exact names from list_metrics/list_dimensions -- never write SQL or invent a name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "One or more metric names.",
                },
                "dimensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Dimension names to group by.",
                },
                "time_dimension": {"type": "string"},
                "time_grain": {
                    "type": "string",
                    "enum": ["day", "week", "month", "quarter", "year"],
                },
                "time_range": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "string", "description": "YYYY-MM-DD"},
                        "end": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                    },
                    "required": ["start", "end"],
                },
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dimension": {"type": "string"},
                            "op": {
                                "type": "string",
                                "enum": ["eq", "neq", "in", "not_in", "gte", "lte"],
                            },
                            "value": {
                                "description": "A string/number for eq/neq/gte/lte, "
                                "a list for in/not_in."
                            },
                        },
                        "required": ["dimension", "op", "value"],
                    },
                },
                "order_by": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "[name, 'asc'|'desc']",
                    },
                },
                "limit": {"type": "integer"},
            },
            "required": ["metrics"],
        },
    },
    {
        "name": "ask_clarification",
        "description": (
            "Terminal -- ends your turn. Call this instead of final_answer only when the "
            "question is genuinely ambiguous and you cannot make a reasonable, statable "
            "assumption and proceed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["question"],
        },
    },
    {
        "name": "final_answer",
        "description": "Terminal -- ends your turn. Give your final answer to the question.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "key_numbers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {"type": "number"},
                            "unit": {"type": "string"},
                        },
                        "required": ["label", "value", "unit"],
                    },
                },
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "caveats": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
            "required": ["answer", "key_numbers", "assumptions", "caveats", "confidence"],
        },
    },
]

TERMINAL_TOOLS = {"ask_clarification", "final_answer"}

# A safety net against an unbounded result, independent of any backend's own LIMIT
# handling: found live when an agent asked for daily grain by category over 12
# months with no `limit` -- naive_bigquery only applies a LIMIT when the query sets
# one, so this came back as 8,774 rows (one run_semantic_query call alone cost
# ~1.78M tokens once that result sat in conversation history for the rest of the
# run, since every later turn resends it). Every backend's SemanticResult is capped
# here rather than in each backend, so no current or future backend can repeat this.
MAX_RESULT_ROWS = 500


def execute_tool(name: str, arguments: dict[str, Any], backend: Backend) -> dict[str, Any]:
    """Run a non-terminal tool against a backend. Never raises for a bad LLM-supplied
    query -- returns a readable error the agent can see and self-correct from."""
    if name == "list_metrics":
        return {"metrics": [m.model_dump() for m in backend.list_metrics()]}
    if name == "list_dimensions":
        return {"dimensions": [d.model_dump() for d in backend.list_dimensions()]}
    if name == "run_semantic_query":
        try:
            query = SemanticQuery.model_validate(arguments)
        except Exception as exc:
            return {"error": f"invalid query: {exc}"}
        result = backend.run(query).model_dump(mode="json")
        if len(result["rows"]) > MAX_RESULT_ROWS:
            total = len(result["rows"])
            result["rows"] = result["rows"][:MAX_RESULT_ROWS]
            result["warnings"] = [
                *result.get("warnings", []),
                f"result had {total} rows; truncated to {MAX_RESULT_ROWS}. "
                "Use a coarser time_grain, add filters, or set a smaller limit.",
            ]
        return result
    raise ValueError(f"execute_tool called on a terminal or unknown tool: {name!r}")
