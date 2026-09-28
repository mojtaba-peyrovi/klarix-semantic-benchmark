# Klarix Semantic AI Benchmark: Foundation + Project 1 (GCP)

Development plan for Claude Code. It **replaces** the earlier "Step 1 shared foundation" plan (synthetic SaaS). Read fully before writing code. Work milestone by milestone and stop after each one for review.

---

## 1. Context and goal

This repo is the portfolio centerpiece for Klarix (klarix.consulting), a data, BI, and applied AI consultancy.

The portfolio compares three semantic-layer stacks answering the same business questions through an LLM agent:

| Project | Stack | LLM | Status |
|---|---|---|---|
| 1 | BigQuery + Cube Core | Gemini on Vertex AI | **this plan** |
| 2 | dbt Core + MetricFlow on DuckDB | Claude | later |
| 3 | Power BI Desktop, PBIP/TMDL | Claude | later |

**Thesis:** a semantic layer makes metric answers consistent, but not necessarily correct. The layer is only as correct as the judgment encoded into it. The benchmark measures where stack + agent gets it right, where it is confidently wrong, and where it asks the right question.

**Data:** a frozen snapshot of Google's public `bigquery-public-data.thelook_ecommerce` dataset, a fictitious clothing e-commerce site. We inject planted problems into a copy and compute ground truth from the clean version.

**This plan builds:**
1. The shared foundation: snapshot, planted problems, ground truth, metric catalog, semantic query contract, agent loop, evals.
2. Project 1:
   - GCP setup
   - BigQuery staging and **star schema**
   - governed marts
   - Cube Core model
   - Cube backend adapter
   - Gemini agent runs
   - eval report

**Out of scope:** dbt, TMDL, any UI, the Klarix website.

---

## 2. Hard constraints

- **No LangChain, LangGraph, LlamaIndex, or other agent frameworks.** Use official SDKs (`google-genai`, `anthropic`) with a small hand-written tool-calling loop.
- **Gemini via Vertex AI** (`google-genai` with `vertexai=True`), in an EU region. Do not use the deprecated `google.generativeai` package.
- **Do not hardcode model IDs from memory.** Check current Google and Anthropic docs, pick current stable models, and confirm the Gemini model is available in the chosen EU region. Put the IDs in config and tell me what you chose.
- **The LLM never writes SQL.** It only produces structured semantic queries (section 8). Backends compile them.
- **Ground truth is never computed from observed (corrupted) tables or through BigQuery/Cube.** It is computed locally with DuckDB on the clean "true" Parquet files, with independent code.
- Deterministic: same seed, same outputs (file hashes recorded).
- Python 3.12, `uv`, `ruff`, `pytest`, `pydantic` v2, type hints everywhere.
- **Allowed dependencies:** numpy, pandas, pyarrow, duckdb, pydantic, pyyaml, python-dotenv, typer, rich, httpx, pyjwt, google-cloud-bigquery, db-dtypes, google-genai, anthropic, pytest. Ask before adding anything else.
- Secrets and credentials only via `.env` and Application Default Credentials. Never commit keys or service-account JSON.
- Keep modules small and readable. Hiring managers and tech leads will read this code.

---

## 3. Repository structure

