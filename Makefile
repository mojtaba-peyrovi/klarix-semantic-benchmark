.PHONY: setup gcp-check snapshot world bq-load bq-build bq-test cube-up cube-test eval compare test lint

BACKEND ?= cube
PROVIDER ?= gemini

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

cube-up:
	$(call todo,7)

cube-test:
	$(call todo,7)

eval:
	$(call todo,8)

compare:
	$(call todo,9)

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
