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
- **Glossary:** all project terminology (P1-P5, Q01-Q20, worlds, backends, scorers, etc.) is
  defined in the README's Glossary section. Add any new term there when you introduce it, and
  don't use unexplained shorthand in replies.
- **Per-query guard:** every BigQuery job sets `maximum_bytes_billed` from `config/settings.yaml`.
- **Windows:** `make` may not be installed (`winget install ezwinports.make`). Every target is a
  thin `uv run ...` wrapper.
- **Daily query quota:** the 10 GiB project cap is not set (still the 200 TiB default). The user
  chose to ignore it for now; `gcp-check` reports it as FAIL. The per-query guard still applies.
- **Snapshot:** pulled 2026-09-28 07:54 UTC (upstream generation of 03:39 UTC), 325.5 MB scanned.
  GEOGRAPHY columns and unused `events` columns (ip, city, state, postal_code, browser, uri) are
  not in the snapshot. Never re-pull unless the user asks.
- **Benchmark window:** end date `2026-08-31`, window `2024-09-01` to `2026-08-31` (confirmed
  2026-09-28). See `config/settings.yaml` for the exact value.
- **Planted-problem parameters (P2-P5):** confirmed 2026-09-28, in `config/settings.yaml` under
  `planted_problems` (typed in `shared/settings.py`). Notable deviations from the plan's defaults:
  - P2 renames Sweaters -> Knitwear on 2025-10-01 (not the plan's Outerwear & Coats example).
  - P4 uses 900 internal users, not the plan's ~150 -- that count was too small to clear the
    milestone's own repeat-purchase-rate test.
  - P5's cohort (Facebook, 2025-05 to 2025-07, 80% return probability) clears its own test at
    cohort level but barely moves company-wide net margin. Q18/Q19 must be scoped to the
    cohort/segment, not the whole channel, when written in Milestone 8.

## Status

- **Milestone 1** (scaffold + GCP): done. `gcp-check` passes except the quota row (see above).
- **Milestone 2** (snapshot + profile): done and confirmed by the user. `data/snapshot/*.parquet`,
  `manifest.json`, `PROFILE.md`, and the planted-problem parameters in `config/settings.yaml`.
- **Next:** Milestone 3 (true world, observed world, truth) per DEV_PLAN.md section 6.
