.PHONY: setup gcp-check snapshot world bq-load bq-build bq-test agent-smoke cube-up cube-test eval compare test lint

BACKEND ?= cube
PROVIDER ?= gemini
QUESTIONS ?= all
REPEATS ?= 1

todo = @echo "'$@' is not implemented yet (milestone $(1))." && exit 1

setup:
	uv sync

gcp-check:
	uv run python project1-gcp-cube/gcp/check.py

snapshot:
	uv run python -m shared.snapshot.pull
	uv run python -m shared.snapshot.profile

world:
	uv run python -m shared.world.real_signal
	uv run python -m shared.world.observe
	uv run python -m shared.world.truth

bq-load:
	uv run python project1-gcp-cube/bigquery/load.py

bq-build:
	uv run python project1-gcp-cube/bigquery/apply_sql.py

bq-test:
	uv run python project1-gcp-cube/bigquery/run_tests.py

agent-smoke:
	uv run python -m shared.agent.smoke_test

cube-up:
	uv run python project1-gcp-cube/cube/up.py

cube-test:
	uv run pytest tests/test_cube_contract.py tests/test_cube_layer_correctness.py

eval:
	uv run python -m shared.evals.runner --backend $(BACKEND) --provider $(PROVIDER) --questions $(QUESTIONS) --repeats $(REPEATS)

compare:
	uv run python -m shared.evals.compare

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
