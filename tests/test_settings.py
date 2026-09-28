import pytest

from shared import settings as settings_module
from shared.settings import load_settings


@pytest.fixture(autouse=True)
def _ignore_local_env_file(monkeypatch):
    monkeypatch.setattr(settings_module, "load_dotenv", lambda *_: None)


def test_settings_load_with_defaults(monkeypatch):
    monkeypatch.delenv("BQ_LOCATION", raising=False)
    monkeypatch.delenv("VERTEX_LOCATION", raising=False)
    s = load_settings()
    assert s.benchmark.window_months == 24
    assert s.gcp.bq_location == "EU"
    assert s.gcp.vertex_location == "eu"


def test_env_overrides_gcp(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("BQ_LOCATION", "europe-west3")
    s = load_settings()
    assert s.gcp.project_id == "my-project"
    assert s.gcp.bq_location == "europe-west3"


def test_every_configured_model_has_a_price():
    m = load_settings().models
    for model_id in (m.gemini, m.anthropic_agent, m.judge):
        assert model_id in m.prices, f"no token price for {model_id}"


def test_planted_problem_dates_fall_inside_the_window():
    s = load_settings()
    start = s.benchmark.end_date.replace(
        year=s.benchmark.end_date.year - s.benchmark.window_months // 12
    )
    p = s.planted_problems
    for d in (
        p.p2_category_rename.rename_date,
        p.p3_consent_loss.consent_date,
        p.p5_high_return_cohort.cohort_start,
        p.p5_high_return_cohort.cohort_end,
    ):
        assert start <= d <= s.benchmark.end_date
