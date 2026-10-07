.PHONY: p2-setup p2-build p2-test p2-docs p2-mf-validate p2-layer-test p2-smoke p2-parity p2-naive-parity setup gcp-check snapshot world bq-load bq-build bq-test agent-smoke cube-up cube-test eval compare compare-cross failures test lint

BACKEND ?= cube
PROVIDER ?= gemini
QUESTIONS ?= all
REPEATS ?= 1
MAX_TOOL_CALLS ?= 8
PROJECT ?= 1

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
	uv run pytest tests/layer -k cube

eval:
	uv run python -m shared.evals.runner --backend $(BACKEND) --provider $(PROVIDER) --questions $(QUESTIONS) --repeats $(REPEATS) --max-tool-calls $(MAX_TOOL_CALLS)

compare:
	uv run python -m shared.evals.compare --project $(PROJECT)

compare-cross:
	uv run python -m shared.evals.compare --cross-stack

failures:
	uv run python -m shared.evals.failures $(RUN)

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

# --- Project 2: dbt Core + MetricFlow on DuckDB ---
p2-setup:
	uv sync --group project2

p2-build:
	uv run python project2-dbt-metricflow/run_dbt.py --fresh build

p2-test:
	uv run python project2-dbt-metricflow/run_dbt.py test

p2-docs:
	uv run python project2-dbt-metricflow/run_dbt.py docs generate

p2-mf-validate:
	uv run python project2-dbt-metricflow/run_mf.py validate-configs

p2-layer-test:
	uv run pytest tests/layer tests/test_metricflow_contract.py tests/test_metricflow_backend.py -k "not cube"

p2-parity:
	uv run python project2-dbt-metricflow/parity/compare_star.py

p2-smoke:
	uv run python project2-dbt-metricflow/smoke_test.py

p2-naive-parity:
	uv run python project2-dbt-metricflow/parity/compare_naive.py