```text
klarix-semantic-benchmark/
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example                   # GCP_PROJECT_ID, BQ_LOCATION, VERTEX_LOCATION, ANTHROPIC_API_KEY, CUBEJS_API_SECRET
├── .gitignore                     # data/, runs/, .env, *.json credentials
├── config/
│   └── settings.yaml              # seed, benchmark dates, planted-problem params, model IDs, token prices
├── shared/
│   ├── snapshot/
│   │   ├── pull.py                # public dataset -> local Parquet (frozen)
│   │   └── profile.py             # data profile report
│   ├── world/
│   │   ├── real_signal.py         # P5: modifies the TRUE world
│   │   ├── observe.py             # P2, P3, P4: produces OBSERVED tables
│   │   └── truth.py               # truth tables + answers.json from TRUE world (DuckDB)
│   ├── semantic/
│   │   ├── catalog.yaml           # canonical metrics + dimensions (contract for all 3 stacks)
│   │   ├── catalog.py
│   │   └── query.py               # SemanticQuery / SemanticResult
│   ├── backends/
│   │   ├── base.py
│   │   └── naive_bigquery.py      # baseline: LLM-style queries on raw observed tables
│   ├── agent/
│   │   ├── loop.py
│   │   ├── tools.py
│   │   ├── prompts.py
│   │   └── providers/
│   │       ├── base.py
│   │       ├── gemini_vertex.py
│   │       └── anthropic_provider.py
│   └── evals/
│       ├── golden_questions.yaml
│       ├── scorers.py
│       ├── judge.py
│       ├── runner.py
│       └── report.py
├── project1-gcp-cube/
│   ├── README.md                  # case study (milestone 10)
│   ├── gcp/
│   │   └── SETUP.md               # manual GCP steps for me
│   ├── bigquery/
│   │   ├── load.py                # observed Parquet -> apparel_ecom_raw
│   │   ├── apply_sql.py           # runs sql/ in order
│   │   └── sql/
│   │       ├── 10_staging/*.sql
│   │       ├── 20_star/*.sql
│   │       ├── 30_marts/*.sql
│   │       └── 90_tests/*.sql     # assertion queries (must return 0 rows)
│   ├── cube/
│   │   ├── docker-compose.yml
│   │   └── model/
│   │       ├── cubes/*.yml
│   │       └── views/*.yml
│   └── backend/
│       └── cube_backend.py
├── project2-dbt-metricflow/README.md     # placeholder
├── project3-powerbi-tmdl/README.md       # placeholder
├── data/                          # gitignored: snapshot/, true/, observed/, truth/
├── runs/                          # gitignored: eval outputs
└── tests/
```

---

## 4. GCP setup (Milestone 1, documented in `gcp/SETUP.md`)

Write clear manual steps for me, plus a verification script (`make gcp-check`).

1. **Project and billing.** Use a dedicated GCP project with billing enabled. Do **not** use the BigQuery Sandbox: its tables expire after 60 days.
2. **Cost guardrails.**
   - A budget with alerts at €5 / €10 / €20. Note in the doc that budgets only alert and do not cap spending.
   - A custom BigQuery query quota of 10 GB per day per project as the hard cap.
3. **APIs:** BigQuery and Vertex AI.
4. **Datasets:** all in one EU location (default `EU` multi-region, configurable):
   - `apparel_ecom_raw`: observed tables, loaded from Parquet
   - `apparel_ecom_staging`: views
   - `apparel_ecom_star`: tables
   - `apparel_ecom_marts`: tables and views
5. **Service account for Cube** with BigQuery Data Viewer + BigQuery Job User on the project. Key JSON stored outside the repo and mounted into Docker.
6. **Local dev auth** via `gcloud auth application-default login`. My user needs BigQuery Data Editor, BigQuery Job User, and Vertex AI User.
7. **Location note.** `bigquery-public-data` lives in the US. Cross-region `CREATE TABLE AS SELECT` into an EU dataset does not work. That's why the snapshot goes to local Parquet first (section 5), which also gives us a frozen, portable source for Projects 2 and 3.

---

## 5. Snapshot and profiling (Milestone 2)

### 5.1 Pull

`shared/snapshot/pull.py` reads the seven theLook tables from `bigquery-public-data.thelook_ecommerce`:
- users
- products
- orders
- order_items
- inventory_items
- distribution_centers
- events

It writes them to `data/snapshot/*.parquet` and records the pull timestamp, row counts, and file hashes in `data/snapshot/manifest.json`.

- The dataset is regenerated regularly upstream, so this snapshot is the permanent source. Never re-query the public dataset after this milestone unless I ask.
- `events` is the largest table. Select only the needed columns so the bytes scanned stay small.
- Print bytes processed per query.

### 5.2 Profile

`shared/snapshot/profile.py` writes `data/snapshot/PROFILE.md` covering:

- **Row counts, date range, and null rates** per table and column.
- **Distinct values** for: order and order_item status, users.traffic_source, events.traffic_source, events.event_type, products.category, products.department, the top brands, and countries.
- **Timestamps:** any in the future relative to the pull date, and monthly volume per table (to spot partial months).
- **Key integrity:**
  - order_items → orders / products / users
  - orders → users
  - events → users (the nullable share)
