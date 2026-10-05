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
- **Windows + LLM output text:** a redirected/non-interactive stdout defaults to cp1252, not
  UTF-8, and LLM answer text routinely contains characters (arrows, em dashes, curly quotes)
  cp1252 can't encode -- the process crashes with `UnicodeEncodeError` right when it tries to
  print, which can look like a silent hang if the crash comes after a long run (found this in
  `shared/agent/smoke_test.py`). Any script that prints LLM-generated text (the Milestone 8 eval
  runner will do this constantly) should open with
  `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` before printing anything.
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
- **Catalog synonyms: deferred, not forgotten.** `catalog.yaml` could carry a `synonyms:` list per
  metric/dimension (e.g. `aov` / "average order value"), but don't add any yet. Some ambiguous
  terms ("revenue") are ambiguous *on purpose* -- Q06-Q09 (P1) test whether the agent notices the
  gross/net split and asks or states its assumption; pre-resolving that with a synonym would
  quietly defeat the test. Revisit this in **Milestone 9** (the real Gemini/Claude eval runs), and
  only add a synonym if a run shows the agent genuinely failing to find an *unambiguous* metric by
  a plausible alternate name -- not to smooth over a deliberate trap.

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
- **Milestone 5** (BigQuery modeling): done. `project1-gcp-cube/bigquery/{load,apply_sql,
  run_tests,render}.py` + `sql/{10_staging,20_star,30_marts,90_tests}/*.sql`. `make bq-load`
  loaded `data/observed/` into `apparel_ecom_raw`; `make bq-build` ran staging -> star -> marts;
  `make bq-test` passes all 16 assertions (PK uniqueness, no orphan FKs, row-count and
  gross-revenue reconciliation to raw, every category has a family). Verified live against
  BigQuery, not just structurally: `is_internal` flags exactly the 1000 injected P4 users,
  `Sweaters`/`Knitwear` both map to one `category_family`, `acquisition_channel`/
  `session_traffic_source` show "Unattributed" for exactly the P3-affected counts.
  - `project1-gcp-cube/bigquery/` isn't a Python package (the directory name has a hyphen); its
    scripts import each other as script-directory siblings (`from render import ...`), not via
    `shared`. Run them as files (`uv run python project1-gcp-cube/bigquery/load.py`), never `-m`.
  - `.sql` files use `{{placeholder}}` templating (see `render.py`) for dataset names, the
    benchmark window, and the P2/P4 planted-problem parameters -- no Jinja (not an allowed
    dependency). `map_category_family` is a genuinely hand-maintained governed table (all 27
    current categories hardcoded in its VALUES list, per DEV_PLAN 9.2); only the renamed pair's
    names are templated from settings, not the full category list.
  - `fct_orders` keeps fully-cancelled orders as rows (gross_revenue = 0) rather than dropping
    them; `is_first_order`/`order_sequence_number` are only assigned among orders with
    gross_revenue > 0 (the same "orders" definition as the metric catalog and truth.py).
- **Milestone 6** (agent and baseline): done. `shared/backends/{base,naive_bigquery}.py`,
  `shared/agent/{tools,prompts,loop}.py`, `shared/agent/providers/{base,gemini_vertex,
  anthropic_provider}.py`. `make agent-smoke` runs one question end to end on both providers
  against `naive_bigquery` -- confirmed live, both reach `final_answer` with the correct number.
  - **A model turn can request several tool calls at once** (both Gemini and Claude do this) --
    discovered live: Gemini errored ("number of function response parts...") when the loop only
    answered the first call of a multi-call turn. The loop and both providers now execute every
    call in a turn and send all results back together in one round-trip
    (`Provider.send_tool_results`, plural).
  - `naive_bigquery` restricts a single query to one "metric family" (transactional order-item
    metrics; `signups`; `sessions`/`session_conversion_rate`; the two cohort metrics
    `new_customers`/`repeat_purchase_rate_90d`) -- realistic for a semantic layer with no
    fan-out-safe join graph across those grains, and it keeps the compiler simple. A mixed
    request comes back as a warning, not a crash, so the agent can split it into two calls.
  - `attribution_coverage_rate` is the only metric marked unavailable (per DEV_PLAN 11.2);
    `category_family` and `customer_cohort_month` are the only dimensions not offered at all,
    since both need governed-layer logic no raw-table query can produce.
  - The naive backend's BigQuery client is lazy (built on first `run()`, not in `__init__`), so
    `tests/test_naive_bigquery.py` can test SQL compilation and error handling without live
    credentials.
  - `AgentRun.estimated_cost_usd` is computed from `config/settings.yaml`'s `models.prices` and is
    `None` if `run_agent()` isn't given `models` (as the unit tests don't, deliberately).
  - `MAX_TOOL_CALLS = 8` counts individual tool calls, not round-trips -- a turn with 3 parallel
    calls counts as 3 toward the budget, matching the plan's "max 8 tool calls" literally.
