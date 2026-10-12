# Klarix Semantic AI Benchmark: Project 3 (Power BI Desktop, PBIP / TMDL)

This is the development plan for Claude Code. Save it as `project3-powerbi-tmdl/DEV_PLAN_PROJECT3.md`.

**Read these four files in full before writing any code:**

1. `docs/DEV_PLAN.md`: the foundation and Project 1 plan.
2. `project2-dbt-metricflow/DEV_PLAN_PROJECT2.md`: the Project 2 plan. Its patterns are reused here.
3. `CLAUDE.md`: every decision and finding from Projects 1 and 2.
4. This file.

Work one milestone at a time and **stop after each one for review**. A milestone is done only when its acceptance checks pass. Tell me what you ran and what came out.

---

## 1. Context and goal

Projects 1 and 2 are done and published:

- **Project 1:** BigQuery and Cube Core, with Gemini, three eval runs and a case study.
- **Project 2:** dbt Core and MetricFlow on DuckDB, with a layer-correctness case study.

Project 3 builds the **third standalone case study** on the same benchmark:

| | Project 2 (done) | Project 3 (this plan) |
|---|---|---|
| Tables | dbt star schema in DuckDB | **The same star schema**, exported to Parquet and imported into Power BI |
| Semantic layer | MetricFlow YAML | **Power BI semantic model**: TMDL files plus DAX measures |
| Query language the backend generates | SQL (compiled by MetricFlow) | **DAX** (compiled by our backend) |
| Where it runs | Any OS | **Windows only**: Power BI Desktop's local engine |
| Cloud cost | None | None. No Power BI service, no Fabric, no Microsoft account. |

**Why reuse the dbt star schema:** the tables are byte-for-byte the ones Project 2 already proved against truth and against BigQuery. So the **only** thing that changes in Project 3 is the semantic layer, meaning relationships, DAX measures and model settings. Any deviation from truth is a DAX or modeling problem, never a data problem.

**The thesis stays the same:** a semantic layer makes answers consistent, but not necessarily correct. Power BI adds its own ways to be subtly wrong:

- bidirectional relationships
- implicit measures
- auto date/time tables
- filter context

Project 3 shows that the same correctness harness catches them.

**This plan builds:**

1. An export of the dbt star schema and cohort mart to Parquet.
2. A Power BI Project (PBIP) whose semantic model is written as **TMDL text files under git**. Claude Code writes those files; Power BI Desktop opens them.
3. 18 catalog measures in DAX, implementing `shared/semantic/catalog.yaml` exactly.
4. Offline static tests on the TMDL files, which run on any OS without Desktop.
5. A `powerbi` backend that compiles a `SemanticQuery` to DAX and runs it on Desktop's local engine.
6. The shared layer tests (contract and correctness) run against Power BI, plus a parity check against MetricFlow.
7. A **Power BI traps** suite: four common modeling mistakes, each shown to produce a wrong number and each caught by a test.
8. The case-study README `project3-powerbi-tmdl/README.md`.

**Not in this project:**

- **Agent evaluation runs.** The backend is registered in the runner so the runs *could* be made with one command, but none are executed. See section 10 for how the README describes this.
- The Power BI service, Fabric, the XMLA endpoint and the Execute Queries REST API.
- Microsoft's Power BI MCP servers. They let the agent write DAX, which breaks the benchmark's rule.
- Power Query transformations beyond loading the Parquet files.
- The Klarix website.

---

## 2. Frozen: do not change these

Everything frozen in Project 2's plan (section 2) stays frozen. These are also frozen now:

| Path | Why it's frozen |
|---|---|
| `project2-dbt-metricflow/**` | Finished case study. Project 3 only **reads** its warehouse file. |
| `data/warehouse/apparel_ecom.duckdb` | Built by `make p2-build`. Project 3 reads it read-only and never rebuilds it. |
| `config/runs.yaml` project1 / project2 pins | Published comparisons. |
| `tests/fixtures/*` | Proofs from Project 2. |

Before you start, create a git tag `project2-final` on the current HEAD, if it doesn't exist. At the end, `git diff project2-final -- <frozen paths>` must be empty.

**Allowed shared changes.** Each must leave Projects 1 and 2 behaving exactly as before.

