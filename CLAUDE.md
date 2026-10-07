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
  test_cube_contract,test_cube_layer_correctness}.py` (since moved to `tests/layer/`, see P2-4). `make cube-up` brings up one
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
## Project 2 decisions

Spec: [project2-dbt-metricflow/DEV_PLAN_PROJECT2.md](project2-dbt-metricflow/DEV_PLAN_PROJECT2.md)
(the plan asks for `docs/DEV_PLAN_PROJECT2.md`; it lives in the project folder instead). The
"Project 1 tag" the plan mentions doesn't exist -- create one before P2-2 so the frozen-path diff
in the plan's section 13 has something to compare against.

**P2-1 spike (checked 2026-10-06; environment decision confirmed by the user: `project2` dependency group in the main env, pinned exactly, `[tool.uv] default-groups` includes it; git tag `project1-final` marks the frozen Project 1 state):**
- **Versions that resolve together on Python 3.12:** `dbt-core 1.12.5`, `dbt-duckdb 1.11.0`,
  `dbt-metricflow 0.15.0` (pulls `metricflow 0.213.0`), `duckdb 1.5.5` (unchanged). All Apache-2.0
  per the installed package metadata (re-check the upstream repo before the README states it).
- **One transitive downgrade:** `dbt-core` requires `protobuf>=6,<7`, so `protobuf` goes 7.36.2 ->
  6.33.6. Nothing is removed and nothing else changes. `google-cloud-bigquery`, `google-genai` and
  `anthropic` all import fine on 6.33.6 (checked in a scratch env). The plan's "without
  downgrading anything" strictly fails on this one package; recommendation is still a `project2`
  dependency group in the main env (a separate venv would force a subprocess backend).
- **MetricFlow Python API** (`metricflow.engine.metricflow_engine.MetricFlowEngine`) works, but its
  own docstring says the class is not a stable API ("TODO: provide a more stable API layer"). Pin
  the version exactly. Proven on a toy model: `engine.explain(MetricFlowQueryRequest.create(...))
  .sql_statement.sql` compiles without executing; `engine.list_metrics()` / `list_dimensions(
  [metric])` give names, types, descriptions; the compiled SQL runs on our own connection.
- **Execution path:** MetricFlow compiles, our backend executes on its own read-only DuckDB
  connection. The engine needs a `SqlClient` (sql_engine_type, sql_plan_renderer, query, execute,
  dry_run, close, render_bind_parameter_key); the CLI's one wraps a dbt adapter (read-write), so
  write a ~15-line read-only one. Manifest: `parse_manifest_from_dbt_generated_manifest` (from
  `metricflow_semantics.model.dbt_manifest_parser`) on `target/semantic_manifest.json`, which
  `dbt parse`/`build` writes.
- **File locking (Windows, tested with two processes):** one writer XOR many read-only readers.
  A read-only open while dbt holds the file fails with `IOException ... being used by another
  process`; a dbt write while a reader holds it fails the same way. The backend must catch that
  and say "run the backend after dbt build finishes".
- **Semantic YAML spec:** dbt-core 1.12.5 supports the new inline "v2" spec (a `semantic_model:`
  block on the model, `entity:`/`dimension:` on columns, simple metrics with `agg` + `expr`; there
  are no separate `measures`). **The docs page puts `agg_time_dimension` inside `semantic_model:`;
  the installed version rejects that** -- it must be a sibling key at the model level
  (`agg_time_dimension: x` next to `semantic_model:`). Found live, not from the docs.
- **A time spine model is mandatory** (`time_spine: standard_granularity_column:` on a model with a
  DAY column) or `dbt parse` fails; `dim_date` is the natural candidate.
- **dbt-duckdb's relative `path:` resolves against the current directory, not the profiles dir**
  -- `run_dbt.py` must pass an absolute path.
- **Windows path length:** a scratch venv under the Claude scratchpad (path > 260 chars) made
  Python fail to import `anthropic` ("No module named ...") even though the file existed. Not a
  dependency problem; keep Project 2 paths short.

**P2-2 (dbt project): done, awaiting review.** `project2-dbt-metricflow/{run_dbt.py,dbt/,parity/}`,
`tests/test_agent_text_hygiene.py`, `make p2-{setup,build,test,docs,parity}`. `make p2-build` runs 87
dbt nodes (1 seed, 7 staging views, 9 tables, 70 tests) green from an empty `data/warehouse/
apparel_ecom.duckdb` in ~5 s of dbt time; two fresh builds give identical row counts and
per-table content fingerprints. `make p2-parity` against Project 1's BigQuery star: 44 aggregates
(row counts, measure sums, date-key sums, flag counts), 0 mismatches.
- Findings from the port:
  - Parquet timestamps are TIMESTAMPTZ; `DATE()` on those follows the session time zone in DuckDB
    (BigQuery is always UTC). Staging casts via `utc_ts()` to a naive UTC TIMESTAMP, and the
    profile also pins `TimeZone: UTC`.
  - dbt prefixes custom schemas with the target schema by default; a `generate_schema_name`
    override makes them plain `staging`/`star`/`marts`, mirroring Project 1's datasets.
  - Surrogate keys: `md5_number_lower` shifted by 2^63 into signed BIGINT (not `hash()`).
  - Two deliberate deviations from the BigQuery SQL, both for determinism (documented in the model
    SQL headers): `fct_orders` ranks with an `order_id` tie-breaker (91 users have two orders at
    one timestamp), and `fct_sessions` uses MIN instead of ANY_VALUE (every session has exactly one
    user and one traffic source, so the values are identical).
  - Relationship tests need the `arguments:` form under dbt 1.12 (no deprecation warnings).
  - `dbt_project.yml` warns "paths ... do not apply to any resources" until `models/semantic/`
    gets files in P2-3.
- **Hygiene test result (the finding the plan asks to report):** exactly one Cube description
  reaches the agent with a planted-problem label: the `attribution_coverage_rate` measure in
  `project1-gcp-cube/cube/model/cubes/customers.yml` says "P3 (consent-tracking loss)".
  `naive_bigquery`'s 31 descriptions are clean. The Cube case is a strict `xfail`. **Lesson:** a
  strict xfail also swallows a crashing collector (the first version crashed on aliased `includes`
  entries and still "xfailed"); the test now asserts what it collects, and was checked by listing
  the actual hits.
- Lint: `ruff check` has one pre-existing E501 in `shared/agent/loop.py:144` (Project 1 code, not
  touched) and four Project 1 files fail `ruff format --check`; neither was changed.

**P2-3 (MetricFlow semantic models): done, awaiting review.** `project2-dbt-metricflow/dbt/models/
semantic/{_semantic.yml,sem_*.sql}`, `run_mf.py`, `make p2-mf-validate`. `mf validate-configs`: 0
errors, 0 future-errors, 0 warnings, including all six warehouse-level validations. 93 dbt nodes green.
- **Design:** six semantic models, each a thin `sem_*` view in `models/semantic/` (a dbt model can
  carry only one YAML patch, and the star tables already have theirs). The views exist because
  MetricFlow needs a real time column inside the model while the star schema keeps only date keys:
  `sem_order_items`, `sem_orders`, `sem_customers` join `dim_date`; `sem_sessions` casts the start
  timestamp to a date; `sem_products` and `sem_customer_cohorts` are pass-throughs. Star-schema
  columns are unchanged, so the BigQuery parity result still holds.
- **Entities:** `order_item`, `order`, `customer`, `product`, `session` are primary in their own
  model. `sem_customer_cohorts` has primary entity `customer_cohort` plus a *foreign* `customer`
  entity (declared via `derived_semantics`, since a v2 column carries only one entity), so
  `customer_cohort_month` has exactly one source and the internal-account filter reaches the same
  `customer__is_internal` as every other metric. `sem_customers` deliberately omits
  `customer_cohort_month`.
- **Spec notes (v2, dbt-core 1.12.5):** metrics sit under the model that owns them; there is no
  top-level `meta` on a metric (use `config: {meta: ...}`) and `hidden: true` marks private metrics.
  Helper metrics carry both `hidden: true` and `meta.agent_facing: false`; catalog metrics carry
  `meta.unit`. Descriptions/units were generated once from `catalog.yaml` and are verbatim (checked:
  18/18 metrics, 15/15 dimensions equal modulo whitespace). Catalog has 15 dimensions, not the 14
  stated earlier in this file.
- **Internal exclusion** is a metric-level `filter` on every simple metric (ratio/derived inherit it
  through their inputs). `is_internal` is a hidden `sem_customers` dimension (the only non-catalog
  dimension); the P2-4 backend must not list it.
- **`signups`/`known_channel_signups` exclude the -1 unknown member** (Cube's count did not).
- **MetricFlow advantage over Cube, confirmed live:** metrics from different fact models
  (`orders` on items, `new_customers` on orders) combine in one query via `metric_time`; Cube's
  fact-to-fact join limit does not exist here. `order_created` is defined on two models
  (`sem_order_items`, `sem_orders`), which is harmless in MetricFlow.
- **Open points for P2-4:** (1) `repeat_purchase_rate_90d` averages `repeat_within_90d` over every
  customer in the mart, never-buyers included (same as Cube): ungrouped it is diluted; grouped by
  cohort month, never-buyers fall into a NULL-month group (rate 0). The plan and Cube both define it
  this way, so it is unchanged; raise if the layer test says otherwise. (2) The catalog's default
  time dimension for `repeat_purchase_rate_90d` is `user_created`, but its MetricFlow
  `agg_time_dimension` is `customer_cohort_month` (as the plan specifies, as in Cube): the backend's
  time routing must handle that.
- **Windows:** `mf` crashes through a pipe under cp1252 (its spinners print emoji; the error
  surfaces as a misleading "cannot use a string pattern on a bytes-like object" while parsing the
  manifest, which actually parses fine). `run_mf.py` runs it with `PYTHONUTF8=1`.

**P2-4 (MetricFlow backend + shared layer tests): done, awaiting review.**
`project2-dbt-metricflow/backend/metricflow_backend.py`, `tests/layer/{conftest,test_contract,
test_correctness}.py`, `tests/test_metricflow_{contract,backend}.py`, `make p2-layer-test`. Full suite
with both backends live: 133 passed, 1 expected xfail, 0 skipped. `make cube-test` (now
`pytest tests/layer -k cube`): 22 passed, the same 22 checks as before the refactor.
- **Backend shape:** `plan()` (pure: routing, filter translation, escaping) -> `compile()` (MetricFlow
  `explain`) -> `run()` (our own read-only DuckDB connection, columns renamed to catalog names,
  dates as ISO strings, decimals as floats). A connection is opened per query and closed again, so
  `dbt build` is never blocked between queries; a missing or locked warehouse raises a readable
  RuntimeError ("make p2-build" / "run the backend after it finishes").
  `list_metrics`/`list_dimensions` read the semantic manifest (descriptions, units, grains), not
  `catalog.yaml`; grains are intersected with the catalog's (the cohort month stays month-only).
- **Time routing (the three cases of plan 7.5, tested):** all metrics' own time dimension ==
  `time_dimension` -> `metric_time` (month grain for cohort metrics); otherwise the named dimension
  via its entity link with a warning saying what the range filtered on; if MetricFlow cannot
  resolve it, a warning naming each metric's own time dimension (never an exception).
  `order_created` has a documented alternate path (`order__order_created`) tried second.
  `repeat_purchase_rate_90d` queried by `user_created` routes through the customer link (rule 2).
- **Value safety:** MetricFlow renders where-clauses as Jinja, so besides doubling quotes and
  rejecting control characters the backend rejects `{{ }}`, `{% %}`, `{# #}` in values (otherwise
  an LLM-supplied value could inject a template expression); NaN/inf, booleans, non-ISO time
  filter values and empty IN lists are rejected with readable messages.