- **Milestone 7** (Cube Core): done. `project1-gcp-cube/cube/{docker-compose.yml,up.py,
  model/{cubes,views}/*.yml}`, `project1-gcp-cube/backend/cube_backend.py`, `tests/{conftest,
  test_cube_contract,test_cube_layer_correctness}.py`. `make cube-up` brings up one
  `cubejs/cube:v1.7.46` container (dev mode, embedded Cube Store, no separate cubestore service);
  `make cube-test` runs both tests. Confirmed live against BigQuery: the contract test passes
  (the `commerce` view's measures/dimensions equal `catalog.yaml` exactly, modulo one documented
  exception -- see below); the layer correctness test passes all 22 checks (every catalog metric
  plus the P2 category_family-survives-the-rename check) within 0.5% of ground truth computed
  fresh from `data/true` via DuckDB, independent of `truth.py`'s own aggregation.
  - `project1-gcp-cube/backend/` isn't a Python package either (same hyphen reason as
    `bigquery/`); `tests/conftest.py` loads `cube_backend.py` by file path
    (`importlib.util.spec_from_file_location`), not `import`.
  - **Cube's YAML same-cube column syntax is `{CUBE}.column`, not `{CUBE.column}`.** Got this
    wrong in every join declaration on the first pass; the failure mode is a confusing
    `"customers.created_date_key cannot be resolved"` (Cube parses `{CUBE.x}` as a foreign-cube
    member reference, substitutes the cube's own name for `CUBE`, then fails to find member `x`
    on it) -- found live, not from docs.
  - **BigQuery DATE vs TIMESTAMP, twice over.** (1) Cube's `dateRange` filters compare a `type:
    time` dimension against TIMESTAMP literals; any such dimension built on a raw DATE column
    (`dim_date.date`, `dim_customer`/mart's `customer_cohort_month`) needs `TIMESTAMP(...)` cast
    in its `sql:`, or BigQuery raises "No matching signature for operator >=". (2) Cube only
    auto-qualifies a *bare* column name in `sql:` with the cube's own table alias -- the moment
    `sql:` is an expression (any function call), you must write `{CUBE}.column` explicitly for
    every column in it, or BigQuery raises "Column name ... is ambiguous" the moment a joined
    cube's table happens to share that column name (`customer_cohort_month` exists on both
    `dim_customer` and `mart_customer_cohorts`).
  - **Cube cannot join two different fact cubes together even through one shared conformed
    dimension** -- confirmed live (`"Can't find join path to join 'order_items', 'dates',
    'orders', 'customers'"`), not a fan-out-safety feature for that case, just a hard limit of
    this version. `order_items` and `orders` both needed `order_created` under the same catalog
    name; giving them one shared view member forced that unsupported join on every
    `orders`/`aov`/`purchasing_customers`/`new_customers` query. Fixed by exposing `orders`' own
    `order_created` under an internal-only view alias (`orders_created`, documented in
    `commerce.yml` and excluded from the contract test via `_INTERNAL_ONLY_DIMENSIONS`) and having
    `cube_backend.py::_time_dimension_member` route the catalog's one "order_created" name to
    whichever physical member the requested metrics' cube actually needs -- the agent only ever
    sees one name. This is a genuine layer-correctness finding worth keeping for the README, not
    just a workaround.
  - Every ratio measure uses `SAFE_DIVIDE`, matching `naive_bigquery`'s own convention -- bare `/`
    on two BigQuery INT64s still throws on division by zero.
  - `up.py` resolves `CUBE_SA_KEY_PATH` to forward slashes before handing it to `docker compose`
    as a bind-mount source (Windows backslashes break the volume syntax) and polls `/readyz`
    instead of returning as soon as `docker compose up -d` exits.