- **Money checks:** returned and cancelled item share, both by count and by revenue.

### 5.3 Stop and propose

After profiling, stop. Propose to me:
- a **benchmark end date** (the last complete month; everything after it is dropped)
- a 24-month analysis window
- calibrated parameters for P2 to P5, using real category, source, and brand names from the profile

Do not continue until I confirm.

---

## 6. True world, observed world, truth (Milestone 3)

### 6.1 Pipeline

```text
snapshot (clipped to window)
   └─► real_signal.py (P5)  ─► data/true/*.parquet       # the TRUE business
            └─► observe.py (P2, P3, P4) ─► data/observed/*.parquet   # what the warehouse sees
truth.py reads data/true/ only ─► data/truth/*.parquet + answers.json
```

### 6.2 Planted problems

The parameters below are defaults. Replace names and dates with the calibrated values I confirm in 5.3.

**P1: Gross vs net revenue (definition trap, natural).**
- No injection is needed: theLook contains cancelled and returned items.
- Truth provides `gross_revenue` and `net_revenue` separately (definitions in section 7).
- **Test:** returned plus cancelled revenue is at least 10% of gross in the window. If it's lower, tell me.

**P2: Category rename (artifact).**
- On a date about 12 months before the benchmark end, one mid-sized category is renamed (e.g. "Outerwear & Coats" → "Jackets & Coats").
- Implementation in `observe.py`: duplicate every product in that category with a new product_id and the new category name. Order items created on or after the rename date point to the new product_ids. Old products stay as they are.
- `products` has no validity columns, as in many real warehouses.
- **Truth:** `category_family_map` (old name, new name → one family).
- **Test:** the observed old-category item count drops by more than 95% in the rename month, while the truth family count changes by less than 15% month over month.

**P3: Consent tracking loss (artifact).**
- From a consent date about 6 months before the end, 30% of users created on or after that date get `traffic_source = NULL`. The same applies to 30% of sessions in `events`, selected randomly and independently of the true source.
- **Truth:** `true_user_source` and `true_session_source`.
- **Test:** the observed share of the top paid source drops by more than 20% relative after the consent date; the true share stays within ±5%.

**P4: Internal and test users (hygiene).**
- Inject about 150 users with test-like names (e.g. "Test", "QA", "Demo"), emails on an internal domain (e.g. `@thelook-internal.com`), and a single country.
- Each gets 5 to 30 orders of 1 to 3 items with sale_price 0.01 to 1.00, all status Complete, spread over the window. Some also get sessions in `events`.
- **Truth:** `internal_user_ids`; all truth metrics exclude them.
- **Test:** injected users raise the observed repeat-purchase rate by at least 2 points and lower observed AOV measurably.

**P5: High-return acquisition cohort (real signal, applied to the TRUE world).**
- For users whose traffic_source is one chosen source (e.g. "Facebook") and who were created in a 3-month window about 15 months before the end, raise the item return rate to about 40%.
- Mechanics: flip status to Returned and set returned_at 5 to 20 days after delivered_at, applied to delivered items only.
- Compare against the baseline return rate from the profile.
- **Effect:** that source looks fine on gross revenue and orders but bad on net revenue and margin.
- **Truth:** `cohort_returns` by signup month × source, and `net_margin_by_source`.
- **Test:** the P5 cohort's return rate is at least 20 points above other cohorts of the same source.

### 6.3 Truth outputs

`truth.py` uses DuckDB on `data/true/` with the canonical definitions from section 7, written independently of the BigQuery SQL. It produces:
- a truth table per metric and grain as needed
- `answers.json`, keyed by `truth_ref` (section 11)
- `manifest.json` with the seed and hashes

---

## 7. Canonical metric catalog (Milestone 4)

`shared/semantic/catalog.yaml` is the contract that Cube (and later dbt and TMDL) must implement exactly. Each entry has: name, description (written for the agent: what it means, what it excludes, common confusions), unit, default time dimension.

### 7.1 Metrics

All metrics exclude internal users unless stated.

