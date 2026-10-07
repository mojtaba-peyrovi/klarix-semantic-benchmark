"""Shared test fixtures.

`project1-gcp-cube/backend/` and `project2-dbt-metricflow/backend/` aren't importable
Python packages (the parent directory names have hyphens -- same reason
`project1-gcp-cube/bigquery/` isn't; see CLAUDE.md), so each backend module is loaded
here by file path instead of `import`.
"""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

import httpx
import pytest

from shared.settings import REPO_ROOT, load_settings

CUBE_BACKEND_PATH = REPO_ROOT / "project1-gcp-cube" / "backend" / "cube_backend.py"
METRICFLOW_BACKEND_PATH = (
    REPO_ROOT / "project2-dbt-metricflow" / "backend" / "metricflow_backend.py"
)
CUBE_BASE_URL = "http://localhost:4000"


def load_backend_module(name: str, path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses (with `from __future__ import annotations`) look it up
    spec.loader.exec_module(module)
    return module


def load_cube_backend_module() -> ModuleType:
    return load_backend_module("cube_backend", CUBE_BACKEND_PATH)


@pytest.fixture(scope="session")
def cube_backend():
    """A live CubeBackend, or a skip if `make cube-up` hasn't been run."""
    module = load_cube_backend_module()
    settings = load_settings()
    if not settings.gcp.project_id or not settings.cube_api_secret:
        pytest.skip("GCP_PROJECT_ID / CUBEJS_API_SECRET not set in .env")
    try:
        httpx.get(f"{CUBE_BASE_URL}/readyz", timeout=2).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("Cube is not reachable at localhost:4000; run `make cube-up` first")
    return module.CubeBackend(settings, base_url=CUBE_BASE_URL)


@pytest.fixture(scope="session")
def metricflow_module() -> ModuleType:
    return load_backend_module("metricflow_backend", METRICFLOW_BACKEND_PATH)


@pytest.fixture(scope="session")
def metricflow_backend(metricflow_module):
    """A MetricFlowBackend, or a skip if the warehouse or semantic manifest is missing
    (`make p2-build`) or the warehouse is locked by a running dbt."""
    if not metricflow_module.MANIFEST_PATH.exists():
        pytest.skip("semantic manifest is missing; run `make p2-build` first")
    try:
        return metricflow_module.MetricFlowBackend(load_settings())
    except RuntimeError as e:
        pytest.skip(str(e))