- **Milestone 8** (evals: golden questions, scorers, judge, runner, report): done. `shared/evals/
  {golden_questions.yaml,golden_questions,scorers,judge,models,report,runner}.py`, `tests/
  test_evals.py`. `make eval BACKEND=... PROVIDER=... QUESTIONS=... REPEATS=...` runs
  `shared.evals.runner`, writing `runs/<timestamp>_<backend>_<provider>/{traces.jsonl,scores.csv,
  report.md}`. Live-smoke-tested end to end (`naive_bigquery x gemini`, single question, real
  BigQuery + Gemini + the Claude judge) -- this surfaced and fixed three real bugs the milestone
  exists to catch, none of them eval-code bugs:
  - **The system prompt's "today's date" was genuinely ambiguous.** It stated `benchmark_date`
    (2026-08-31, the *last day of* August) as "today," and Gemini reasonably resolved "last month"
    to July, not August -- disagreeing with every `truth.py` "last_month"/"last_quarter"/etc.,
    which all mean August. Fixed in `shared/agent/prompts.py`: the prompt now names the completed
    month explicitly ("The most recently completed calendar month is August 2026...") instead of
    relying on the model to infer it from a boundary date. This is a Milestone 6 prompt fix,
    found only because Milestone 8 finally asked date-scoped questions for real.
  - **The judge's `max_tokens=300` truncated `claude-opus-5`'s response mid-JSON-string.**
    claude-opus-5 thinks by default (adaptive thinking, even with no `thinking` param set) and
    300 tokens wasn't enough for thinking + the verdict. Fixed in `shared/evals/judge.py`:
    `max_tokens=1024` and `output_config={"effort": "low"}` (grading doesn't need much reasoning).
  - **A real Milestone 3 bug in P4's order-date generation, found by the eval smoke test, not by
    `tests/test_world.py`.** `observe.py` drew each internal user's order dates uniformly between
    their signup and the *fixed window end*, not a fixed period after signup -- since signups are
    uniform across the window but the upper bound is fixed, the order date's marginal density
    diverges as it approaches the window end (integrates to ~ln(window / (window - T))), piling
    fake orders into the most recent months far more than the "small background noise" the plan
    intended (683 extra observed non-cancelled orders in August 2026 alone, before the fix).
    `tests/test_world.py::test_p4_internal_users_move_the_observed_metrics` didn't catch it
    because it only checks the AOV/repeat-rate delta, not the temporal distribution. Fixed by
    bounding every order to `repeat_within_days` (90) after signup, matching what "test accounts
    used briefly" was supposed to mean; `config/settings.yaml`'s comment on that field updated to
    match. **Required regenerating `data/observed` and reloading the whole BigQuery pipeline**
    (`bq-load` -> `bq-build` -> `bq-test`, all 16 assertions still pass) and rerunning `cube-test`
    (all 22 checks still pass) -- `data/truth` is untouched (it's built from `data/true`, which
    P4 never touches). Cube's `is_internal` exclusion was never affected by this bug (confirmed by
    `cube-test` passing both before and after the fix); only `naive_bigquery`, which structurally
    can't exclude internal users, was.
  - Confirmed live: Suits (-37%) and Jumpsuits & Rompers (-33%) rank ahead of Fashion Hoodies &
    Sweatshirts (-14.3%) in Q11's raw month-over-month category decline, but both are tiny
    categories (~20-40 items/month, vs Fashion Hoodies' ~350-400) where a small absolute change
    produces a large swing -- Q11's rubric now names this explicitly as a second trap layered on
    top of the Sweaters/Knitwear rename artifact, not just the single decliner CLAUDE.md's P2 note
    originally implied.
  - **P4-tagged numeric questions (Q01, Q04, Q05, Q07, Q14) don't let numeric tolerance gate
    pass/fail.** `naive_bigquery` structurally cannot exclude P4's internal accounts, so those
    questions' numbers are *expected* to run off-truth there (more so for a single recent month --
    P4 users' orders now cluster within 90 days of their own signup, so recent months see a bigger
    share) -- gating on a tight numeric tolerance would fail an agent for correctly reporting the
    polluted number and flagging why, exactly the behavior those questions are designed to reward.
    `ParaphraseResult.numeric_gates` (`shared/evals/models.py`) controls this per paraphrase, set
    by the runner from `"P4" not in question.planted_problems()`; the numeric score is still
    computed and shown in the report either way. Dollar metrics (Q02's net_revenue) don't need
    this -- P4's orders are individually tiny ($0.01-$1.00), contributing <0.15% of August 2026's
    net_revenue even though they're ~15% of its raw order count.
  - `truth.py` gained three answers.json fields Milestone 3 didn't need: `window_totals.
    session_conversion_rate`/`purchasing_customers`/`new_customers` (window-level, not summed from
    `monthly_metrics` -- purchasing_customers isn't summable across months without double-counting
    repeat customers, and session_conversion_rate needs summed converted_sessions/sessions, not an
    average of monthly rates), `channel_monthly` (Q12/Q13 -- true per-channel signups/new_customers,
    unaffected by P3's consent-loss nulls), and `margin_by_channel` (Q18 -- a channel-level rollup
    of `net_margin_by_cohort`).
  - `project1-gcp-cube/backend/` isn't a package (same hyphen reason as `bigquery/`); `runner.py`
    loads `cube_backend.py` by file path, the same way `tests/conftest.py` does.
- **Next:** Milestone 9 (the three required eval runs + `make compare`) per DEV_PLAN.md section 12.4.
