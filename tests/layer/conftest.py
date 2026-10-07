"""Backend-agnostic layer tests: every check runs once per backend (`cube`, `metricflow`)
with the same truth, the same tolerance and the same queries. A backend that isn't
reachable (Cube not up, DuckDB warehouse missing) is skipped, not failed.

Each check also records its relative deviation from truth; the terminal summary prints
the maximum per backend (DuckDB vs DuckDB should be near exact, and that is worth a line in
the case study).
"""

from __future__ import annotations

import json
from collections import defaultdict

import pytest

from shared.settings import REPO_ROOT

REL_TOL = 0.005  # 0.5% -- float rounding across engines' aggregation order

# backend name -> {check name -> relative deviation from truth}
DEVIATIONS: dict[str, dict[str, float]] = defaultdict(dict)


@pytest.fixture(scope="session", params=["cube", "metricflow"])
def backend(request):
    return request.getfixturevalue(f"{request.param}_backend")


@pytest.fixture
def check_close(backend):
    """check_close(name, got, want): assert within REL_TOL of truth and record the deviation."""

    def check(name: str, got: float, want: float) -> None:
        scale = max(abs(want), 1e-12)
        DEVIATIONS[backend.name][name] = abs(got - want) / scale
        assert got == pytest.approx(want, rel=REL_TOL)

    return check


LAYER_REPORT = REPO_ROOT / "runs" / "layer_correctness.json"


def write_layer_report() -> None:
    """Merge this session's per-backend results into runs/layer_correctness.json, which the
    failure analysis (shared/evals/failures.py) reads to spot `layer_wrong` causes. A metric is
    flagged when its deviation from truth exceeds the tolerance."""
    try:
        existing = json.loads(LAYER_REPORT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    for name, checks in DEVIATIONS.items():
        existing[name] = {
            "tolerance": REL_TOL,
            "deviations": dict(sorted(checks.items())),
            "flagged_metrics": sorted(c for c, d in checks.items() if d > REL_TOL),
        }
    LAYER_REPORT.parent.mkdir(exist_ok=True)
    LAYER_REPORT.write_text(json.dumps(existing, indent=1) + "\n", encoding="utf-8")


def pytest_terminal_summary(terminalreporter) -> None:
    if not DEVIATIONS:
        return
    write_layer_report()
    terminalreporter.section("layer correctness: maximum deviation from truth")
    for name, checks in sorted(DEVIATIONS.items()):
        worst = sorted(checks, key=checks.get, reverse=True)[:3]
        terminalreporter.write_line(f"{name}: {len(checks)} checks, tolerance {REL_TOL:.1e}")
        for check in worst:
            terminalreporter.write_line(f"    {checks[check]:.2e}  {check}")