| Metric | Definition |
|---|---|
| `gross_revenue` | Sum of sale_price of order items not cancelled (includes items later returned) |
| `returned_revenue` | Sum of sale_price of returned items |
| `net_revenue` | gross_revenue minus returned_revenue |
| `cogs` | Cost (products.cost) of net (non-cancelled, non-returned) items |
| `gross_margin` | net_revenue minus cogs |
| `gross_margin_pct` | gross_margin / net_revenue |
| `orders` | Distinct orders with at least one non-cancelled item |
| `aov` | net_revenue / orders |
| `items_sold` | Non-cancelled items |
| `return_rate` | Returned items / non-cancelled items (item-based; description must mention the revenue-based alternative) |
| `cancellation_rate` | Cancelled items / all items |
| `purchasing_customers` | Distinct users with at least one order in the period |
| `new_customers` | Users whose first order falls in the period |
| `repeat_purchase_rate_90d` | Share of a first-order cohort that ordered again within 90 days |
| `signups` | Users created in the period |
| `sessions` | Distinct session_id in events |
| `session_conversion_rate` | Sessions with a purchase event / sessions |
| `attribution_coverage_rate` | Share of users (or sessions) with a known traffic_source. **Governed stack only; this is the "layer exposes its own blind spot" metric** |

### 7.2 Dimensions

- **Time:** order_created (day, week, month, quarter, year), user_created, session_started
- **Product:** category, category_family, brand, department
- **Customer:** customer_country, customer_age_band, customer_gender, acquisition_channel (users.traffic_source, with NULL shown as "Unattributed"), customer_cohort_month
- **Session:** session_traffic_source
- **Other:** distribution_center, item_status

---

## 8. Semantic query contract (Milestone 4)

`shared/semantic/query.py`:

```python
class Filter(BaseModel):
    dimension: str
    op: Literal["eq", "neq", "in", "not_in", "gte", "lte"]
    value: str | float | list[str] | list[float]

class TimeRange(BaseModel):
    start: date
    end: date            # inclusive

class SemanticQuery(BaseModel):
    metrics: list[str]                 # >= 1, validated against catalog
    dimensions: list[str] = []
    time_dimension: str | None = None  # e.g. "order_created"
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    time_range: TimeRange | None = None
    filters: list[Filter] = []
    order_by: list[tuple[str, Literal["asc", "desc"]]] = []
    limit: int | None = None

class SemanticResult(BaseModel):
    columns: list[str]
    rows: list[list]
    compiled_query: str                # SQL or Cube JSON, for transparency
    backend: str
    latency_ms: int
    warnings: list[str] = []
```

Validate names against the catalog before calling a backend. Return readable errors so the agent can self-correct.

---

## 9. BigQuery modeling: staging, star schema, marts (Milestone 5)

`bigquery/load.py` loads `data/observed/*.parquet` into `apparel_ecom_raw` (write-truncate). `apply_sql.py` executes the numbered SQL folders in order, idempotently (`CREATE OR REPLACE`), and prints bytes processed per statement.

### 9.1 Staging (`10_staging`, views in `apparel_ecom_staging`)

One view per raw table:
- snake_case names and typed columns
- timestamps kept as TIMESTAMP, plus DATE columns derived for convenience
- no business logic

### 9.2 Star schema (`20_star`, tables in `apparel_ecom_star`)

This is the core modeling work and the backbone of the case study. Follow Kimball conventions:
- surrogate keys: `FARM_FINGERPRINT` of the natural key, cast to INT64
- an unknown member row (key -1) in every dimension
- documented grain at the top of every file

**Dimensions**

| Table | Grain | Key columns / attributes |
|---|---|---|
| `dim_date` | one row per day, covering the full window | date_key (YYYYMMDD int), date, week_start, month, quarter, year, day_of_week, is_weekend |
| `dim_customer` | one row per user | customer_key, user_id, gender, age, age_band, country, state, city, acquisition_channel (NULL → "Unattributed"), created_date_key, customer_cohort_month (first order month), is_internal (rule-based: internal email domain or test-name patterns; document the rule) |
| `dim_product` | one row per product_id | product_key, product_id, name, brand, category, category_family (from a governed mapping table `apparel_ecom_star.map_category_family`, seeded from a SQL VALUES list), department, retail_price, cost, distribution_center_name |
| `dim_distribution_center` | one row per center | center key and attributes |

