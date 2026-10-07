# Klarix Semantic AI Benchmark: Project 2 (dbt Core + MetricFlow on DuckDB)

Development plan for Claude Code. Save it as `docs/DEV_PLAN_PROJECT2.md`.

**Before writing any code, read these three files in full:**

1. `docs/DEV_PLAN.md`: the foundation and Project 1 plan. It still governs everything this plan doesn't override.
2. `CLAUDE.md`: decisions and findings from Project 1. Many of them apply here too.
3. This file.

Work one milestone at a time and **stop after each one for review**. A milestone is done only when its acceptance checks pass. Tell me what you ran and what came out.

---

## 1. Context and goal

Project 1 is done: BigQuery + Cube Core, answered by Gemini, with three eval runs and a case-study README.

Project 2 builds the **second standalone case study** on the same benchmark:

| | Project 1 (done) | Project 2 (this plan) |
|---|---|---|
| Warehouse | BigQuery (EU) | DuckDB (local file) |
| Transformation | Plain SQL views, `apply_sql.py` | **dbt Core** with `dbt-duckdb` |
| Semantic layer | Cube Core | **MetricFlow** (dbt semantic models and metrics) |
| Headline LLM | Gemini on Vertex AI | **Claude** (`claude-opus-5`) |
| Cloud cost | BigQuery + Vertex AI | None for the stack. API tokens only. |

The thesis stays the same: a semantic layer makes metric answers consistent, but not necessarily correct.

Project 2 adds two questions that only a second stack can answer:

1. **Does the stack matter?** We run the same data, questions, judge and models on a different semantic layer. Where do results differ, and why?
2. **What does "governed" look like in dbt?** That means dbt tests, documented models, and metric definitions that live next to the transformation code. This is the stack most mid-sized data teams in the DACH region already run, so the case study has to speak to them.

**This plan builds:**

1. A dbt project on DuckDB: sources, staging, star schema, marts and tests. It ports the Project 1 star schema.
2. A MetricFlow semantic layer that implements `shared/semantic/catalog.yaml` exactly.
3. A `metricflow` backend adapter that implements the existing `Backend` interface.
4. A `naive_duckdb` baseline: the same "hurried analyst" definitions as `naive_bigquery`, running on DuckDB.
5. Layer tests (contract + correctness) shared across backends.
6. Three required eval runs, a project comparison and a cross-stack comparison.
7. The case-study README `project2-dbt-metricflow/README.md`.

**Out of scope:** Power BI / TMDL (Project 3), any UI, the Klarix website, dbt Cloud, the dbt Semantic Layer APIs (hosted), and dbt Fusion.

---

## 2. Frozen: do not change these

Project 1's published results depend on these files. **If you think any of them needs to change, stop and ask me first.** Don't change them as a side effect.

| Path | Why it's frozen |
|---|---|
| `data/snapshot/`, `data/true/`, `data/observed/`, `data/truth/` | Same data for every stack. Never regenerate, never re-pull. |
| `shared/world/*` | Generates the worlds and truth. |
| `shared/semantic/catalog.yaml` | The contract every stack implements. |
| `shared/semantic/query.py`, `catalog.py` | The semantic query contract. |
| `shared/evals/golden_questions.yaml`, `scorers.py`, `judge.py` | Same questions, same scoring, same judge. |
| `shared/agent/prompts.py` | The system prompt must be identical across stacks. |
| `config/settings.yaml` → `seed`, `benchmark`, `planted_problems`, `models` | Same window, same problems, same models. |
| `project1-gcp-cube/**` | Finished case study. |
| `runs/2026093*` | The pinned Project 1 runs. |

**Allowed shared changes** are listed explicitly in this plan:

- 7.4: the layer test refactor
- 8.1: the naive compiler refactor
- 9.1: a configurable tool budget, default unchanged
- 9.4: pinned runs in `compare.py`

Each one must leave Project 1 behaviour byte-identical. Each comes with a test that proves it.

---

## 3. Hard constraints

Everything in DEV_PLAN section 2 still applies:

- no agent frameworks
- the LLM never writes SQL
- truth is independent
- deterministic outputs
- Python 3.12, `uv`, `ruff`, `pytest`, pydantic v2
- secrets only in `.env`
- small, readable modules

New for Project 2:

