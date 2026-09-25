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
