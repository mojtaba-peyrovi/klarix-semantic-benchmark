# Project 3: Power BI Desktop (PBIP / TMDL)

Status: scaffolding started. The warehouse export, `powerbi` backend registration and the
machine-local `DataFolder` parameter are in place; the semantic model itself is still being built.

## What this project will prove

- The Project 2 star schema can be exported to Parquet without changing the data.
- Power BI can host the same semantic contract as TMDL text files under git.
- The model can be checked statically on any OS and queried live on Windows Desktop.

## Reproduce it

1. Run `make p3-export`.
2. Run `make p3-set-path`.
3. Open the Power BI project in Desktop once the semantic model files exist.
4. Refresh the model in Desktop.

## Current notes

- The committed `definition/expressions.tmdl` keeps a placeholder `DataFolder` value so the repo
  stays portable.
- The local `Power BI Desktop` install in this environment is the Store build `2.158.1304.0`.
- The `powerbi` backend is registered in `shared/evals/runner.py`, but the live DAX path is not
  wired yet.