- `tests/layer/conftest.py`: add `powerbi` to the backend params. It is skipped when Desktop isn't reachable.
- `tests/test_agent_text_hygiene.py`: add the Power BI descriptions.
- `shared/evals/runner.py`: register `powerbi` in `build_backend`, loaded by file path like the other two.
- `Makefile`, root `README.md`, `CLAUDE.md`, `.gitignore`, `pyproject.toml` (a `project3` dependency group).

**If anything else seems to need changing, stop and ask me.**

---

## 3. Hard constraints

Everything in DEV_PLAN section 2 and Project 2's section 3 still applies:

- no agent frameworks
- the LLM never writes SQL, **or DAX**
- independent truth
- deterministic outputs
- Python 3.12, `uv`, `ruff`, `pytest`, pydantic v2
- secrets only in `.env`
- small, readable modules

New for Project 3:

- **Windows-first, Desktop-dependent.** Power BI Desktop's local Analysis Services engine only accepts connections from `localhost`. So:
  - Claude Code must run on the same Windows machine as Desktop.
  - Live tests need Desktop open with this project's `.pbip`.
  - Every live test **skips** with a clear reason when Desktop isn't reachable. It never fails for that reason.
  - Static tests (section 6.4) must run on any OS without Desktop.
- **Dependencies.**
  - `pythonnet` is approved, if the spike (P3-1) confirms it's the cleanest way to call ADOMD.NET from Python.
  - Microsoft's ADOMD.NET client library comes from NuGet, downloaded by a setup script into a **gitignored** folder. **Never commit Microsoft DLLs.**
  - Anything else needs my approval first.
- **Do not pin versions from memory.** Check current Power BI Desktop, PBIP/TMDL and ADOMD.NET docs. Record the versions and the date checked in CLAUDE.md. If PBIP or TMDL still needs a preview feature switched on in Desktop, say so and record which one.
- **The TMDL files in git are the source of truth for the model.** Never "fix" something only inside Desktop. If Desktop changes the files on save, commit what Desktop writes and record in CLAUDE.md what it changed.
- **One source of truth for parameters.** Catalog text comes from `catalog.yaml`. The window and planted-problem values come from `config/settings.yaml`. Neither is typed in a second time.
- **No hints in agent-facing text.** Same rule and same hygiene test as Project 2: no planted-problem labels (P1 to P5) and no planted-problem parameter values in any measure or column description the agent can see.

---

## 4. Repository layout (new and changed files)

```text
project3-powerbi-tmdl/
├── README.md                          # case study (P3-6)
├── DEV_PLAN_PROJECT3.md               # this file
├── setup_adomd.py                     # downloads ADOMD.NET from NuGet into a gitignored folder
├── export_star.py                     # DuckDB warehouse (read-only) -> data/powerbi/*.parquet + manifest
├── set_data_path.py                   # writes the absolute data folder into the TMDL parameter
├── tmdl_check.py                      # small TMDL reader used by the static tests (no Desktop)
├── traps.py                           # Power BI traps suite (P3-5)
├── pbip/
│   ├── KlarixApparel.pbip
│   ├── KlarixApparel.SemanticModel/
│   │   └── definition/                # TMDL: model.tmdl, tables/*.tmdl, relationships.tmdl, expressions.tmdl ...
│   └── KlarixApparel.Report/          # minimal report (may stay empty; see 9.3)
└── backend/
    ├── desktop_connection.py          # find the local engine's port, open an ADOMD connection
    ├── dax_compiler.py                # SemanticQuery -> DAX (pure, offline-testable)
    └── powerbi_backend.py             # Backend implementation
data/powerbi/                          # gitignored (under data/)
tests/
├── test_powerbi_static.py             # TMDL checks, any OS
├── test_dax_compiler.py               # compiler unit tests, any OS
└── test_powerbi_contract.py           # live: the model describes itself as the catalog
```

`project3-powerbi-tmdl/` has a hyphen, so it isn't a Python package. Load modules by file path, as in Projects 1 and 2. Keep paths short: Project 2 found that Windows' 260-character path limit breaks imports.

---

## 5. Milestone P3-1: Spike and environment decision (stop and report)