- **Layer correctness, maximum relative deviation from truth (tolerance 0.5%):**
  - metricflow: every metric at float precision (~1e-15) except `repeat_purchase_rate_90d` 2.2e-3.
  - cube: `repeat_purchase_rate_90d` 2.2e-3, `orders` 7.7e-4, `purchasing_customers` 5.1e-4, the rest
    near exact. MetricFlow's `orders`/`purchasing_customers` (defined on items, per the plan) are exact
    where Cube's (defined on `fct_orders.gross_revenue > 0`) differ by a few zero-price orders.
  - The repeat-rate gap is identical in both and is a property of the shared mart rule: "second order
    within 90 calendar days" (date_diff of order dates, so a same-day second order counts) vs truth's
    timestamp rule (0.10188 vs 0.10166, measured). Not a layer bug; kept as ported.
- **Test changes to the shared Project 1 tests (allowed, plan 7.4):** (1) the truth queries bounded
  timestamps with `BETWEEN '{start}' AND '{end}'`, which stops at midnight at the start of the
  last day and silently dropped 2026-08-31 (~0.14%, hidden by the 0.5% tolerance); now an exclusive
  upper bound of end + 1 day, which made the "max deviation" line meaningful. Cube still passes.
  (2) the repeat-rate check was only `0 <= x <= 1`; it now compares the cohort-size-weighted average
  of the layer's monthly rates against a rate recomputed from the true world. (3) the Cube-view tests
  keep their `orders_created` exception as a per-backend table, not shared logic.
