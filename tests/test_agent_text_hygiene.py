"""Agent-facing text must not hint at the planted problems (Project 2 plan, 6.7).

The agent sees only the metric and dimension descriptions a backend returns from
list_metrics()/list_dimensions(). Those must never name a problem label (P1..P5) or a
planted-problem parameter (the renamed categories and their family, the P5 traffic
source, the consent and cohort dates, the internal email domain or name prefixes) --
that would hand the agent the answer to the trap questions.

Each backend contributes a "collector": a function returning (where, text) pairs of
everything the agent can read, built offline (no BigQuery, Cube or warehouse needed).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
import yaml

from shared.backends.naive_bigquery import NaiveBigQueryBackend
from shared.backends.naive_duckdb import NaiveDuckDbBackend
from shared.settings import REPO_ROOT, Settings, load_settings

CUBE_MODEL = REPO_ROOT / "project1-gcp-cube" / "cube" / "model"
METRICFLOW_YAML = (
    REPO_ROOT / "project2-dbt-metricflow" / "dbt" / "models" / "semantic" / "_semantic.yml"
)

Texts = list[tuple[str, str]]


def _date_forms(d: date) -> list[str]:
    return [d.isoformat(), d.strftime("%Y-%m")]


def forbidden_patterns(s: Settings) -> list[tuple[str, re.Pattern[str]]]:
    p = s.planted_problems
    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("problem label", re.compile(r"\bP[1-5]\b")),
    ]
    # Names and domains: case-insensitive. Short generic prefixes (Test/QA/Demo): whole
    # word, case-sensitive, so ordinary lowercase words never trip them.
    for label, value in [
        ("renamed category (old)", p.p2_category_rename.old_name),
        ("renamed category (new)", p.p2_category_rename.new_name),
        ("category family", p.p2_category_rename.family),
        ("P5 traffic source", p.p5_high_return_cohort.traffic_source),
        ("internal email domain", p.p4_internal_users.email_domain),
    ]:
        patterns.append((label, re.compile(re.escape(value), re.IGNORECASE)))
    for prefix in p.p4_internal_users.name_prefixes:
        patterns.append(("internal name prefix", re.compile(rf"\b{re.escape(prefix)}\b")))
    for label, d in [
        ("rename date", p.p2_category_rename.rename_date),
        ("consent date", p.p3_consent_loss.consent_date),
        ("P5 cohort start", p.p5_high_return_cohort.cohort_start),
        ("P5 cohort end", p.p5_high_return_cohort.cohort_end),
    ]:
        for form in _date_forms(d):
            patterns.append((label, re.compile(re.escape(form))))
    return patterns


# --- collectors: everything the agent can read, per backend ---------------------------


def naive_bigquery_texts() -> Texts:
    backend = NaiveBigQueryBackend(load_settings())  # lazy client: no credentials needed
    out: Texts = [(f"metric {m.name}", m.description) for m in backend.list_metrics()]
    out += [(f"dimension {d.name}", d.description) for d in backend.list_dimensions()]
    return out


def naive_duckdb_texts() -> Texts:
    backend = NaiveDuckDbBackend()  # lazy connection: no data needed
    out: Texts = [(f"metric {m.name}", m.description) for m in backend.list_metrics()]
    out += [(f"dimension {d.name}", d.description) for d in backend.list_dimensions()]
    return out


def cube_texts() -> Texts:
    """Descriptions of the members the `commerce` view exposes (public cubes' members are
    included by name; members marked `public: false` never reach the agent)."""
    descriptions: dict[str, tuple[str, bool]] = {}
    for path in sorted((CUBE_MODEL / "cubes").glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for cube in doc["cubes"]:
            for kind in ("measures", "dimensions"):
                for member in cube.get(kind, []):
                    descriptions[member["name"]] = (
                        member.get("description", ""),
                        member.get("public", True),
                    )
    view = yaml.safe_load((CUBE_MODEL / "views" / "commerce.yml").read_text(encoding="utf-8"))
    out: Texts = []
    for v in view["views"]:
        out.append((f"view {v['name']}", v.get("description", "")))
        for entry in v["cubes"]:
            for item in entry["includes"]:
                name = item["name"] if isinstance(item, dict) else item  # {name, alias} form
                assert name in descriptions, f"view includes unknown member {name!r}"
                text, public = descriptions[name]
                if public:
                    out.append((f"cube member {name}", text))
    return out


def metricflow_texts() -> Texts:
    """Descriptions of every non-hidden metric and every dimension except the internal
    is_internal filter column (the backend does not offer it). Model-level descriptions are
    human design notes, not agent-facing."""
    doc = yaml.safe_load((METRICFLOW_YAML).read_text(encoding="utf-8"))
    out: Texts = []
    for model in doc["models"]:
        for metric in model.get("metrics", []):
            if not metric.get("hidden"):
                out.append((f"metric {metric['name']}", metric["description"]))
        for column in model.get("columns", []):
            dimension = column.get("dimension")
            if isinstance(dimension, dict) and dimension.get("name") != "is_internal":
                out.append((f"dimension {dimension['name']}", dimension.get("description", "")))
    return out


COLLECTORS: dict[str, Callable[[], Texts]] = {
    "naive_bigquery": naive_bigquery_texts,
    "naive_duckdb": naive_duckdb_texts,
    "metricflow": metricflow_texts,
    "cube": pytest.param(  # type: ignore[dict-item]
        cube_texts,
        marks=pytest.mark.xfail(
            reason=(
                "Known Project 1 finding (frozen, not fixed): the Cube description of "
                "attribution_coverage_rate (project1-gcp-cube/cube/model/cubes/customers.yml) "
                "mentions 'P3 (consent-tracking loss)', and it reached the agent in the "
                "Project 1 runs."
            ),
            strict=True,
        ),
    ),
}


@pytest.mark.parametrize("collector", COLLECTORS.values(), ids=COLLECTORS.keys())
def test_agent_facing_text_has_no_planted_problem_hints(collector: Callable[[], Texts]):
    texts = collector()
    assert texts, "collector returned no agent-facing text; the test would pass vacuously"
    hits = [
        f"{where}: {label} {pattern.pattern!r}"
        for where, text in texts
        for label, pattern in forbidden_patterns(load_settings())
        if pattern.search(text)
    ]
    assert not hits, "agent-facing text hints at a planted problem:\n" + "\n".join(hits)


def test_forbidden_patterns_actually_match_what_they_should():
    """Guard against the test passing vacuously: each pattern must catch its own value."""
    s = load_settings()
    p = s.planted_problems
    samples = [
        "see P3 for details",
        f"renamed from {p.p2_category_rename.old_name} to {p.p2_category_rename.new_name}",
        f"family {p.p2_category_rename.family}",
        f"{p.p5_high_return_cohort.traffic_source} cohort",
        f"user@{p.p4_internal_users.email_domain}",
        f"names like {p.p4_internal_users.name_prefixes[0]} accounts",
        f"after {p.p3_consent_loss.consent_date.isoformat()}",
    ]
    patterns = forbidden_patterns(s)
    for sample in samples:
        assert any(pat.search(sample) for _, pat in patterns), sample
    assert not any(pat.search("Orders excluding internal accounts") for _, pat in patterns)


def test_collectors_import_cleanly():
    assert Path(CUBE_MODEL).exists()