**Facts**

| Table | Grain | Contents |
|---|---|---|
| `fct_order_items` | one row per order item | order_item_id, order_id, customer_key, product_key, created/shipped/delivered/returned date keys, item_status, is_cancelled, is_returned, sale_price, cost, net_sale_price (0 if cancelled or returned), net_cost |
| `fct_orders` | one row per order | order_id, customer_key, order_date_key, status, item_count, gross_revenue, net_revenue, is_first_order, order_sequence_number |
| `fct_sessions` | one row per session_id (from events) | session_key, customer_key (unknown if anonymous), session_start_ts, session_date_key, session_traffic_source (NULL → "Unattributed"), event_count, has_purchase |

**Design notes to document in the SQL headers**
- `category_family` fixes P2 by design.
- `is_internal` fixes P4 by design.
- "Unattributed" makes P3 visible rather than hiding it; it cannot be fixed.
- P1 is handled by separate gross and net columns.

### 9.3 Marts (`30_marts`, `apparel_ecom_marts`)

- `mart_customer_cohorts`: one row per customer with cohort month, acquisition channel, first order date, whether they repeated within 90 days, lifetime gross and net revenue, return rate. Supports P5 and repeat-purchase questions.
- Additional marts only if Cube needs them. Prefer Cube measures over marts.

### 9.4 SQL tests (`90_tests`)

Each file is an assertion query that must return 0 rows. `make bq-test` runs all of them and fails on any row returned.
- primary key uniqueness for every dim and fact
- no orphan foreign keys (all resolve to a dim row or the unknown member)
- `fct_order_items` row count equals the raw order_items count
- gross revenue in `fct_order_items` reconciles to raw order_items within 0.01
- every category in `dim_product` has a `category_family`

---

## 10. Cube Core (Milestone 7)

### 10.1 Runtime

`cube/docker-compose.yml` runs the official Cube image with:
- the BigQuery driver (`CUBEJS_DB_TYPE=bigquery`, project ID, dataset location, service-account key mounted read-only)
- `CUBEJS_API_SECRET` from `.env`
- dev mode on locally
- the model folder mounted

Check the current Cube docs for exact env var names and the image tag, and pin the tag.

### 10.2 Model

**Cubes** (`model/cubes/*.yml`): one per star table (`order_items`, `orders`, `customers`, `products`, `dates`, `sessions`, `customer_cohorts`), with:
- joins declared from facts to dims (many_to_one)
- every catalog metric as a measure with exactly the catalog definition; ratio metrics as `type: number` built from base measures
- every measure and dimension with a `description` written for an LLM reader: what it includes and excludes, and common confusions (e.g. gross vs net)
- a default exclusion of internal users on all governed measures (via a `filters` clause on the measures or a `segments` entry, as documented in Cube)
- the `attribution_coverage_rate` measure

**Views** (`model/views/*.yml`):
- One agent-facing view, e.g. `commerce`, exposing only catalog metrics and dimensions under catalog names.
- Raw cubes are hidden from the agent: `public: false` on cubes.
- The member names in the view must match `catalog.yaml` exactly.

### 10.3 Adapter (`backend/cube_backend.py`)

- **Auth:** HS256 JWT signed with `CUBEJS_API_SECRET` (pyjwt), short expiry.
- **Endpoints:**
  - `list_metrics` / `list_dimensions` from `GET /cubejs-api/v1/meta`, filtered to the agent-facing view
  - `run` via `POST /cubejs-api/v1/load`
  - the generated SQL via `/cubejs-api/v1/sql`, stored in `compiled_query` next to the Cube JSON
- **Handle Cube's "Continue wait"** response by polling with backoff and a timeout.
- **Mapping:**

  | SemanticQuery | Cube |
  |---|---|
  | metrics | `measures` |
  | dimensions | `dimensions` |
  | time_dimension + grain + range | `timeDimensions` with `granularity` and `dateRange` |
  | eq / neq / in / not_in | `equals` / `notEquals` (multi-value lists for in / not_in) |
  | gte / lte on numbers | `gte` / `lte` |
  | gte / lte on time | `afterOrOnDate` / `beforeOrOnDate` (check current Cube docs) |
  | order_by, limit | `order`, `limit` |