This milestone produces a decision, not features. Answer each question with evidence from a **toy** PBIP: one table, one measure. Then stop.

**5.1 PBIP and TMDL.**

- Confirm the current Desktop version saves the semantic model as TMDL inside a PBIP folder, and whether a preview setting is needed.
- Confirm a hand-written TMDL measure, edited in a text editor while Desktop is closed, appears correctly when the project is reopened.
- Record what Desktop rewrites on save (ordering, `lineageTag`s, annotations), so later diffs aren't surprising.

**5.2 Parquet import.**

- Confirm Power Query can load a local Parquet file, read through a model parameter that holds the folder path.
- Check how DuckDB's types arrive: BIGINT keys, DOUBLE money, DATE, BOOLEAN.
- Confirm a 650k-row table loads.

**5.3 Finding the engine.** While a project is open, Desktop runs a local Analysis Services instance on a random port. Confirm the current, reliable way to find it:

- a port file under the `AnalysisServicesWorkspaces` folder (the location differs between the Microsoft Store install and the normal installer, so check both), or
- the listening port of the `msmdsrv` process.

If several Desktop windows are open, the backend must pick **this** model's instance: check the database or table names and refuse to guess.

**5.4 Running DAX from Python.**

- Prove `EVALUATE ROW("x", 1)` and one `SUMMARIZECOLUMNS` query from Python through ADOMD.NET, using `pythonnet` with the NuGet DLL.
- Report the exact setup steps.
- If `pythonnet` can't load the library on this machine, report that and propose the fallback: a PowerShell subprocess that runs ADOMD.NET. **Don't build the fallback without my approval.**

**5.5 Self-description.** Find the current way to read measure names, descriptions and format strings **from the live model**, the way Cube's `/meta` and MetricFlow's manifest worked. Candidates, to be confirmed: the `INFO.VIEW.MEASURES()` / `INFO.MEASURES()` DAX functions, or a DMV query.

**5.6 Refresh.** Find out whether a full refresh of the import model can be triggered from Python against the local engine (a TMSL `refresh` command through ADOMD). If it can't, the documented step is "open the project in Desktop and click Refresh".

**Deliverable:**

- a short report in your reply
- a `## Project 3 decisions` section in CLAUDE.md covering versions, setup, port discovery, the query path, the self-description query and the refresh path

**Stop.**

---

## 6. Milestone P3-2: Data export and model skeleton

### 6.1 Export (`export_star.py`)

- Open `data/warehouse/apparel_ecom.duckdb` **read-only**. If it's missing, say "run make p2-build first". If it's locked, print the same message Project 2 uses.
- Export these tables to `data/powerbi/<table>.parquet`:
  - `star.dim_date`, `dim_customer`, `dim_product`, `dim_distribution_center`
  - `star.fct_order_items`, `fct_orders`, `fct_sessions`
  - `marts.mart_customer_cohorts`