- **Gotchas:** a backend module loaded by file path must be put in `sys.modules` before exec (its
  `@dataclass` with `from __future__ import annotations` looks the module up; the runner must do
  the same in P2-5). The first 20 layer tests errored with a confusing
  `'NoneType' object has no attribute '__dict__'` until then.
- Cube was brought up for the Cube run and stopped again afterwards (`docker stop cube-cube-1`;
  `docker compose down` fails without the env vars `cube/up.py` supplies).

**P2-5 (`naive_sql` refactor, `naive_duckdb`, smoke): done, awaiting review.**
`shared/backends/{naive_sql,naive_bigquery,naive_duckdb}.py`, `tests/test_naive_sql_refactor.py` +
`tests/fixtures/naive_bigquery_sql.json`, `tests/test_naive_duckdb.py`,
`project2-dbt-metricflow/{smoke_test.py,parity/compare_naive.py}`, `make p2-smoke`,
`make p2-naive-parity`. Full suite 161 passed, 22 skipped (Cube down), 1 expected xfail.
- **Refactor proof:** before touching `naive_bigquery.py`, the SQL it generated for 20 fixed queries
  (every metric family, all six filter ops, all five grains, order/limit, quote escaping, all
  12 transactional metrics at once) was captured to `tests/fixtures/naive_bigquery_sql.json`.
  After the refactor all 20 are byte-identical (the test compiles offline; the fixture is only
  regenerated with `--regenerate`, never to make the test pass).