- **New dependencies, approved:** `dbt-core`, `dbt-duckdb`, `dbt-metricflow` (or whatever package currently provides the MetricFlow CLI and Python API for dbt Core). Anything else, including dbt packages like `dbt_utils`, needs my approval first. Write small macros instead.
- **Do not pin versions from memory.** Check the current dbt, dbt-duckdb and MetricFlow docs and PyPI. Pick the latest stable versions that work together on Python 3.12. Pin them exactly, and record them in CLAUDE.md with the date checked.
- **Check MetricFlow's current license** and note it in the README. Its license changed in the past, so don't state it from memory.
- **dbt Core only.** Use no dbt Cloud features and no hosted Semantic Layer API. Everything runs locally and offline, except the LLM calls.
- **Windows-first.** I run this on Windows. Paths must work with backslashes and spaces. Any script that prints LLM output must reconfigure stdout to UTF-8 (see CLAUDE.md). Every Make target must stay a thin `uv run ...` wrapper.
- **One source of truth for parameters.** dbt must read the benchmark window and planted-problem names from `config/settings.yaml`, passed in as dbt vars by a small Python wrapper. Never hardcode them a second time in dbt. The one exception is the hand-maintained `map_category_family` seed, same as Project 1.
- **No hints in agent-facing text.** No metric or dimension description the agent can see may name a planted problem (`P1` to `P5`) or a planted-problem parameter (the renamed category names, the P5 traffic source, the consent date, the internal email domain, or the internal name prefixes). Section 6.7 adds a test for this.

---

## 4. Repository layout (new and changed files)

```text
klarix-semantic-benchmark/
├── config/
│   ├── settings.yaml                 # unchanged (frozen keys); may gain a `project2:` block
│   └── runs.yaml                     # NEW: pinned run directories per comparison (9.4)
├── shared/
│   ├── backends/
│   │   ├── naive_sql.py              # NEW: dialect-agnostic naive compiler (8.1)
│   │   ├── naive_bigquery.py         # thin wrapper over naive_sql (BigQuery dialect)
│   │   └── naive_duckdb.py           # NEW: thin wrapper over naive_sql (DuckDB dialect)
│   ├── agent/loop.py                 # max_tool_calls becomes a parameter, default 8 (9.1)
│   └── evals/
│       ├── runner.py                 # registers metricflow + naive_duckdb, --max-tool-calls
│       └── compare.py                # reads config/runs.yaml; --project, --cross-stack (9.4)
├── project2-dbt-metricflow/
│   ├── README.md                     # case study (Milestone P2-7)
│   ├── run_dbt.py                    # wrapper: settings.yaml -> dbt --vars, fixed paths
│   ├── dbt/
│   │   ├── dbt_project.yml
│   │   ├── profiles.yml              # committed; DuckDB path only, no secrets
│   │   ├── macros/                   # surrogate_key, safe_divide, window helpers
│   │   ├── seeds/map_category_family.csv
│   │   ├── models/
│   │   │   ├── sources.yml           # data/observed/*.parquet as external sources
│   │   │   ├── staging/              # stg_*.sql + _staging.yml
│   │   │   ├── star/                 # dim_*, fct_* + _star.yml (tests, docs)
│   │   │   ├── marts/                # mart_customer_cohorts + _marts.yml
│   │   │   └── semantic/             # semantic models + metrics YAML (MetricFlow)
│   │   └── tests/                    # singular tests (reconciliation etc.)
│   ├── backend/
│   │   └── metricflow_backend.py     # Backend implementation
│   └── parity/
│       └── compare_star.py           # optional: DuckDB star vs BigQuery star (6.6)
├── data/warehouse/apparel_ecom.duckdb  # gitignored (under data/)
└── tests/
    ├── layer/                        # NEW: backend-agnostic contract + correctness (7.4)
    ├── test_metricflow_contract.py
    ├── test_naive_sql_refactor.py    # proves naive_bigquery SQL is byte-identical (8.1)
    └── test_agent_text_hygiene.py    # no planted-problem hints in agent-facing text (6.7)
```

`project2-dbt-metricflow/` has a hyphen, so it isn't a Python package. This works the same as Project 1: load `metricflow_backend.py` by file path (`importlib.util.spec_from_file_location`) in the runner and `tests/conftest.py`. Run scripts as files, never with `-m`.

---

## 5. Milestone P2-1: Spike and environment decision (stop and report)

This milestone produces a decision, not features. Answer these four questions with evidence, then stop.

**5.1 Dependency resolution.** Can `dbt-core`, `dbt-duckdb` and the MetricFlow package install into the existing `uv` environment next to `google-genai`, `anthropic`, `google-cloud-bigquery` and pydantic v2, without downgrading anything?

- **If yes:** add them as a `project2` dependency group in `pyproject.toml`.
- **If no** (MetricFlow has pinned conflicting versions in the past): put dbt and MetricFlow in a separate `uv` project at `project2-dbt-metricflow/.venv`. The backend then calls MetricFlow through a subprocess. Report the exact conflict.

**5.2 MetricFlow interface.** Find the current, documented way to:

- (a) compile a query to SQL without executing it
- (b) list metrics, dimensions and their descriptions from the semantic manifest
- (c) query with metrics, group-by items, time grain, a where clause, order and limit

Prefer the Python API (one engine object reused across queries) over the CLI. If the Python API isn't public or stable, use `mf query --explain` and the `semantic_manifest.json` that `dbt parse` writes. Show me a 10-line proof for each of (a), (b) and (c) against a toy model.

**5.3 Execution path.** Decide who executes the compiled SQL.

