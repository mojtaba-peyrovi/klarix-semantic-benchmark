"""Typed access to config/settings.yaml plus the environment (.env).

Non-secret, versioned choices live in settings.yaml. Anything machine- or
account-specific (project ID, locations, keys) comes from the environment.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = REPO_ROOT / "config" / "settings.yaml"


class Datasets(BaseModel):
    raw: str
    staging: str
    star: str
    marts: str


class GcpSettings(BaseModel):
    project_id: str | None
    bq_location: str
    vertex_location: str
    datasets: Datasets
    max_bytes_billed_per_query: int


class Price(BaseModel):
    input: float  # USD per 1M input tokens
    output: float  # USD per 1M output tokens


class ModelSettings(BaseModel):
    gemini: str
    anthropic_agent: str
    judge: str
    prices: dict[str, Price]


class BenchmarkSettings(BaseModel):
    end_date: date | None
    window_months: int


class CategoryRename(BaseModel):
    """P2: a mid-sized category renamed partway through the window (DEV_PLAN 6.2)."""

    old_name: str
    new_name: str
    rename_date: date
    family: str


class ConsentLoss(BaseModel):
    """P3: users and sessions created on/after consent_date lose their traffic_source."""

    consent_date: date
    affected_share: float


class InternalUsers(BaseModel):
    """P4: injected internal/test accounts, excluded from every governed metric."""

    count: int
    country: str
    email_domain: str
    name_prefixes: list[str]
    orders_per_user: tuple[int, int]
    items_per_order: tuple[int, int]
    sale_price_range: tuple[float, float]
    repeat_within_days: int


class HighReturnCohort(BaseModel):
    """P5: a real signal applied to the true world (not a data artifact)."""

    traffic_source: str
    cohort_start: date
    cohort_end: date
    return_probability: float
    return_lag_days: tuple[int, int]


class PlantedProblems(BaseModel):
    p2_category_rename: CategoryRename
    p3_consent_loss: ConsentLoss
    p4_internal_users: InternalUsers
    p5_high_return_cohort: HighReturnCohort


class Settings(BaseModel):
    seed: int
    benchmark: BenchmarkSettings
    gcp: GcpSettings
    models: ModelSettings
    planted_problems: PlantedProblems


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["gcp"] |= {
        "project_id": os.getenv("GCP_PROJECT_ID") or None,
        "bq_location": os.getenv("BQ_LOCATION", "EU"),
        "vertex_location": os.getenv("VERTEX_LOCATION", "eu"),
    }
    return Settings.model_validate(raw)