- **Design:** `naive_sql.py` holds the compiler, validation and the shared `NaiveSqlBackend`; a small
  `Dialect` (table, quote, date_trunc, safe_divide, if_, countif, bool_or) is all that differs per
  engine. `naive_bigquery.py` = BigQuery dialect + lazy client + byte-guarded `_execute`;
  `naive_duckdb.py` = DuckDB dialect + in-memory views over `data/observed/*.parquet` (pinned to
  UTC; independent of the dbt warehouse file, so it can run during `dbt build`). Error messages use
  the backend's own name, so they are unchanged for `naive_bigquery`.
- **Live parity (`make p2-naive-parity`):** the same 18 runnable queries through both naive
  backends: 0 differences at 0.01% tolerance (up to a 149,197-row group-by). Two fixture queries
  (`filter_gte_lte_numeric`, `filter_eq_numeric`) compare numbers to the string-valued
  `customer_age_band`: they exist to cover the numeric filter code paths in the byte proof and cannot
  run on any engine.
- **Smoke (Claude, "How many orders did we have last month?", est. cost ~$0.08-0.14 per run):**
  `naive_duckdb` -> 5,898 orders, high confidence, no mention of internal accounts; `metricflow`
  -> 4,633 (matches the layer-correctness number, internal users excluded). Both reach
  `final_answer`. The 27% gap is the visible cost of P4 (partly offset by the next point).
- **A naive-definition quirk worth a README line (identical in both engines, kept as is):** the
  time range is `created_at >= 'start' AND created_at <= 'end'` on a timestamp, which stops at
  midnight at the start of the last day, so the naive backends drop most of 2026-08-31 (26 orders
  instead of ~300). Gemini noticed it on `agent-smoke` and spent its 8-call budget investigating
  the "partial last day" (`terminal_tool: max_tool_calls`); Claude did not.
- **`make agent-smoke` after the refactor:** exit 0, live BigQuery through the refactored `_execute`,
  generated SQL identical to Project 1's; Claude reached `final_answer`, Gemini ended on the tool
  budget for the reason above (consistent with the budget findings in Project 1's runs, not a
  regression: its first query returned the same 5,898 as the DuckDB backend).
- The eval runner registers `naive_duckdb` and `metricflow` (`--backend`); `metricflow` is loaded by
  file path with its module put in `sys.modules` first (see the P2-4 gotcha).
- Total API spend for P2-5 (3 smoke runs + `agent-smoke`): about $0.5 of Anthropic/Gemini tokens,
  plus a few cents of BigQuery scans for the parity run.

**Scope decision (2026-10-07, user): Project 2's paid eval runs are NOT executed.** The budget
(~$55 for four runs) is too high for a portfolio piece. P2-6 is therefore code + tests only, and
every Project 2 results section/README must say so plainly: the layer-correctness numbers, the
smoke test and the byte-identity proof are real and measured; pass rates for the four eval runs do
not exist and must never be invented or implied. Do not run `make eval` for Project 2 without the
user's explicit go-ahead and a fresh cost estimate.