**Tests:**
- **Contract test:** Cube meta for the view equals the `catalog.yaml` metric and dimension names.
- **Layer correctness test (deterministic, no LLM):** for a fixed set of about 15 queries covering every metric, Cube results match `data/truth` within tolerance. Expected exceptions: anything depending on true channel for Unattributed users (P3 is unrecoverable by design). List the expected exceptions explicitly in the test.
  - This separates "is the layer correct?" from "is the agent correct?", which is a key finding for the README.

---

## 11. Agent and baseline (Milestone 6)

### 11.1 Backend interface (`shared/backends/base.py`)

```python
class Backend(ABC):
    name: str
    def list_metrics(self) -> list[MetricInfo]: ...
    def list_dimensions(self) -> list[DimensionInfo]: ...
    def run(self, query: SemanticQuery) -> SemanticResult: ...
```

### 11.2 Naive baseline (`naive_bigquery.py`)

It answers every catalog metric with the definitions a hurried analyst would write directly on `apparel_ecom_raw`:
- "revenue" = sum of all sale_price
- category = products.category
- channel = users.traffic_source, with NULL shown as NULL
- no internal exclusion
- no `attribution_coverage_rate` (report it as unavailable)

The module docstring states clearly that this represents "LLM on raw tables, no governed semantic layer."

### 11.3 Tools

- `list_metrics()`
- `list_dimensions()`
- `run_semantic_query(query)`
- `ask_clarification(question, options)`: terminal.
- `final_answer(answer, key_numbers[{label, value, unit}], assumptions[], caveats[], confidence)`: terminal.

### 11.4 Loop

- Max 8 tool calls, then force `final_answer`.
- Temperature 0.
- Any provider × any backend.
- Returns an `AgentRun`: output, turns, tool calls and results, tokens, estimated cost, latency.
- Everything is serializable to JSON (the replay UI will use it later).

### 11.5 System prompt

- Role: analyst for theLook leadership, using the tools only.
- State definitions and assumptions.
- Ask for clarification when a question is genuinely ambiguous.
- Flag anything that looks like a data artifact rather than a business change.
- Include the benchmark date for resolving "last month" or "this quarter".
- Identical across providers and backends.
- **Never mention or hint at the planted problems.**

### 11.6 Providers

- `gemini_vertex.py`: `google-genai` with `vertexai=True`, project and location from env, native function calling.
- `anthropic_provider.py`: Messages API tool use. Used for the judge and the control run.
- Both retry on rate limits with backoff.

---

## 12. Evals (Milestones 8 and 9)

### 12.1 Golden questions (`golden_questions.yaml`)

Format:

```yaml
- id: Q10
  category: trap          # straightforward | definition | trap | ambiguous | insight
  planted_problem: P2
  paraphrases: ["...", "...", "..."]
  expected:
    kind: insight         # numeric | table | clarification | insight
    truth_ref: category_family_trend_12m
    tolerance_pct: 2.0
  rubric: "Pass only if ..."
```

Write 3 paraphrases each. Fill concrete names and dates from the calibrated parameters; relative phrases resolve against the benchmark date.

| ID | Category | Question | Problem |
|---|---|---|---|
| Q01 | straightforward | How many orders did we have last month? | |
| Q02 | straightforward | What was net revenue last month? | |
| Q03 | straightforward | Top 5 brands by net revenue in the last 12 months | |
| Q04 | straightforward | Which country has the most purchasing customers? | P4 minor |
| Q05 | straightforward | Monthly signups for the last 6 months | P4 minor |
| Q06 | definition | What was revenue last quarter? | P1 |
| Q07 | definition | What is our average order value? | P1, P4 |
| Q08 | definition | What is our return rate? | |
| Q09 | definition | What is our conversion rate? | |
| Q10 | trap | How has [renamed category] performed over the last 12 months? | P2 |
| Q11 | trap | Which category declined the most in [rename month]? | P2 |
| Q12 | trap | Is [top paid source] acquisition declining since [consent month]? | P3 |
| Q13 | trap | Which channel brought the most new customers last quarter? | P3 |
| Q14 | trap | What share of new customers buy again within 90 days? | P4 |
| Q15 | ambiguous | How are we doing? | |
| Q16 | ambiguous | What is our margin? | |
| Q17 | ambiguous | Compare this month to last. | |
| Q18 | insight | Which acquisition channel is most profitable after returns? | P5 |
| Q19 | insight | Why did net margin weaken in [P5 impact period]? | P5 |
| Q20 | insight | Which customer cohort has the worst return behavior? | P5 |

