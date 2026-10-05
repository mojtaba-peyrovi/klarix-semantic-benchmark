"""Shared test fixtures.

`project1-gcp-cube/backend/` isn't an importable Python package (the parent
directory name has hyphens -- same reason `project1-gcp-cube/bigquery/` isn't; see
CLAUDE.md), so cube_backend.py is loaded here by file path instead of `import`.
"""

from __future__ import annotations

import importlib.util

import httpx
import pytest

from shared.settings import REPO_ROOT, load_settings

CUBE_BACKEND_PATH = REPO_ROOT / "project1-gcp-cube" / "backend" / "cube_backend.py"
CUBE_BASE_URL = "http://localhost:4000"


def load_cube_backend_module():
    spec = importlib.util.spec_from_file_location("cube_backend", CUBE_BACKEND_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
