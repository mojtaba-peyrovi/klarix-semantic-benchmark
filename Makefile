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
	$(call todo,3)

bq-load:
	$(call todo,5)

bq-build:
	$(call todo,5)

bq-test:
	$(call todo,5)

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
