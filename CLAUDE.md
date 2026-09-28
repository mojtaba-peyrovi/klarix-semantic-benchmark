# Klarix Semantic AI Benchmark

The full development plan is [docs/DEV_PLAN.md](docs/DEV_PLAN.md). Read it before working. Go
milestone by milestone and stop after each one for review.

## Decisions made so far (deviations from or additions to the plan)

- **GCP project:** display name "Klarix", ID `klarix-509711`. It's an umbrella project for several
  Klarix portfolio projects.
- **Naming:** this project's domain slug is `apparel_ecom` (theLook is a D2C apparel web store).
  - BigQuery datasets: `apparel_ecom_raw`, `apparel_ecom_staging`, `apparel_ecom_star`, `apparel_ecom_marts`
  - Cube service account: `apparel-ecom-cube`
- **Locations:** BigQuery `EU` multi-region. Vertex AI `eu` (the EU multi-region endpoint) rather
  than `europe-west4`, because `gemini-3.8-flash` isn't documented there.
- **Models (checked 2026-09-25):** Gemini `gemini-3.8-flash`. Claude `claude-opus-5` for both the
  judge and the control agent run. Current Claude models reject `temperature`/`top_p`, so
  "temperature 0" applies to Gemini only; Claude runs rely on fixed prompts and low effort.
- **Per-query guard:** every BigQuery job sets `maximum_bytes_billed` from `config/settings.yaml`.
- **Windows:** `make` may not be installed (`winget install ezwinports.make`). Every target is a
  thin `uv run ...` wrapper.

## Status

- **Milestone 1** (scaffold + GCP): code done. Waiting on the user to finish
  `project1-gcp-cube/gcp/SETUP.md`, fill in `.env`, and get `make gcp-check` passing (the Anthropic
  and Cube key checks may stay WARN).
- **Next:** Milestone 2 (snapshot + profile). It ends by proposing the benchmark end date and the
  P2-P5 parameters, and waits for confirmation.