### 12.2 Scorers

- **numeric:** expected numbers matched to `key_numbers` within tolerance.
- **consistency:** key numbers agree across paraphrases.
- **clarification:** pass if `ask_clarification` was called; for Q17, explicit assumptions also pass.
- **rubric:** LLM judge.
- **cost and latency:** recorded.

### 12.3 Judge

- One fixed Claude model for all runs, temperature 0.
- Output: JSON `{pass, reason}`.
- Cached by input hash.

### 12.4 Runner and report

- **CLI:** `uv run python -m shared.evals.runner --backend cube --provider gemini --questions all --repeats 1`
- **Output:** `runs/<timestamp>_<backend>_<provider>/` with `traces.jsonl`, `scores.csv`, `report.md`.
- `report.md` contains:
  - pass rate by category and by planted problem
  - consistency rate
  - per-question table
  - tokens, cost, median latency
  - 3 example failures with answer vs truth

**Required runs for Project 1:**
1. `naive_bigquery × gemini` (baseline)
2. `cube × gemini` (headline)
3. `cube × anthropic` (control, separates model effect from layer effect)

Plus `make compare` producing `runs/COMPARISON.md` across the three.

---

## 13. Makefile targets

```text
make setup        # uv sync
make gcp-check    # verify auth, datasets, quotas reachable
make snapshot     # pull + profile (run once)
make world        # true + observed + truth
make bq-load      # observed Parquet -> apparel_ecom_raw
make bq-build     # staging -> star -> marts
make bq-test      # SQL assertions
make cube-up      # docker compose up
make cube-test    # contract + layer correctness tests
make eval BACKEND=cube PROVIDER=gemini
make compare
make test lint
```

---

## 14. Milestones (stop after each for review)

1. **Scaffold and GCP:** repo structure, config, Makefile, `SETUP.md`, `gcp-check`.
2. **Snapshot and profile:** pull, profile. **Stop and propose the benchmark date and P2 to P5 parameters.**
3. **Worlds and truth:** P5 on the true world; P2, P3, P4 in observed; truth tables, `answers.json`, planted-problem tests.
4. **Semantic contract:** `catalog.yaml`, `query.py`, validation.
5. **BigQuery modeling:** load, staging, star schema, marts, SQL tests. Report row counts and reconciliation results.
6. **Agent and baseline:** tools, loop, both providers, `naive_bigquery`. Smoke test one question on each provider.
7. **Cube:** docker, cubes, views, adapter, contract test, layer correctness test.
8. **Evals:** golden questions, scorers, judge, runner, report.
9. **Runs:** the three required runs plus the comparison.
10. **Case study draft:** `project1-gcp-cube/README.md` with:
    - architecture diagram (Mermaid)
    - star schema diagram (Mermaid ER)
    - how each planted problem is handled by design (or deliberately not)
    - eval results table
    - honest limitations
    - privacy note (below)
    - a checklist of what to screen-record

---

## 15. Acceptance criteria

- The snapshot is frozen and hashed; `make world` is deterministic.
- All planted-problem tests, SQL tests, the Cube contract test, and the layer correctness test pass (with the documented P3 exceptions).
- The three required eval runs complete, and `COMPARISON.md` is generated.
- **Expected shape:** the naive baseline fails most trap and definition questions; Cube passes most P1/P2/P4 questions by design. If results deviate strongly, report it rather than tuning prompts to fit.
- Total GCP spend for the whole milestone set stays under €10; report bytes processed and token costs.
- No secrets in git.

---

## 16. Privacy wording for the README

The agent receives schema metadata and aggregated query results only, never raw rows. Gemini runs on Vertex AI in an EU region inside the project's own GCP boundary. Vertex AI does not use customer prompts to train models; verify the current Google Cloud terms wording before publishing. The data is synthetic public data.
