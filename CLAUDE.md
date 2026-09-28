# Klarix Semantic AI Benchmark

The full development plan is [docs/DEV_PLAN.md](docs/DEV_PLAN.md). Read it before working. Go
milestone by milestone and stop after each one for review.

**Portfolio intent:** the real goal is three separate, standalone consulting-portfolio case
studies, one per semantic-layer stack (see the table in DEV_PLAN.md section 1). The shared
benchmark (one dataset, one set of planted problems, one set of golden questions) exists only to
build all three fairly and cheaply; the cross-stack comparison report is a bonus, not the main
deliverable. **Build the stacks one at a time, fully, in order** (Project 1 through its own
Milestone 10 case-study README before starting Project 2's stack), rather than advancing all three
through the shared milestones in lockstep.

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
  - P4 uses **1000** internal users, not the plan's ~150 or even the user's first-confirmed 900 --
    900 measured at +1.9pts observed repeat-purchase-rate lift once implemented, just under the
    milestone's own 2pt test threshold. 1000 clears it with margin. Told to the user when raised.
  - P5's cohort (Facebook, 2025-05 to 2025-07, 80% return probability) clears its own test at
    cohort level (~40% vs ~12% baseline) but barely moves company-wide net margin. Q18/Q19 must be
    scoped to the cohort/segment, not the whole channel, when written in Milestone 8.
- **Milestone 3 design decisions** (DEV_PLAN section 6 leaves these implicit):
  - **"Clipped to window" only means capped at the end date.** Rows/timestamps after
    `benchmark.end_date` are dropped (`real_signal.py`); rows *before* `window_start` are **kept**
    in data/true and data/observed, because `new_customers`/cohort/first-order logic needs full
    order history to tell a first order from a repeat one -- a customer who first ordered in 2021
    and re-ordered in the window must not be counted as new. The 24-month window is applied as a
    filter when metrics are computed (`truth.py`, and later Cube/marts), not by deleting history.
  - **As-of-end-date rollback:** a lifecycle timestamp (shipped/delivered/returned_at) after the
    end date is nulled and the item's status stepped back one stage (Returned->Complete->
    Shipped->Processing), so the true world reflects what was actually known as of the cutoff.
  - **Injection order in `observe.py`: P4 runs before P2.** Internal users buy random products
    across all categories; if P2 (category rename) ran first, injected orders placed in the
    renamed category after the rename date would never get repointed, diluting P2's own test.
  - **P3 excludes P4's synthetic users.** The consent-loss mechanic only applies to real users;
    internal/test accounts aren't a real consent-tracking subject.
  - Reference the P1-P5 tests in `tests/test_world.py::test_p*` for the exact numbers each
    planted problem produces on the current seed.

## Status

- **Milestone 1** (scaffold + GCP): done. `gcp-check` passes except the quota row (see above).
- **Milestone 2** (snapshot + profile): done and confirmed by the user. `data/snapshot/*.parquet`,
  `manifest.json`, `PROFILE.md`, and the planted-problem parameters in `config/settings.yaml`.
- **Milestone 3** (true world, observed world, truth): done. `shared/world/{real_signal,observe,
  truth}.py`, `make world`, `data/{true,observed,truth}/*`, and `tests/test_world.py` (all 5
  planted-problem tests pass on the current seed).
- **Milestone 4** (semantic contract): done. `shared/semantic/catalog.yaml` (18 metrics, 14
  dimensions, from DEV_PLAN section 7), `query.py` (SemanticQuery/SemanticResult/Filter/TimeRange,
  section 8, structural validation via pydantic), `catalog.py` (loads the catalog, and
  `validate_query()` cross-checks a query's names against it, returning readable errors instead of
  raising -- backends call this before compiling anything, from Milestone 6 on).
  `tests/test_semantic.py` also checks `truth.py`'s metric columns haven't drifted from the
  catalog (it predates catalog.yaml by one milestone).
- **Next:** Milestone 5 (BigQuery modeling: `bigquery/load.py`, staging views, the star schema,
  marts, SQL tests) per DEV_PLAN.md section 9. This loads `data/observed/` into
  `apparel_ecom_raw`, currently still empty.
