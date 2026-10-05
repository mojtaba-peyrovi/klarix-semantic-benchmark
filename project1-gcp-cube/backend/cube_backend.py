"""The Cube backend (DEV_PLAN section 10.3): the governed stack's implementation of
`shared.backends.base.Backend`, talking to the local Cube Core container (Milestone
7's docker-compose.yml) over its REST API.

Auth is a short-lived HS256 JWT signed with CUBEJS_API_SECRET -- exercised even
though CUBEJS_DEV_MODE also accepts unauthenticated requests, since the point is to
demonstrate the real auth path a production Cube deployment would require.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from shared.backends.base import Backend, DimensionInfo, MetricInfo
from shared.semantic.catalog import load_catalog, validate_query
from shared.semantic.query import Filter, SemanticQuery, SemanticResult
from shared.settings import Settings

VIEW = "commerce"

# Metrics that live on the `orders` cube (order grain), not `order_items` (item
# grain). Both cubes have their own physical order_created dimension, but Cube can't
# join order_items and orders together in one query even through a shared dimension
# like customers (a confirmed limitation, not a modeling bug -- see commerce.yml's
# `orders_created` comment). When a query's metrics are entirely from this set, the
# catalog's "order_created" is routed to `orders_created` (orders.order_created's
# internal alias) instead of order_items' own order_created, so Cube never needs to
# combine the two cubes.
_ORDERS_GRAIN_METRICS = {"orders", "aov", "purchasing_customers", "new_customers"}

# SemanticQuery filter op -> Cube filter operator, for non-time dimensions.
_OP_TO_CUBE = {
    "eq": "equals",
    "neq": "notEquals",
    "in": "equals",
    "not_in": "notEquals",
    "gte": "gte",
    "lte": "lte",
}
# Same, when the filtered dimension is type: time (DEV_PLAN 10.3's mapping table).
_TIME_OP_TO_CUBE = {"gte": "afterOrOnDate", "lte": "beforeOrOnDate"}

_CONTINUE_WAIT_POLL_S = 2.0
_CONTINUE_WAIT_TIMEOUT_S = 120.0


class CubeBackend(Backend):
    name = "cube"

    def __init__(self, settings: Settings, base_url: str = "http://localhost:4000"):
        if not settings.cube_api_secret:
            raise ValueError("CUBEJS_API_SECRET is not set in .env")
        self.settings = settings
        self.catalog = load_catalog()
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)

    def _token(self) -> str:
        payload = {"exp": datetime.now(UTC) + timedelta(minutes=5)}
        return jwt.encode(payload, self.settings.cube_api_secret, algorithm="HS256")

    def _headers(self) -> dict[str, str]:
        # Cube accepts the raw JWT here (no "Bearer " prefix needed, though modern
        # versions tolerate it too) -- see product/auth/methods/jwt in Cube's docs.
        return {"Authorization": self._token(), "Content-Type": "application/json"}

    def _get_meta(self) -> dict[str, Any]:
        resp = self._client.get(f"{self.base_url}/cubejs-api/v1/meta", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def _view_meta(self) -> dict[str, Any]:
        meta = self._get_meta()
        for cube in meta["cubes"]:
            if cube["name"] == VIEW:
                return cube
        raise RuntimeError(f"view {VIEW!r} not found in Cube meta; is the model deployed?")

    def list_metrics(self) -> list[MetricInfo]:
        view = self._view_meta()
        by_name = {m["name"].removeprefix(f"{VIEW}.") for m in view["measures"]}
        out = []
        for name, m in self.catalog.metrics.items():
            available = name in by_name
            out.append(
                MetricInfo(
                    name=name,
                    description=m.description,
                    unit=m.unit,
                    available=available,
                    unavailable_reason=None if available else "not exposed by the commerce view",
                )
            )
        return out

    def list_dimensions(self) -> list[DimensionInfo]:
        view = self._view_meta()
        by_name = {d["name"].removeprefix(f"{VIEW}.") for d in view["dimensions"]}
        return [
            DimensionInfo(name=d.name, description=d.description, type=d.type, grains=d.grains)
            for d in self.catalog.dimensions.values()
            if d.name in by_name
        ]

    def run(self, query: SemanticQuery) -> SemanticResult:
        errors = validate_query(query, self.catalog)
        if errors:
            return SemanticResult(
                columns=[],
                rows=[],
                compiled_query="",
                backend=self.name,
                latency_ms=0,
                warnings=errors,
            )

        cube_query = self._to_cube_query(query)

        start = time.monotonic()
        data = self._request("load", cube_query)
        latency_ms = int((time.monotonic() - start) * 1000)

        sql_result = self._request("sql", cube_query)
        compiled_query = sql_result["sql"]["sql"][0]

        key_of = self._result_key_map(query)
        columns = list(key_of.values())
        rows = [[row.get(key) for key in key_of] for row in data["data"]]
        rows = [[self._coerce(v) for v in row] for row in rows]

        return SemanticResult(
            columns=columns,
            rows=rows,
            compiled_query=compiled_query,
            backend=self.name,
            latency_ms=latency_ms,
        )

    # -- SemanticQuery -> Cube JSON query --------------------------------------

    def _member(self, name: str) -> str:
        return f"{VIEW}.{name}"

    def _time_dimension_member(self, query: SemanticQuery) -> str | None:
        """The catalog's time_dimension name, routed to the physical Cube member it
        actually needs to resolve to (see _ORDERS_GRAIN_METRICS above)."""
        if query.time_dimension is None:
            return None
        if query.time_dimension == "order_created" and set(query.metrics) <= _ORDERS_GRAIN_METRICS:
            return "orders_created"
        return query.time_dimension

    def _to_cube_query(self, query: SemanticQuery) -> dict[str, Any]:
        cube_query: dict[str, Any] = {
            "measures": [self._member(m) for m in query.metrics],
            "dimensions": [self._member(d) for d in query.dimensions],
        }

        filters = []
        for f in query.filters:
            filters.append(self._to_cube_filter(f))
        if filters:
            cube_query["filters"] = filters

        time_member = self._time_dimension_member(query)
        if time_member:
            td: dict[str, Any] = {"dimension": self._member(time_member)}
            if query.time_grain:
                td["granularity"] = query.time_grain
            if query.time_range:
                tr = query.time_range
                td["dateRange"] = [tr.start.isoformat(), tr.end.isoformat()]
            cube_query["timeDimensions"] = [td]

        if query.order_by:
            cube_query["order"] = [
                [self._member(name), direction] for name, direction in query.order_by
            ]
        if query.limit:
            cube_query["limit"] = query.limit

        return cube_query

    def _to_cube_filter(self, f: Filter) -> dict[str, Any]:
        dim = self.catalog.dimensions[f.dimension]
        values = f.value if isinstance(f.value, list) else [f.value]
        if dim.type == "time" and f.op in _TIME_OP_TO_CUBE:
            return {
                "member": self._member(f.dimension),
                "operator": _TIME_OP_TO_CUBE[f.op],
                "values": [str(values[0])],
            }
        return {
            "member": self._member(f.dimension),
            "operator": _OP_TO_CUBE[f.op],
            "values": [str(v) for v in values],
        }

    def _result_key_map(self, query: SemanticQuery) -> dict[str, str]:
        """Cube response key -> catalog name, in the column order we report.

        A timeDimension with no granularity is a date-range filter only -- Cube
        doesn't select or group by it, so it gets no output column (see
        docs.cube.dev/reference/core-data-apis/rest-api/query-format).
        """
        key_of: dict[str, str] = {}
        time_member = self._time_dimension_member(query)
        if time_member and query.time_grain:
            cube_key = f"{self._member(time_member)}.{query.time_grain}"
            key_of[cube_key] = query.time_dimension
        for d in query.dimensions:
            key_of[self._member(d)] = d
        for m in query.metrics:
            key_of[self._member(m)] = m
        return key_of

    @staticmethod
    def _coerce(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            return value

    # -- HTTP + "Continue wait" -------------------------------------------------

    def _request(self, endpoint: str, cube_query: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/cubejs-api/v1/{endpoint}"
        deadline = time.monotonic() + _CONTINUE_WAIT_TIMEOUT_S
        while True:
            resp = self._client.post(url, headers=self._headers(), json={"query": cube_query})
            resp.raise_for_status()
            body = resp.json()
            if body.get("error") == "Continue wait":
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Cube {endpoint!r} did not complete within {_CONTINUE_WAIT_TIMEOUT_S}s"
                    )
                time.sleep(_CONTINUE_WAIT_POLL_S)
                continue
            if "error" in body:
                raise RuntimeError(f"Cube {endpoint!r} error: {body['error']}")
            return body