- **Preferred:** MetricFlow compiles; our backend executes the SQL on its own **read-only** DuckDB connection. This gives us control over types, row conversion, latency measurement and `compiled_query`.
- If MetricFlow can only execute through its own client, document that.

**5.4 DuckDB file locking.** DuckDB allows one writer, or many readers in read-only mode. Confirm that `dbt build` and a read-only backend can't collide. Make the backend fail with a readable message if the file is locked ("run the backend after dbt build finishes").

**Deliverable:** a short report in your reply, plus a `## Project 2 decisions` section in CLAUDE.md covering versions, environment layout, interface choice and execution path. **Stop.**

---

## 6. Milestone P2-2: dbt project (sources, staging, star, marts, tests)

This ports the Project 1 BigQuery modeling (`project1-gcp-cube/bigquery/sql/`) to dbt on DuckDB. **The Project 1 SQL is the reference implementation.** Same grains, same columns, same names, same business rules. Port it; don't redesign it. If the port forces a difference, document it in the model's YAML `description` and in CLAUDE.md.

### 6.1 Runtime and wrapper

- **DuckDB file:** `data/warehouse/apparel_ecom.duckdb`, which is gitignored. Rebuilding it from scratch must be deterministic.
- **`run_dbt.py`:** reads `config/settings.yaml` and calls dbt with fixed `--project-dir` and `--profiles-dir`. It passes these vars:
  - `window_start`, `window_end`
  - P2's `old_name`, `new_name`, `family`
  - P4's `email_domain`, `name_prefixes`
  
  It forwards any extra CLI args (`build`, `test`, `docs generate`, `--select ...`).
- **`profiles.yml`:** committed. DuckDB path relative to the repo root, resolved by the wrapper. Single thread is fine.
- **Schemas inside DuckDB** mirror Project 1: `staging`, `star`, `marts`. Configure them per folder in `dbt_project.yml`.

### 6.2 Sources

`sources.yml` declares the seven observed tables as external Parquet sources. Use dbt-duckdb's external location support, pointing at `data/observed/<table>.parquet`.

The observed Parquet files *are* the raw layer, the equivalent of `apparel_ecom_raw`. There's no separate load step.

Add `not_null` and `unique` source tests on primary ids.

### 6.3 Staging

Staging is one view per source, matching `10_staging/*.sql`:

- snake_case names
- typed columns
- timestamps kept, date columns derived
- no business logic

### 6.4 Star schema and marts

Port these one to one:

- `dim_date`, `dim_customer`, `dim_product`, `dim_distribution_center`
- `fct_order_items`, `fct_orders`, `fct_sessions`
- `mart_customer_cohorts`

Materialize star and marts as tables.

Every model YAML entry has:

- a `description` stating the **grain** first
- a description for every column
- the design notes from Project 1's SQL headers (category_family fixes P2, is_internal fixes P4, "Unattributed" exposes P3, separate gross and net columns handle P1)

These notes are for humans reading dbt docs. They are **not** agent-facing; the agent only sees metric and dimension descriptions (6.7).

**Dialect translation rules** (BigQuery → DuckDB). Each one is written once, as a macro:

| BigQuery (Project 1) | dbt on DuckDB |
|---|---|
| `FARM_FINGERPRINT(x)` cast to INT64 | macro `surrogate_key(cols)`: a deterministic signed 64-bit integer from a stable hash such as MD5 of the concatenated, null-safe natural key. It must be stable across DuckDB versions, so **don't use DuckDB's `hash()`**. Unknown member stays `-1`. |
| `SAFE_DIVIDE(a, b)` | macro `safe_divide(a, b)` → `a / nullif(b, 0)` |
| `{{placeholder}}` templating (`render.py`) | `{{ var('...') }}` from the wrapper |
| `map_category_family` VALUES list | dbt **seed** `map_category_family.csv`, hand-maintained, with all current categories. The renamed pair's names must match `settings.yaml`. A singular test checks that. |
| TIMESTAMP / DATE handling | DuckDB `TIMESTAMP` and `DATE`. Keep the same columns as Project 1. |

Keep Project 1's Milestone 3 rules:

- History before `window_start` is kept.
- The window is a filter applied at metric time, not by deleting rows.
- `is_first_order` and `order_sequence_number` are assigned only among orders with `gross_revenue > 0`.
- Fully cancelled orders stay as rows in `fct_orders`.

### 6.5 dbt tests (port of the 16 Project 1 assertions)

`dbt build` must run and pass all of these:

| Project 1 assertion | dbt equivalent |
|---|---|
| PK uniqueness, every dim and fact (7) | `unique` + `not_null` generic tests |
| No orphan FKs (5) | `relationships` tests (the unknown member `-1` exists in every dim, so they resolve) |
| `fct_order_items` row count = observed `order_items` row count | singular test |
| Gross revenue in `fct_order_items` reconciles to observed source within 0.01 | singular test |
| Every category in `dim_product` has a `category_family` | singular test, or `not_null` + `relationships` to the seed |

