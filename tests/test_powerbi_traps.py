"""Offline checks on the Power BI traps suite's machinery (project3-powerbi-tmdl/traps.py): every
trap's edit applies to the committed model exactly once and leaves TMDL that still parses, the
DEFINE text comes from the edited copy, every claimed catcher is a real test, and the committed
model itself is never touched. The live part (wrong numbers, catchers failing) is `make p3-traps`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from shared.settings import REPO_ROOT

PROJECT = REPO_ROOT / "project3-powerbi-tmdl"
for _path in (PROJECT / "backend", PROJECT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import tmdl_check  # noqa: E402
import traps  # noqa: E402
from trap_plugin import with_define  # noqa: E402


@pytest.fixture
def copy(tmp_path):
    target = tmp_path / "definition"
    shutil.copytree(traps.MODEL_DIR, target)
    return target


@pytest.mark.parametrize("trap", [t for t in traps.TRAPS if t.mutate], ids=lambda t: t.id)
def test_each_edit_applies_once_and_the_edited_model_still_parses(trap, copy):
    before = {p.name: p.read_bytes() for p in copy.rglob("*.tmdl")}
    trap.mutate(copy)
    changed = [p.name for p in copy.rglob("*.tmdl") if p.read_bytes() != before[p.name]]
    assert changed  # T3c edits two files (the column and the model flag), the rest one
    assert tmdl_check.load_model(copy).tables  # still readable


def test_the_edits_change_what_they_claim_to_change(copy):
    traps.mutate_orders_without_base_measure(copy)
    orders = tmdl_check.load_model(copy).tables["Metrics"].measures["orders"].expression
    assert "[_orders]" not in orders and "fct_order_items[order_id]" in orders
    traps.mutate_summed_ratio(copy)
    assert traps.measure_define(copy, "return_rate").startswith(
        "  MEASURE Metrics[return_rate] = SUMX(VALUES('Order Date'[month])"
    )


def test_define_comes_from_the_edited_copy_not_the_committed_model(copy):
    traps.mutate_averaged_ratio(copy)
    assert "AVERAGEX" in traps.measure_define(copy, "return_rate")
    assert "AVERAGEX" not in traps.measure_define(traps.MODEL_DIR, "return_rate")


def test_with_define_touches_only_compiled_data_queries():
    data = "EVALUATE\nSUMMARIZECOLUMNS(\n)"
    assert (
        with_define("  MEASURE Metrics[x] = 1", data) == f"DEFINE\n  MEASURE Metrics[x] = 1\n{data}"
    )
    info = 'EVALUATE SELECTCOLUMNS(INFO.MEASURES(), "n", [Name])'
    assert with_define("  MEASURE Metrics[x] = 1", info) == info
    assert with_define("", data) == data


def test_every_claimed_catcher_is_a_real_test():
    nodes = sorted({n for t in traps.TRAPS for n in t.catchers})
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *nodes],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
    )  # fmt: skip
    collected = {line.strip() for line in done.stdout.splitlines() if "::" in line}
    assert set(nodes) <= collected, set(nodes) - collected


def test_the_committed_model_is_unchanged_by_importing_or_mutating(copy):
    before = {p.name: p.read_bytes() for p in traps.MODEL_DIR.rglob("*.tmdl")}
    for trap in traps.TRAPS:
        if trap.mutate:
            fresh = copy.parent / f"x_{trap.id}"
            shutil.copytree(traps.MODEL_DIR, fresh)
            trap.mutate(fresh)
    assert before == {p.name: p.read_bytes() for p in traps.MODEL_DIR.rglob("*.tmdl")}
