# Klarix Semantic AI Benchmark

Three semantic-layer stacks answer the same business questions through an LLM agent.

| Project | Stack | LLM | Status |
|---|---|---|---|
| [1](project1-gcp-cube/) | BigQuery + Cube Core | Gemini on Vertex AI | in progress |
| [2](project2-dbt-metricflow/) | dbt Core + MetricFlow on DuckDB | Claude | planned |
| [3](project3-powerbi-tmdl/) | Power BI Desktop, PBIP/TMDL | Claude | planned |

**Thesis:** a semantic layer makes metric answers *consistent*, but not necessarily *correct*. The
layer is only as correct as the judgment encoded into it. The benchmark measures where stack +
agent gets it right, where it's confidently wrong, and where it asks the right question.

**Data:** a frozen snapshot of Google's public `thelook_ecommerce` dataset (a fictitious clothing
store), with planted problems injected into a copy. Ground truth is computed independently from
the clean version.

**Naming:** the GCP project *Klarix* hosts several portfolio projects. This benchmark's BigQuery
datasets are prefixed with the domain slug `apparel_ecom` (e.g. `apparel_ecom_star`).

## Quick start

```sh
make setup                              # uv sync (Python 3.12)
cp .env.example .env                    # then fill it in
make gcp-check                          # after project1-gcp-cube/gcp/SETUP.md
```

`make` on Windows: `winget install ezwinports.make`, or run the `uv run ...` line from the
`Makefile` directly.

## Layout

```text
config/settings.yaml   seed, benchmark dates, model IDs, token prices
shared/                snapshot, worlds + truth, semantic contract, agent, evals (shared by all stacks)
project1-gcp-cube/     BigQuery star schema + Cube Core
```