Add these new tests:

- **Seed parameter check:** `map_category_family` contains P2's old and new name, both mapped to P2's `family` var.
- **Internal flag count:** `dim_customer.is_internal` flags exactly `planted_problems.p4_internal_users.count` users. Project 1 verified this live; here it becomes a test.
- **Unattributed bucket:** `acquisition_channel` and `session_traffic_source` contain "Unattributed" and no NULLs.

### 6.6 Optional parity check against Project 1

`make p2-parity` runs `parity/compare_star.py`. It needs GCP credentials and is skipped otherwise.

For every star and mart table it compares, between DuckDB and BigQuery:

- the row count
- the sum of each numeric measure column
- the count of each flag column

It then prints a table. Expected result: identical counts, and sums within 0.01%.

Surrogate key *values* will differ, because the hash is different. That's fine: compare aggregates, not keys. This check is a cheap story for the README ("same model, two engines, same numbers").

### 6.7 Agent-text hygiene test (new, shared)

Add `tests/test_agent_text_hygiene.py`. For every backend that can be built offline, it collects all agent-facing metric and dimension descriptions (whatever `list_metrics()` and `list_dimensions()` return) and fails if any contains:

- `\bP[1-5]\b`
- or any planted-problem parameter value from `settings.yaml`: category names, traffic source, email domain, name prefixes, or dates

