"""The `powerbi` backend is registered in the shared eval runner and fails readably when Power BI
Desktop is not open. No LLM is called: the runner builds the backend before any provider, and
this test stops there."""

from __future__ import annotations

import sys

import pytest
import yaml

from shared.evals import runner
from shared.settings import REPO_ROOT

for _path in (REPO_ROOT / "project3-powerbi-tmdl" / "backend", REPO_ROOT / "project3-powerbi-tmdl"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import desktop_connection  # noqa: E402


def test_runner_exits_with_one_readable_line_when_desktop_is_not_open(monkeypatch):
    monkeypatch.setattr(desktop_connection, "candidate_ports", lambda: [])

    def no_provider(*args, **kwargs):
        raise AssertionError("the provider must not be built when the backend cannot start")

    monkeypatch.setattr(runner, "build_provider", no_provider)
    with pytest.raises(SystemExit) as exc:
        runner.main(
            backend="powerbi", provider="anthropic", questions="Q01", repeats=1, max_tool_calls=8
        )
    message = str(exc.value)
    assert message.startswith("cannot start backend 'powerbi'")
    assert "Power BI Desktop is not open" in message


def test_project3_pins_are_all_null():
    pins = yaml.safe_load((REPO_ROOT / "config" / "runs.yaml").read_text(encoding="utf-8"))
    assert pins["project3"] and all(v is None for v in pins["project3"].values())