**P2-6 (budget parameter, failure analysis, pinned comparisons): code and tests done, no paid run.**
`shared/agent/loop.py`, `shared/evals/{runner,report,compare,failures}.py`, `config/runs.yaml`,
`tests/{test_tool_budget,test_compare,test_failures}.py`. Full suite 194 passed, 22 skipped (Cube
down), 1 expected xfail.
- **Tool budget (9.1):** `run_agent(max_tool_calls=8)`, `make eval MAX_TOOL_CALLS=...`
  (`--max-tool-calls`); recorded on every `AgentRun` (traces.jsonl) and in the report.md header;
  older traces load as 8. At 8 the system prompt is byte-identical to the pre-change capture
  (`tests/fixtures/system_prompt_default.txt`); at another value only the number changes.
- **Pinned runs (9.4):** `config/runs.yaml` pins directory names per project; `make compare` /
  `compare PROJECT=2` / `compare-cross` read only those pins and fail loudly when a pin is unset or
  its directory is missing (never "latest" - runs/ holds newer unpublished naive x gemini runs).
  Project 1's three pins are the runs in the existing COMPARISON.md. `make compare` regenerates
  Project 1's COMPARISON.md identically (tested against a capture, `tests/fixtures/
  COMPARISON_project1.md`, plus verified end to end). Project 2's four pins are null
  (not run): `compare --project 2` and `--cross-stack` therefore stop with "not pinned ... has not
  been published yet", by design. The reports themselves (3-run comparison, sensitivity section,
  cross-stack with strict + paraphrase-level rates and the "mixes model and engine" baseline label)
  are tested on synthetic runs.
- **Failure analysis (9.3):** `failures.md` is written after every run and by `make failures
  RUN=runs/<dir>`. A first-pass table for a human to correct (one primary cause per failed
  question): budget (a failed run ended on max_tool_calls) > layer_wrong (queried a metric the
  layer suite flagged, from `runs/layer_correctness.json`, which `tests/layer` now writes) >
  clarification > agent_query (a query came back with warnings) > needs_review; judge_disputed
  and agent_interpretation are never auto-assigned. Validated for free on Project 1's real runs:
  cube x gemini: 11 failed questions (= its 9/20 strict pass rate), cube x anthropic: 14 failed,
  10 of them attributed to the tool budget (consistent with Project 1's finding that Claude hit the
  8-call limit in 21 of 60 runs).
- Lint: the one pre-existing E501 in `loop.py` was fixed while editing that file; four Project 1
  files still fail `ruff format --check` (untouched).

**P2-7 (case study README, root README, CLAUDE.md): done, awaiting review.**
`project2-dbt-metricflow/README.md` (standalone case study; sections per the plan), root `README.md`
(Project 1 status "done", Project 2 status, Layout, a "Project 2: dbt and MetricFlow" glossary
section, `Backend`/`Control run` rows updated).
- **The README's honesty rule:** a status box at the top and an "Eval runs: not executed" section say
  the paid evaluation was not run; it reports measured things only (layer correctness vs truth, the
  deterministic 93-node build, DuckDB-vs-BigQuery parity, the byte-identical refactor proof, naive
  parity, one smoke question) and contains no Project 2 pass rate, cost or latency. The failure
  tool is shown validated on Project 1's real runs and labelled as such. Any edit that adds an
  agent result for Project 2 must come from a real run pinned in `config/runs.yaml`.
- **Verified from sources, not memory (2026-10-07):** MetricFlow license history (AGPL to 0.140.0,
  BSL 0.150.0-0.208.2, Apache 2.0 from 0.209.0; pinned 0.213.0 is Apache 2.0) from the upstream
  README; Anthropic API data use from its API data-retention docs (retained data is never used for
  training without express permission). The README tells the reader to re-check the wording.
- Two README claims were corrected on review: the `sem_order_items` model carries 12 catalog
  metrics (not 11), and Cube also uses a per-measure internal-user filter (the "no default
  segment" point is a MetricFlow convention, not a difference in how the two filter).

## Project 2 status

P2-1 to P2-7 are all done. Stack built and tested; **the four paid evaluation runs are intentionally
not executed** (user decision, 2026-10-07). Final state: 194 tests passed, 22 skipped (Cube down),
1 expected xfail; `ruff check` clean; no frozen path differs from the `project1-final` tag.
Project 3 (Power BI / TMDL) has not started.

- **Next:** review of P2-7. If the evaluation is ever to be run: get a fresh cost estimate, get the
  user's explicit go-ahead, run the four commands in the README's "Reproduce it", set the pins in
  `config/runs.yaml`, run `make compare PROJECT=2 && make compare-cross`, review each `failures.md`,
  and only then add results to the README.