- Columns are unchanged. Keep the same order as the dbt models.
- Write `data/powerbi/manifest.json` with row counts and content fingerprints (reuse Project 2's fingerprint approach). Two exports of the same warehouse must give identical manifests.
- `make p3-export` runs it.

### 6.2 Model skeleton (TMDL)

**Tables.** One table per exported file, loaded by a Power Query expression through a `DataFolder` parameter. `set_data_path.py` writes the absolute path into `expressions.tmdl`, and `make p3-set-path` runs it. **Never commit a machine-specific path**: commit a placeholder, and document the step.

**Role-playing date tables.** Power BI allows only one active relationship path between two tables. So instead of one `dim_date` with inactive relationships and `USERELATIONSHIP` in every measure, create **three date tables** from `dim_date.parquet`:

| Date table | Related to | Catalog time dimension |
|---|---|---|
| `Order Date` | `fct_order_items[created_date_key]`, `fct_orders[order_date_key]` | `order_created` |
| `Signup Date` | `dim_customer[created_date_key]` | `user_created` |
| `Session Date` | `fct_sessions[session_date_key]` | `session_started` |

Each date table:

- exposes the grain columns `Date`, `week_start`, `month`, `quarter`, `year`
- is marked as a date table on `Date`

Document this choice in the README. It is the standard Power BI answer to role-playing dimensions, and it keeps every measure free of relationship switching.

**Relationships.**

- All many-to-one, fact to dimension.
- **Single cross-filter direction everywhere.** No bidirectional relationships.
- `fct_order_items` → `dim_customer`, `dim_product`, `Order Date`.
- `fct_orders` → `dim_customer`, `Order Date`.
- `fct_sessions` → `dim_customer`, `Session Date`.
- `dim_customer` → `Signup Date`.
- `mart_customer_cohorts` → `dim_customer`, many-to-one and single direction. Don't make it one-to-one: a one-to-one relationship in Power BI defaults to bidirectional, which is one of the traps in section 8.

**`customer_cohort_month` has one source.** Expose it from `dim_customer` only, and hide the mart's copy. A filter on it then flows from `dim_customer` to the mart, so the cohort metric works, and other metrics can group by it too.

Before relying on this, verify that `dim_customer.customer_cohort_month` equals the mart's value for every customer. Add this as a static check on the exported Parquet files. If they differ, stop and report.

**Model settings.**

- **Auto date/time off.** No hidden `LocalDateTable_*` tables.
- **Implicit measures discouraged** at model level.
- Every numeric column set to "don't summarize".
- Every key column and `is_internal` hidden.
- Only catalog dimension columns are visible.

### 6.3 Opening and refreshing

Document the human steps in `project3-powerbi-tmdl/README.md` ("Reproduce it"):

1. Run `make p3-export` and `make p3-set-path`.
2. Open `KlarixApparel.pbip` in Desktop.
3. Refresh, unless P3-1 found a scripted refresh, in which case use `make p3-refresh`.

Claude Code must **tell me explicitly** whenever a TMDL change requires reopening the project in Desktop. Desktop does not reload TMDL files while they're open.

### 6.4 Static tests (`tests/test_powerbi_static.py`, any OS, no Desktop)

`tmdl_check.py` reads only the TMDL subset we use. It does not try to be a general TMDL parser. Validate it against the files Desktop actually writes.

The tests check:

- the tables, columns and relationships match section 6.2 exactly
- no relationship is bidirectional, and none is one-to-one
- auto date/time is off, and there are no `LocalDateTable_*` tables
- implicit measures are discouraged
- every numeric column is set to "don't summarize"
- keys and `is_internal` are hidden
- visible columns are exactly the catalog dimensions, plus the date tables' grain columns

**Live parity (needs Desktop).** Row counts per table, queried through DAX `COUNTROWS`, equal `data/powerbi/manifest.json`.

**Acceptance:**

- the export is deterministic
- the static tests pass
- after I open and refresh the project, the row counts match

Report the table of row counts. **Stop.**

---

## 7. Milestones P3-3 and P3-4: Measures and backend

### 7.1 Measures (P3-3)

The 18 catalog metrics are measures in one `Metrics` table, a measure-only table with no columns. Each measure has:

- **Name:** exactly the catalog name, e.g. `gross_revenue`.
- **Description:** the `catalog.yaml` text, **verbatim** after whitespace normalization. Generate it once from the catalog, never retype it.
- **Format string by unit:**
  - usd: two decimals
  - count: integer
  - ratio: a fraction with enough decimals, **not a percentage format**. The catalog says ratios are fractions, so 0.52 means 52%.

**Internal-user exclusion convention.** Power BI has no model-wide default filter, so this convention is enforced by a test, as in Project 2.

- Hidden **base measures** in a `_base` display folder each apply `KEEPFILTERS(dim_customer[is_internal] = FALSE())` exactly once. Examples: `_gross_revenue`, `_returned_revenue`, `_items_sold`, `_returned_items`, `_cancelled_items`, `_all_items`, `_orders`, `_signups`, `_known_channel_signups`, `_sessions`, `_converted_sessions`.
- Catalog measures are built **only** from base measures and other catalog measures.
- The static contract test walks the measure-reference graph. It fails if any catalog measure reaches a column aggregation without passing through a base measure that applies the filter.

**Definitions.** Each must equal the catalog. Where Project 2 made a choice, mirror it:

| Catalog metric | Built on | Definition |
|---|---|---|
| `gross_revenue` | `fct_order_items` | sum of `sale_price` where not cancelled (returned items included) |
| `returned_revenue` | `fct_order_items` | sum of `sale_price` where returned |
| `net_revenue` | measures | `gross_revenue - returned_revenue` |
| `cogs` | `fct_order_items` | sum of `cost` where neither cancelled nor returned |
| `gross_margin` | measures | `net_revenue - cogs` |
| `gross_margin_pct` | measures | `DIVIDE(gross_margin, net_revenue)` |
| `orders` | `fct_order_items` | distinct `order_id` with at least one non-cancelled item. Defined on items, as in Project 2, which was exact against truth. |
| `aov` | measures | `DIVIDE(net_revenue, orders)` |
| `items_sold` | `fct_order_items` | count of non-cancelled items |
| `return_rate` | measures | `DIVIDE(returned_items, items_sold)` |
| `cancellation_rate` | measures | `DIVIDE(cancelled_items, all_items)` |
| `purchasing_customers` | `fct_order_items` | distinct customer with a non-cancelled item |
| `new_customers` | `fct_orders` | count of rows where `is_first_order` |
| `repeat_purchase_rate_90d` | `mart_customer_cohorts` | average of `repeat_within_90d` as 0/1. Same population as Cube and MetricFlow. |
| `signups` | `dim_customer` | count of customers, **excluding the -1 unknown member**, as in Project 2 |
| `sessions` | `fct_sessions` | count of sessions |
| `session_conversion_rate` | measures | `DIVIDE(converted_sessions, sessions)` |
| `attribution_coverage_rate` | measures | `DIVIDE(known_channel_signups, signups)` |

**Two checks before trusting the numbers:**

1. **The unknown member and anonymous sessions.** Sessions without a user point to customer `-1`. Check what `is_internal` is on that row, and whether the session metrics match truth with the filter applied. Project 2's layer test answers what truth expects. Mirror it, and record the finding.
2. **Blank versus zero.** DAX returns BLANK, not 0, for empty filter contexts. The backend must turn BLANK into what the other backends return for an empty group. Check what Cube and MetricFlow actually return, and document it.

**Static contract test, extending `tests/test_powerbi_static.py`:**

- The `Metrics` measures equal the catalog names exactly, in both directions. Every other measure is hidden.
- Descriptions equal the catalog verbatim.
- Format strings match units.
- The internal-exclusion graph walk passes.
- The hygiene rule passes.

### 7.2 Backend (P3-4)

`powerbi_backend.py` implements `Backend` with `name = "powerbi"`.

**Startup.** Find this model's instance (5.3). If Desktop isn't open, raise a readable error: "Open project3-powerbi-tmdl/pbip/KlarixApparel.pbip in Power BI Desktop". If several instances are open, raise a readable error naming them. **Open a connection per query and close it**, as in Project 2.

**`list_metrics` / `list_dimensions`.** Read from the **live model** with the self-description query chosen in 5.5, not from `catalog.yaml`. Filter to catalog names. Dimension grains come from the date tables' grain columns, intersected with the catalog's grains.

**`DIMENSION_MAP`.** One table maps each catalog dimension to a `'Table'[Column]`, and each time grain to a date-table column.

| Catalog dimension | Model column |
|---|---|
| `category`, `category_family`, `brand`, `department`, `distribution_center` | `dim_product` |
| `customer_country`, `customer_age_band`, `customer_gender`, `acquisition_channel`, `customer_cohort_month` | `dim_customer` |
| `item_status` | `fct_order_items` |
| `session_traffic_source` | `fct_sessions` |

The last two are degenerate dimensions on the fact tables.

**Reachability.**

- Compute from the relationships which dimension columns can filter which measure's base table. Group-by columns on a fact table are reachable only by that fact's measures.
- An unreachable dimension, for example `item_status` on `sessions`, returns a **warning naming the metric and the dimension**. It never returns silently wrong numbers. In DAX, an unrelated group-by repeats the total on every row, which is a classic trap.

**`dax_compiler.py`.** These are pure functions with no connection, unit-tested offline.

1. **Validate first.** Call `validate_query()` first, same as every backend.
2. **Time routing.** Same three cases as Project 2 (plan 7.5):
   - the metric's own time dimension
   - another time dimension reachable through relationships, with a warning stating what the range filtered on
   - unreachable: a warning naming each metric's own time dimension, never an exception

   `repeat_purchase_rate_90d` by `user_created` goes through `dim_customer` → `Signup Date`. Its own axis is `customer_cohort_month`, at month grain only.
3. **Query shape.** `SUMMARIZECOLUMNS(<group-by columns>, <filter tables>, "<metric>", [<metric>], ...)`.
   - With no group-by, return one row.
   - Apply `limit` with `TOPN` over the summarized table, then `ORDER BY` from `order_by`.
   - Check the one known DAX behaviour: `SUMMARIZECOLUMNS` drops rows where **all** measures are blank. Make sure this matches how the other backends treat empty groups, or document the difference.
4. **Time range.** Filter the date table's `Date` column to the inclusive range, e.g. `KEEPFILTERS(DATESBETWEEN(...))` or an equivalent `FILTER(ALL(...))`. The range is inclusive on both ends; avoid the midnight bug Project 2 found in its truth queries.
5. **Filters.**
   - `eq` / `in`: `TREATAS({...}, 'T'[C])`.
   - `neq` / `not_in`: `KEEPFILTERS(FILTER(ALL('T'[C]), NOT 'T'[C] IN {...}))`.
   - `gte` / `lte` on time: date bounds.
   - **Escape every value.** Values come from an LLM:
     - strings become DAX string literals with `"` doubled
     - control characters are rejected
     - numbers must be finite
     - dates must be ISO
     - empty `IN` lists are rejected

     Nothing from the query is ever pasted into DAX outside a literal.
6. **Output.**
   - Rename columns to catalog names. ADOMD returns names like `dim_product[category]` and `[gross_revenue]`.
   - A time column is named after the requested catalog time dimension.
   - Dates become ISO strings, decimals become floats, and BLANK is handled as decided in 7.1.
7. **Result.** Return `SemanticResult(compiled_query=<the DAX>, backend="powerbi", latency_ms=..., warnings=[...])`.

**Tests:**

- **`tests/test_dax_compiler.py`** (offline): routing for all three cases, every filter op, escaping (including a value with a `"` in it and one with a DAX comment marker), `TOPN` and order, reachability warnings, and column renaming.
- **`tests/test_powerbi_contract.py`** (live): `list_metrics()` and `list_dimensions()` equal the catalog, and the live descriptions equal the catalog verbatim.
- **Shared layer tests:** add `powerbi` to `tests/layer/conftest.py`. The same 41 checks, the same truth and the same tolerance (0.5%) must pass. Expected exception, as before: `attribution_coverage_rate` is checked only as a valid ratio below 1.
- **Three-engine parity** (`make p3-parity`, live): run each layer-test query through `powerbi` and `metricflow`. Both read the same star schema, so the result should match to floating-point precision. Report the maximum difference. For the README this is the line "same tables, three engines, same numbers": BigQuery was matched in Project 2, MetricFlow and Power BI here.

**Acceptance for P3-3:**

- the static tests pass
- I reopen and refresh the project, and every catalog measure appears

**Acceptance for P3-4:**

- the compiler tests pass
- the live contract test passes
- the layer suite passes for `powerbi`
- `make cube-test` and `make p2-layer-test` still behave as before (skips allowed)
- the parity is reported

Stop after each.

---

## 8. Milestone P3-5: Power BI traps

This is the section that makes Project 3 more than "the same thing a third time". Each trap is a modeling mistake that is common in real Power BI models. For each one, `traps.py`:

- **shows the wrong number** it produces against truth
- **names the test** in this repo that catches it

Simulate each trap **inside the DAX query**, for example with `CROSSFILTER(..., Both)`, `CALCULATE` without the base measure, or a raw column `SUM`. **Never change the committed model.** The model stays correct; the trap is shown next to it.

| # | Trap | How to show it | Expected catcher |
|---|---|---|---|
| T1 | **Bidirectional relationship** | Turn on both-direction filtering between a fact and `dim_customer` (or between the mart and `dim_customer`) and find a catalog query whose number changes. Pick the clearest example; don't invent one that doesn't move. | Static test (no bidirectional relationships), plus the layer test if the number moves |
| T2 | **Measure without the internal-user filter** | `orders` for August 2026 computed without the base measure | Layer correctness (truth excludes internal users), plus the static graph walk |
| T3 | **Implicit or summed ratio** | Sum a per-row or per-group ratio instead of dividing totals, e.g. the sum of monthly `return_rate`s versus the true window rate | Layer correctness; implicit measures discouraged in the model |
| T4 | **Unrelated group-by** | Group `sessions` by `category`: DAX repeats the total on every row | Backend reachability warning (7.2) |

For each trap, write a table row: trap, query, wrong number, truth, deviation, and which test catches it.

- If a trap **doesn't** move the number on this data, say so plainly. Don't tune the data to make it move.
- If Auto date/time is worth showing too, add it as a fifth trap only if you can show a concrete effect. Otherwise mention it as a model setting.

`make p3-traps` runs the suite (live) and writes `runs/powerbi_traps.md`.

**Acceptance:** the trap table is produced, and every claimed catcher is shown actually failing on the trap. **Stop.**

---

## 9. Milestone P3-6: Wiring, report page and case study

### 9.1 Wiring

- Register `powerbi` in `shared/evals/runner.py` (by file path). `make eval BACKEND=powerbi PROVIDER=anthropic` must start, find Desktop, and fail cleanly if Desktop isn't open.
- **Do not run it.** Add a `project3:` block to `config/runs.yaml` with null pins and a comment, like Project 2's.
- Extend the hygiene test to the Power BI descriptions (live, with a static TMDL fallback).

### 9.2 Makefile targets

```text
make p3-setup        # uv sync --group project3, then setup_adomd.py
make p3-export       # export the dbt star schema to data/powerbi/
make p3-set-path     # write the absolute data folder into the TMDL parameter
make p3-refresh      # only if P3-1 found a scripted refresh
make p3-static-test  # TMDL checks + compiler tests (any OS, no Desktop)
make p3-layer-test   # live: contract + layer correctness for powerbi
make p3-parity       # live: powerbi vs metricflow on the layer queries
make p3-traps        # live: the traps table
```

Every target is a thin `uv run ...` wrapper.

### 9.3 Report page (manual, for the screen recording)

PBIR report files are tedious to write by hand. Don't spend more than a short attempt on that. Instead, document a three-visual page I can build in Desktop in a few minutes:

- `items_sold` by month by `category`, showing the Sweaters/Knitwear break
- the same by `category_family`, showing a continuous line
- `attribution_coverage_rate` by signup month

### 9.4 Case study README (`project3-powerbi-tmdl/README.md`)

Same structure and tone as Project 2's README: plain language, short sentences, no hype, and no claims beyond what was measured.

1. **The question:** the same thesis, applied to Power BI, and why its semantic model deserves its own test.
2. **Same benchmark, third stack:** a comparison table with Projects 1 and 2. Make it clear the tables are Project 2's star schema, reused on purpose so the semantic layer is the only variable.
3. **Architecture** (Mermaid): dbt star → Parquet → Power BI import → TMDL model → DAX backend → agent interface, with truth independent on the side.
4. **Model as code:** what TMDL in git gives you (diffs, review, tests) and what still needs Desktop.
5. **Model design:** role-playing date tables, single-direction relationships, the measure table, base measures, `customer_cohort_month` from one source, the model settings. Include a Mermaid diagram of the relationships.
6. **How each planted problem is handled**, in the same table format as Projects 1 and 2.
7. **Governance in Power BI:** what the static tests guarantee, the internal-exclusion convention and its graph-walk test, and what none of it proves (correctness needs truth).
8. **Results: what was measured:** layer correctness (checks, max deviation, compared with Cube and MetricFlow), three-engine parity, row counts.
9. **Power BI traps:** the table from P3-5, with one sentence per trap on why it happens.
10. **Agent evaluation:** see 10.1 for how to write this section.
11. **Three stacks, same benchmark:** five or six honest bullets. These come from building the layer a third time; they are not agent findings.
12. **Engineering findings:** symptom and fix, as in Projects 1 and 2. Collect them in CLAUDE.md as you go.
13. **Honest limitations:**
    - Windows and Desktop only
    - an import snapshot, not DirectQuery
    - no Power BI service or Fabric behaviour tested
    - P3 is unrecoverable by design
    - the Project 1 description leak
14. **Privacy:** everything runs locally on Windows; no data leaves the machine; the data is synthetic.
15. **Reproduce it:** the make targets in order, including the manual Desktop steps.
16. **Screen-recording checklist:**
    - `make p3-static-test`
    - opening the PBIP
    - the measure descriptions in Desktop
    - `make p3-layer-test` deviation summary
    - `make p3-traps`
    - the three-visual report page
    - one compiled DAX query next to its semantic query

Also update:

- **root `README.md`:** project table status, a Layout entry, and glossary entries for PBIP, TMDL, DAX, measure, base measure, role-playing date table, cross-filter direction, implicit measure, the local Analysis Services engine and Power BI trap
- **CLAUDE.md:** Project 3 status and findings

**Stop for my review of the README draft.**

---

## 10. Agent evaluation: scope and how the README states it

No agent eval runs are part of Project 3. The README must still explain the agent side clearly and honestly.

### 10.1 What the README section must contain

- **What is in place:**
  - the `powerbi` backend is registered in the shared runner
  - it serves the same metric contract
  - the LLM would never write DAX: the backend compiles it
  - the same 20 questions, scorers and judge apply
- **The command that would run it:** `make eval BACKEND=powerbi PROVIDER=anthropic`.
- **Why this case study is scoped to the layer.** The agent harness is the same for every stack, and its behaviour on a governed layer is measured in case study 01. What is specific to Power BI is the model: relationships, DAX and model settings. That is where this study puts its tests. A layer that can't be shown correct against truth isn't ready for an agent, whatever the agent's score.
- **One plain sentence stating that no agent runs were made for this stack**, so the page contains no agent pass rates. Write it as a scope statement.
- **Don't mention cost** as the reason.
- **Don't write anything that implies agent results exist** for Power BI: no "the agent performed well", no invented smoke-test answers.

### 10.2 What not to do

- Don't run `make eval` or any smoke test that calls an LLM. Even a one-question smoke test is out of scope for this project.
- Don't put placeholder numbers anywhere.

---

## 11. Milestone summary (stop after each)

| Milestone | Delivers | Stop for |
|---|---|---|
| P3-1 | Spike: PBIP/TMDL, Parquet import, port discovery, DAX from Python, self-description, refresh | The environment decision |
| P3-2 | Export, model skeleton, static tests, row-count parity | Row counts and model settings |
| P3-3 | 18 catalog measures, base measures, static contract test | Measure design and the two checks in 7.1 |
| P3-4 | DAX compiler, backend, live contract, shared layer tests, three-engine parity | Layer correctness and parity |
| P3-5 | Power BI traps suite | The traps table |
| P3-6 | Wiring, report-page recipe, README, root README and CLAUDE.md | README review |

---

## 12. Acceptance criteria (whole project)

- `git diff project2-final` shows no change to any frozen path.
- `make p3-export` is deterministic, with identical manifests across runs.
- These pass:
  - `make p3-static-test` on any OS, without Desktop
  - `make p3-layer-test` with Desktop open: the contract, plus all 41 layer checks within 0.5% of truth, with the documented `attribution_coverage_rate` exception
- `make p3-parity` reports the maximum difference between Power BI and MetricFlow.
- `make p3-traps` produces the traps table, with every claimed catcher demonstrated.
- `make test` and `make lint` pass. Live tests skip cleanly without Desktop or Cube.
- No LLM was called during Project 3, and `config/runs.yaml` project3 pins are null.
- No Microsoft DLLs, machine-specific paths or secrets are in git.

---

## 13. Questions to raise with me, not decide alone

- Any change to a frozen path.
- A DAX or Power BI limitation that would force a definition to differ from the catalog, Cube or MetricFlow. Report it with a proposed workaround and its effect on comparability.
- `pythonnet` not working, or ADOMD.NET needing anything beyond a NuGet download.
- PBIP/TMDL needing a preview feature or a Desktop version I don't have.
- A trap in section 8 that doesn't move the number on this data.
- Layer results that look too good or too bad compared with Cube and MetricFlow. Check the export and the relationships before believing them.