**Known issue to report, not fix:** Project 1's Cube model description for `attribution_coverage_rate` (`project1-gcp-cube/cube/model/cubes/customers.yml`) mentions "P3 (consent-tracking loss)". That text reached the agent in the Project 1 runs. Don't edit Project 1 (it's frozen).

- Mark the Cube case as `xfail` with a reason pointing to this paragraph.
- Write the finding up for me in your milestone report.
- Project 2's descriptions must pass the test.

**Acceptance for P2-2:**

- `make p2-build` runs `dbt build` (seeds, models and tests) green from an empty warehouse file.
- `make p2-docs` generates dbt docs.
- Report: row counts per table, all test results, and the parity table if GCP is available.

**Stop.**

---

## 7. Milestone P2-3 and P2-4: MetricFlow semantic layer and backend

### 7.1 Semantic models (P2-3)

Put the YAML in `models/semantic/`. Use whichever semantic-model YAML spec the current dbt docs recommend for your pinned version. If the docs describe both an older and a newer spec, use the newer one and note it in CLAUDE.md.

| Semantic model | Built on | Primary entity | Foreign entities | `agg_time_dimension` |
|---|---|---|---|---|
| `order_item` | `fct_order_items` | `order_item` | `customer`, `product`, `order` | `order_created` (from `created_date_key` via date, or the created timestamp) |
| `order` | `fct_orders` | `order` | `customer` | `order_created` |
| `customer` | `dim_customer` | `customer` | (none) | `user_created` |
| `product` | `dim_product` | `product` | `distribution_center` (or the denormalized name, as in Project 1) | (none) |
| `session` | `fct_sessions` | `session` | `customer` | `session_started` |
| `customer_cohort` | `mart_customer_cohorts` | `customer` (or a natural key; avoid a second primary entity named `customer`, see note) | (none) | `customer_cohort_month` |

**Note on entities:** MetricFlow resolves joins through entities. Two semantic models with the same *primary* entity can make dimension names ambiguous. Model `customer_cohort` so that `customer_cohort_month` has exactly one source, the same rule Cube's `customer_cohorts` cube follows. Write down the choice you made.

### 7.2 Measures and metrics: exact mapping to the catalog

**Two rules apply to every metric.**

1. **Item-population logic lives in the measure `expr`.** This covers not-cancelled, returned, and net. Example: `gross_revenue` is `sum(case when not is_cancelled then sale_price else 0 end)`. Logic in the measure is visible, testable, and identical for every metric built on the measure.
2. **Internal-user exclusion lives in a metric-level `filter`**, applied to every agent-facing metric and every helper metric: `{{ Dimension('customer__is_internal') }} = false`. This is the MetricFlow equivalent of Cube's per-measure `filters`.

A contract test (7.5) asserts every catalog metric carries this filter, directly or through the metrics it's built from. This is a governance finding for the README: MetricFlow has no default segment, so exclusion is a convention you have to enforce with a test.

**Helper metrics.** Ratio and derived metrics in MetricFlow reference other metrics, so some non-catalog helpers are needed:

- `returned_items`, `cancelled_items`, `all_items`
- `converted_sessions`, `known_channel_signups`

Mark every helper with `meta: {agent_facing: false}`. The backend only exposes catalog names. The contract test asserts that every non-catalog metric is marked this way.

| Catalog metric | Semantic model | MetricFlow type | Definition (must equal Cube + catalog) |
|---|---|---|---|
| `gross_revenue` | order_item | simple | sum of sale_price, not cancelled (includes returned) |
| `returned_revenue` | order_item | simple | sum of sale_price where returned |
| `net_revenue` | (derived) | derived | `gross_revenue - returned_revenue` |
| `cogs` | order_item | simple | sum of cost, not cancelled and not returned (`net_cost`) |
| `gross_margin` | (derived) | derived | `net_revenue - cogs` |
| `gross_margin_pct` | (derived) | derived or ratio | `gross_margin / net_revenue` |
| `orders` | order_item | simple, `count_distinct` | distinct `order_id` with at least one non-cancelled item |
| `aov` | (derived) | ratio | `net_revenue / orders` |
| `items_sold` | order_item | simple | count of non-cancelled items |
| `return_rate` | (derived) | ratio | `returned_items / items_sold` |
| `cancellation_rate` | (derived) | ratio | `cancelled_items / all_items` |
| `purchasing_customers` | order_item | simple, `count_distinct` | distinct customer with a non-cancelled item |
| `new_customers` | order | simple | count of orders where `is_first_order` |
| `repeat_purchase_rate_90d` | customer_cohort | simple, `average` | avg of `repeat_within_90d` as 0/1 |
| `signups` | customer | simple | count of users |
| `sessions` | session | simple | count of sessions |
| `session_conversion_rate` | (derived) | ratio | `converted_sessions / sessions` |
| `attribution_coverage_rate` | (derived) | ratio | `known_channel_signups / signups` (users with known, non-null channel) |

`orders` and `purchasing_customers` are defined on `order_item`, unlike Cube, which used `fct_orders`. This keeps `aov = net_revenue / orders` inside one semantic model. It gives the same numbers as truth. The layer correctness test proves it. Document why in the YAML.

### 7.3 Dimensions and descriptions

**Group-by names.** Every catalog dimension maps to exactly one MetricFlow group-by item. Keep the mapping in **one** table in `metricflow_backend.py`, named `DIMENSION_MAP`, for example:

- `category` → `product__category`
- `acquisition_channel` → `customer__acquisition_channel`
- `customer_cohort_month` → `customer_cohort__customer_cohort_month`
- `distribution_center` → `product__distribution_center`
- `item_status` → `order_item__item_status`

Name MetricFlow dimensions so the part after `__` equals the catalog name wherever possible.

**Descriptions.** The description of every agent-facing metric and dimension is the `catalog.yaml` description, **verbatim** (whitespace-normalized). Copy it into the MetricFlow YAML. A test compares them.

This is deliberate. Project 1's Cube descriptions drifted from the catalog (see 6.7). In Project 2 the catalog is the only text the agent sees, so the layer is the only variable.

**Hidden columns.** Don't expose columns the catalog doesn't have, such as `is_internal`. If MetricFlow forces them to exist as dimensions (it does for filtering), keep them out of what the backend returns from `list_dimensions()`.

### 7.4 Backend-agnostic layer tests (allowed shared refactor)

Move the logic of `tests/test_cube_contract.py` and `tests/test_cube_layer_correctness.py` into `tests/layer/`, parametrized over a backend fixture (`cube`, `metricflow`). Each backend is skipped if it isn't reachable: Cube not up, or the DuckDB warehouse missing.

- **Same checks, same truth, same tolerance** (`REL_TOL = 0.005`) for both. Add a report of the **maximum observed deviation** per backend. DuckDB vs DuckDB should be close to exact, and that's a nice line for the README.
- Keep the Cube-specific internal alias (`orders_created`) as a per-backend exception list, not as shared logic.
- `make cube-test` must still run and pass for Cube exactly as before.
- Expected exception, same as Project 1: `attribution_coverage_rate` is only sanity-checked as a valid ratio below 1, because P3 is unrecoverable by design.

### 7.5 `metricflow_backend.py` (P2-4)

It implements `Backend` (`list_metrics`, `list_dimensions`, `run`), with `name = "metricflow"`.

**Startup**

- Build the MetricFlow engine or manifest **once** per backend instance, not per query.
- Open DuckDB read-only.
- Fail with a readable message if the warehouse file is missing ("run make p2-build") or locked.

**`list_metrics` / `list_dimensions`**

- Read from the MetricFlow semantic manifest, not from `catalog.yaml`. The layer has to describe itself, same as Cube's `/meta`.
- Filter to catalog names. `available=True` for all 18 metrics.

**`run(query)`**

1. Call `validate_query()` from `shared/semantic/catalog.py` first, same as the other backends. On errors, return them as readable warnings and don't compile.
2. **Time dimension routing** (the important part, so be careful). Each metric has a MetricFlow `agg_time_dimension`; the catalog maps it to one catalog time name. Then:
   - **If every requested metric's own time dimension equals `query.time_dimension`:** group by `metric_time` at `time_grain`, and apply `time_range` to `metric_time`.
   - **If not** (for example `return_rate` by `user_created`, which is a legitimate signup-cohort question and the core of Q20): group by the explicitly named time dimension through the entity path, e.g. `customer__user_created__month`, and apply `time_range` to **that** dimension. Add a warning that says exactly what the time range filtered on.
   - **If MetricFlow can't resolve the path:** return a warning naming each metric's own time dimension, so the agent can split the query. Never raise.
   - **`customer_cohort_month`** (month grain only): treat it as a time dimension for `repeat_purchase_rate_90d`, and as a plain group-by elsewhere.
3. **Filters.** Translate `Filter` ops to MetricFlow where-clause syntax: `{{ Dimension('...') }}` for categorical dimensions and `{{ TimeDimension('...', 'day') }}` for time.
   - `in` / `not_in` become SQL `IN` lists.
   - **Escape every value.** Values come from an LLM, so double single quotes and reject control characters.
   - Numbers are bound as numbers.
   - Combine multiple filters with `AND`.
4. **Order and limit.** `order_by` uses catalog names; map them to MetricFlow output names. `limit` passes through.
5. **Compile** to SQL through the interface chosen in P2-1, execute it on the read-only connection, and convert rows to plain Python types: dates as ISO strings, decimals as floats.
6. **Output columns.** Rename them back to **catalog names**. A time column is named after the requested catalog time dimension (for example `order_created`), never `metric_time__month`. The agent and the scorers must see the same column shape as Cube.
7. Return `SemanticResult(compiled_query=<the SQL MetricFlow generated>, backend="metricflow", latency_ms=..., warnings=[...])`. Latency covers compile and execute.

**Contract test (`tests/test_metricflow_contract.py`)**

- Manifest metric names ⊇ catalog metrics. Every extra metric has `meta.agent_facing: false`.
- `list_metrics()` and `list_dimensions()` names equal the catalog exactly.
- Descriptions equal the catalog verbatim (whitespace-normalized).
- Every catalog metric excludes internal users: either it carries the `is_internal` filter itself, or every metric it's built from does. Walk the metric graph in the manifest.
- `DIMENSION_MAP` covers every catalog dimension, and each target resolves in MetricFlow for at least one metric.

**Unit tests (offline, no LLM)**

- filter escaping (including a value with a quote in it)
- time routing for each of the three cases in step 2
- output column renaming
- readable errors for unknown names

**Acceptance for P2-3 and P2-4:**

- MetricFlow's config validation passes.
- The contract test passes.
- The layer correctness suite passes for `metricflow` (all checks Cube passes, same expected exception).
- `make cube-test` still passes.
- Report the max deviation per backend.

Stop after P2-3 (semantic models validated). Stop again after P2-4 (backend and tests green).

---

## 8. Milestone P2-5: `naive_duckdb` baseline

The baseline must be the **same naive definitions** as Project 1 on a different engine. It is not a new baseline. That way "naive vs governed" means the same thing in both case studies.

### 8.1 Refactor (allowed shared change)

Extract `naive_bigquery.py`'s compiler into `shared/backends/naive_sql.py`. Use a small dialect object for the parts that differ:

- identifier and table quoting
- date truncation
- safe division
- date literal casts

`naive_bigquery.py` and `naive_duckdb.py` become thin wrappers: dialect, connection and table locations.

**Proof that Project 1 is untouched:** before refactoring, write `tests/test_naive_sql_refactor.py`. It compiles about 15 fixed `SemanticQuery` objects with the current `NaiveBigQueryBackend` and stores the SQL strings as a fixture. That should cover every metric family, every filter op, time grains, order and limit. After the refactor, the test asserts the generated SQL is **byte-identical**. This test is offline (the BigQuery client is lazy).

### 8.2 `naive_duckdb`

- Reads `data/observed/*.parquet` directly (the raw layer, equivalent to `apparel_ecom_raw`), through DuckDB views or `read_parquet`.
- Same metric families, same unavailable metric (`attribution_coverage_rate`), and the same missing dimensions (`category_family`, `customer_cohort_month`) as `naive_bigquery`.
- Module docstring: "LLM on raw tables, no governed semantic layer", same as Project 1.

**Optional live parity** (`make p2-naive-parity`, needs GCP): run the 15 fixture queries through both naive backends and assert identical results within 0.01%.

**Acceptance:**

- The refactor test passes.
- `naive_duckdb` unit tests pass.
- `make agent-smoke` still works.
- A new `make p2-smoke` runs one question on `naive_duckdb` and on `metricflow` with Claude, end to end.

**Stop.**

---

## 9. Milestone P2-6: Eval runs and comparisons

### 9.1 Tool budget (allowed shared change)

In Project 1, Claude hit the 8-tool-call limit before answering in **21 of 60** control runs. Project 2's headline model is Claude, so the budget matters.

- Make `max_tool_calls` a parameter of `run_agent()` and `--max-tool-calls` a CLI option of the runner. **Default stays 8.** With the default, the system prompt text must be byte-identical; a test checks this.
- Record `max_tool_calls` in every `traces.jsonl` record and in the `report.md` header.
- **Required runs use 8**, for comparability with Project 1.
- Add one **sensitivity run** at 12. It's reported separately, never mixed into the headline.

### 9.2 Required runs

Smoke first: 3 questions × 1 paraphrase per run. Show me the cost estimate before the full runs.

| # | Run | Purpose |
|---|---|---|
| 1 | `naive_duckdb × anthropic` | Baseline: Claude on raw tables |
| 2 | `metricflow × anthropic` | **Headline** |
| 3 | `metricflow × gemini` | Control. Same model as Project 1's headline, so `cube × gemini` vs `metricflow × gemini` isolates the layer. |
| 4 (sensitivity) | `metricflow × anthropic`, `--max-tool-calls 12` | Shows how much of Claude's score was budget, not model or layer |

All runs use `--questions all --repeats 1`, the same judge (`claude-opus-5`, the cached judge is fine) and the same golden questions.

**Reported limitation, not a fix:** in run 2 the judge and the agent are the same model. Keep the judge fixed (comparability beats everything). Also hand-review 10 randomly sampled judge verdicts from run 2 against the rubric. Report how many you'd overturn and why. This goes into the README.

**Expected cost:** Project 1's runs cost about $15 (Claude) and $10 (Gemini) per 60 answers. Budget about $55 for runs 1 to 4 plus judge calls. Report actual tokens and cost per run.

**If results deviate strongly from expectations, report them rather than tuning prompts to fit** (same rule as DEV_PLAN 15).

### 9.3 Failure analysis (new, small)

For runs 2 and 3, write `runs/<run>/failures.md` (the report generator can produce it). For each failed question, classify the **primary** cause as exactly one of:

- `layer_wrong`: the layer returned a number that disagrees with truth
- `agent_query`: the agent asked the wrong query (wrong metric, dimension, filter or time)
- `agent_interpretation`: the right data came back, but the conclusion was wrong
- `budget`: the agent hit the tool limit
- `clarification`: the agent didn't ask, or asked when it shouldn't have
- `judge_disputed`: you think the judge is wrong

Start from a deterministic first-pass guess: `budget` from `terminal_tool`, and `layer_wrong` if the layer correctness suite flags the metric. Then **I review the classification**, so present it as a table for me to correct, not a final verdict.

This is the most valuable table in the case study: it shows *why* the layer helped or didn't.

### 9.4 Pinned runs and comparisons (allowed shared change)

`compare.py` currently picks the **latest** run per backend × provider. That's already wrong: there are newer `naive_bigquery_gemini` runs (for example `20261002_110657`, which scored 5% with 37 of 60 answers hitting the tool limit) that aren't the published baseline.

Fix it like this:

- Add `config/runs.yaml` that pins run directories by key. Project 1's three pinned runs are the ones listed in the current `runs/COMPARISON.md`.
- `compare.py` reads the pins and fails loudly if a pinned directory is missing. It never falls back to "latest" silently.
- `make compare` keeps producing `runs/COMPARISON.md` for Project 1, byte-identical to the current file apart from line endings. Test that against the pinned runs.
- `make compare PROJECT=2` produces `runs/COMPARISON_project2.md` for runs 1 to 3, with run 4 in a separate sensitivity section.
- `make compare-cross` produces `runs/CROSS_STACK.md` with:
  - **layer effect, model held constant:** `cube × gemini` vs `metricflow × gemini`, and `cube × anthropic` vs `metricflow × anthropic`
  - **baselines:** `naive_bigquery × gemini` vs `naive_duckdb × anthropic` (this mixes model and engine, so label it that way)
  - per-category and per-planted-problem pass rates, cost, tokens and median latency for each
  - both the strict metric (all paraphrases plus consistency) and the paraphrase-level pass rate. Project 1's case study uses both.

**Acceptance:**

- Runs 1 to 4 complete.
- All three comparison files are generated.
- The failure tables are ready for my review.

**Stop.**

---

## 10. Milestone P2-7: Case study README

`project2-dbt-metricflow/README.md` is a standalone case study. A reader who never sees Project 1 must understand it. Plain language, short sentences, no hype.

**Sections**

1. **The question.** Same thesis, one paragraph, plus why a dbt-native layer is worth testing separately.
2. **Architecture.** A Mermaid diagram: observed Parquet → dbt (staging → star → marts, tests) → MetricFlow → backend → agent. Truth sits on the side, independent.
3. **Star schema.** A Mermaid ER diagram. Note that it's the same model as Project 1, rebuilt in dbt, plus the parity result if it was run.
4. **How each planted problem is handled** by design, or deliberately not: a table like Project 1's.
5. **Governance in dbt.** What dbt tests guarantee, and how internal-user exclusion is enforced (a metric filter plus a contract test, because MetricFlow has no default segment).
6. **Results.**
   - pass rates, strict and paraphrase-level, by category and by planted problem
   - cost and latency
   - the sensitivity run
7. **Why the layer did or didn't help:** the reviewed failure-cause table from 9.3.
8. **Two stacks, same benchmark.** Five or six honest bullets from `CROSS_STACK.md`, such as:
   - where MetricFlow's entity joins avoided Cube's fact-to-fact limitation
   - where it was harder
   - differences in agent behaviour on the same model
9. **Engineering findings.** Real ones found during the build, each with the symptom and the fix, like Project 1's Cube findings. Collect them in CLAUDE.md as you go.
10. **Honest limitations:**
    - the same model as agent and judge in run 2, plus the hand-review result
    - one repeat per question
    - DuckDB is single-node
    - P3 is unrecoverable by design
    - the agent-text leak found in Project 1 (6.7)
11. **Privacy note:**
    - Everything runs locally.
    - The agent sees metric metadata and aggregated results only, never raw rows.
    - Claude is called through the Anthropic API under its standard commercial terms (verify the current wording on API data use before publishing, rather than stating it from memory).
    - The data is Google's public, synthetic theLook dataset.
12. **Reproduce it:** the exact `make` targets, in order.
13. **Screen-recording checklist:**
    - `dbt build` going green
    - the dbt docs lineage graph
    - a MetricFlow query and its compiled SQL
    - one trap question answered naive vs governed

Also:

- Update the root `README.md`: project table status, a Layout entry for `project2-dbt-metricflow/`, and glossary entries for every new term (dbt, MetricFlow, semantic model, entity, measure, metric_time, `agg_time_dimension`, helper metric, `naive_duckdb`, sensitivity run, pinned run, failure cause).
- Update CLAUDE.md: Project 2 status per milestone, and the decisions and findings.

**Stop for my review of the README draft.**

---

## 11. Makefile targets (add these)

```text
make p2-setup          # install the project2 dependency group (or the separate env from P2-1)
make p2-build          # run_dbt.py build   (seeds, models, tests; fresh warehouse file)
make p2-test           # run_dbt.py test
make p2-docs           # run_dbt.py docs generate
make p2-mf-validate    # MetricFlow config validation
make p2-layer-test     # contract + layer correctness for metricflow
make p2-parity         # optional, needs GCP: DuckDB star vs BigQuery star
make p2-naive-parity   # optional, needs GCP: naive_duckdb vs naive_bigquery
make p2-smoke          # one question, naive_duckdb + metricflow, Claude
make eval BACKEND=metricflow PROVIDER=anthropic [MAX_TOOL_CALLS=8]
make compare [PROJECT=1|2]
make compare-cross
```

Every target is a thin `uv run ...` wrapper (Windows).

---

## 12. Milestone summary (stop after each)

| Milestone | Delivers | Stop for |
|---|---|---|
| P2-1 | Spike: dependencies, MetricFlow interface, execution path, file locking | Environment and interface decision |
| P2-2 | dbt project: sources, staging, star, marts, tests, hygiene test, optional parity | Row counts, test results, the Cube description finding |
| P2-3 | MetricFlow semantic models and metrics, validated | Modeling choices (entities, helpers, internal filter) |
| P2-4 | `metricflow_backend.py`, contract test, shared layer tests | Layer correctness results for both backends |
| P2-5 | `naive_sql` refactor, `naive_duckdb`, smoke | Refactor proof, smoke output |
| P2-6 | Tool budget parameter, 4 runs, failure tables, pinned comparisons | Results and failure classification review |
| P2-7 | Case study README, root README and CLAUDE.md updates | README review |

---

## 13. Acceptance criteria (whole project)

- The frozen list (section 2) is untouched. `git diff` against the Project 1 tag shows no changes to frozen paths.
- `make p2-build` is green from an empty warehouse, and rebuilding gives the same table row counts and aggregates.
- These pass:
  - MetricFlow validation
  - the metricflow contract test
  - the layer correctness suite for both backends, with the documented `attribution_coverage_rate` exception
  - `test_naive_sql_refactor.py`
  - the hygiene test (Project 2 passes; Cube is `xfail` with its reason)
  - `make test` and `make lint`
- `make cube-test` still passes, and `make compare` regenerates Project 1's `COMPARISON.md` unchanged from the pinned runs.
- Required runs 1 to 3 and sensitivity run 4 are complete, and `COMPARISON_project2.md` and `CROSS_STACK.md` are generated.
- Total API spend is reported, and the target is under $60.
- No secrets in git, and the DuckDB file is gitignored.

---

## 14. Questions to raise with me, not decide alone

- Any change to a frozen path.
- A MetricFlow limitation that would force a definition to differ from the catalog or Cube. Report it with a proposed workaround and its effect on comparability.
- A dependency conflict that the separate-environment fallback (5.1) doesn't solve.
- Results that look too good or too bad, for example `metricflow × gemini` far above `cube × gemini`. Check the layer and the hygiene test before believing it.
- Anything in the failure analysis you classify as `judge_disputed`.
