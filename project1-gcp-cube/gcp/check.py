"""Verify the GCP setup from SETUP.md: auth, datasets, job rights, quota, and models.

Run with `make gcp-check`. Each check prints PASS / WARN / FAIL, and the script exits
non-zero on any FAIL. It only does free operations (metadata reads and dry runs)
plus one tiny Gemini call.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path

import google.auth
import httpx
from google.auth.transport.requests import Request
from google.cloud import bigquery
from rich.console import Console
from rich.table import Table

from shared.settings import REPO_ROOT, Settings, load_settings

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
Result = tuple[str, str]

DAILY_QUOTA_TARGET_MIB = 10 * 1024
QUOTA_METRIC = "bigquery.googleapis.com/quota/query/usage"
PUBLIC_ORDERS = "bigquery-public-data.thelook_ecommerce.orders"


def check_env(s: Settings) -> Result:
    if not s.gcp.project_id:
        return FAIL, "GCP_PROJECT_ID is not set in .env"
    return (
        PASS,
        f"project={s.gcp.project_id}  bq={s.gcp.bq_location}  vertex={s.gcp.vertex_location}",
    )


def check_adc(s: Settings) -> Result:
    _, adc_project = google.auth.default()
    if adc_project and adc_project != s.gcp.project_id:
        return (
            WARN,
            f"ADC quota project is {adc_project!r}; run set-quota-project (SETUP.md step 5)",
        )
    return PASS, "Application Default Credentials found"


def check_datasets(s: Settings) -> Result:
    client = bigquery.Client(project=s.gcp.project_id)
    problems = []
    for name in s.gcp.datasets.model_dump().values():
        try:
            ds = client.get_dataset(f"{s.gcp.project_id}.{name}")
        except Exception:
            problems.append(f"{name} missing")
            continue
        if ds.location.upper() != s.gcp.bq_location.upper():
            problems.append(f"{name} is in {ds.location}")
    if problems:
        return FAIL, "; ".join(problems) + " (SETUP.md step 4)"
    return PASS, f"all 4 datasets exist in {s.gcp.bq_location}"


def check_job_rights(s: Settings) -> Result:
    client = bigquery.Client(project=s.gcp.project_id, location=s.gcp.bq_location)
    client.query("SELECT 1", job_config=bigquery.QueryJobConfig(dry_run=True))
    return PASS, "can create query jobs (dry run)"


def check_public_dataset(s: Settings) -> Result:
    client = bigquery.Client(project=s.gcp.project_id)
    job = client.query(
        f"SELECT * FROM `{PUBLIC_ORDERS}`",
        job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
        location="US",
    )
    mb = job.total_bytes_processed / 1e6
    return PASS, f"theLook readable (full orders scan would be {mb:.1f} MB)"


def check_query_quota(s: Settings) -> Result:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    url = (
        f"https://serviceusage.googleapis.com/v1beta1/projects/{s.gcp.project_id}"
        "/services/bigquery.googleapis.com/consumerQuotaMetrics"
    )
    headers = {"Authorization": f"Bearer {creds.token}", "x-goog-user-project": s.gcp.project_id}
    params: dict[str, str] = {"view": "FULL"}
    while True:
        resp = httpx.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        for metric in body.get("metrics", []):
            if metric.get("metric") == QUOTA_METRIC:
                return _judge_quota(metric)
        if not body.get("nextPageToken"):
            return WARN, f"{QUOTA_METRIC} not found; verify the quota in the console"
        params["pageToken"] = body["nextPageToken"]


def _judge_quota(metric: dict) -> Result:
    for limit in metric.get("consumerQuotaLimits", []):
        if "/d/project" not in limit.get("unit", ""):
            continue
        effective = int(limit["quotaBuckets"][0].get("effectiveLimit", "-1"))
        unit = metric.get("unit", "")
        if effective < 0:
            return FAIL, "query usage per day is unlimited; set the 10 GiB cap (SETUP.md step 3)"
        if "MiBy" in unit and effective > DAILY_QUOTA_TARGET_MIB:
            return WARN, f"daily cap is {effective} MiB, above the 10 GiB target"
        return PASS, f"daily query cap = {effective} {unit}"
    return WARN, "no per-day project limit found; verify the quota in the console"


def check_gemini(s: Settings) -> Result:
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=s.gcp.project_id, location=s.gcp.vertex_location)
    resp = client.models.generate_content(
        model=s.models.gemini,
        contents="Reply with the single word OK.",
        config=types.GenerateContentConfig(temperature=0, max_output_tokens=64),
    )
    tokens = resp.usage_metadata.total_token_count if resp.usage_metadata else "?"
    model = resp.model_version or s.models.gemini
    return PASS, f"{model} answered at '{s.gcp.vertex_location}' ({tokens} tokens)"


def check_anthropic(s: Settings) -> Result:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return WARN, "ANTHROPIC_API_KEY not set (needed from Milestone 6)"
    import anthropic

    client = anthropic.Anthropic()
    ids = sorted({s.models.anthropic_agent, s.models.judge})
    for model_id in ids:
        client.models.retrieve(model_id)
    return PASS, f"key valid, models available: {', '.join(ids)}"


def check_cube_key(s: Settings) -> Result:
    raw = os.getenv("CUBE_SA_KEY_PATH")
    if not raw:
        return WARN, "CUBE_SA_KEY_PATH not set (needed from Milestone 7)"
    path = Path(raw).resolve()
    if not path.is_file():
        return FAIL, f"{path} does not exist"
    if path.is_relative_to(REPO_ROOT):
        return FAIL, "key file is inside the repo; move it out (SETUP.md step 6)"
    return PASS, f"key found outside the repo: {path}"


CHECKS: list[tuple[str, Callable[[Settings], Result]]] = [
    ("env", check_env),
    ("auth (ADC)", check_adc),
    ("datasets", check_datasets),
    ("BigQuery jobs", check_job_rights),
    ("public theLook", check_public_dataset),
    ("daily query quota", check_query_quota),
    ("Gemini on Vertex", check_gemini),
    ("Anthropic", check_anthropic),
    ("Cube SA key", check_cube_key),
]


def main() -> int:
    settings = load_settings()
    table = Table(title="GCP check")
    for col in ("check", "status", "detail"):
        table.add_column(col)
    colors = {PASS: "green", WARN: "yellow", FAIL: "red"}

    failed = False
    for name, check in CHECKS:
        if not settings.gcp.project_id and name != "env":
            status, detail = FAIL, "skipped: no project ID"
        else:
            try:
                status, detail = check(settings)
            except Exception as exc:  # report every failure, don't stop at the first
                status, detail = FAIL, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
        failed |= status == FAIL
        table.add_row(name, f"[{colors[status]}]{status}[/]", detail)

    Console().print(table)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
