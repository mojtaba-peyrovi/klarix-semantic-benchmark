# GCP setup (Project 1)

Manual, one-time steps. Commands work in PowerShell and bash; replace `<PROJECT_ID>` and
`<BILLING_ACCOUNT_ID>` with your own values. When you're done, run `make gcp-check`.

## 1. Project and billing

Use a dedicated project with billing enabled. **Do not use the BigQuery Sandbox**: its tables
expire after 60 days.

```sh
# Project IDs are global. Try "klarix" first; if it's taken, use e.g. "klarix-benchmark".
gcloud projects create <PROJECT_ID> --name="Klarix"
gcloud billing accounts list
gcloud billing projects link <PROJECT_ID> --billing-account=<BILLING_ACCOUNT_ID>
gcloud config set project <PROJECT_ID>
```

## 2. Enable APIs

```sh
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com serviceusage.googleapis.com --project=<PROJECT_ID>
```

`serviceusage` lets `make gcp-check` read back the quota you set in step 3.

## 3. Cost guardrails

### Budget alerts (€5 / €10 / €20)

Budgets **only send alerts. They do not cap spending.** The quota below is the hard cap.

Console: *Billing → Budgets & alerts → Create budget*. Scope it to this project, set the amount to
€20, and add threshold rules at 25% (€5), 50% (€10), and 100% (€20). The same thing from the CLI
(the currency must match your billing account's currency):

```sh
gcloud billing budgets create --billing-account=<BILLING_ACCOUNT_ID> --display-name="klarix-benchmark" --budget-amount=20EUR --filter-projects=projects/<PROJECT_ID> --threshold-rule=percent=0.25 --threshold-rule=percent=0.5 --threshold-rule=percent=1.0
```

### Hard cap: 10 GB per day of BigQuery query bytes

Console: *IAM & Admin → Quotas & system limits*. Filter for **Query usage per day** (service
BigQuery API), select the project-level row, choose *Edit quota*, and set it to 10 GiB. Check the
unit shown in the dialog: if it's MiB, enter `10240`. Queries that would exceed the cap fail
instead of billing.

Every job the code runs also sets `maximum_bytes_billed` (`config/settings.yaml`), so one bad query
can't use up the day's quota.

## 4. BigQuery datasets (all in `EU`)

```sh
bq --location=EU mk --dataset --description="Observed tables loaded from Parquet" <PROJECT_ID>:klarix_raw
bq --location=EU mk --dataset --description="Staging views" <PROJECT_ID>:klarix_staging
bq --location=EU mk --dataset --description="Kimball star schema" <PROJECT_ID>:klarix_star
bq --location=EU mk --dataset --description="Governed marts" <PROJECT_ID>:klarix_marts
```

If you change the location, set `BQ_LOCATION` in `.env` to match. All four datasets must share one
location.

## 5. Local dev auth (your user)

```sh
gcloud auth application-default login
gcloud auth application-default set-quota-project <PROJECT_ID>
```

You need **BigQuery Data Editor**, **BigQuery Job User**, and **Vertex AI User**. As the project's
creator you're already Owner, which includes all three. Otherwise, grant them:

```sh
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="user:<YOUR_EMAIL>" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="user:<YOUR_EMAIL>" --role="roles/bigquery.jobUser"
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="user:<YOUR_EMAIL>" --role="roles/aiplatform.user"
```

## 6. Service account for Cube

Read-only: Cube can query the data but can't change it.

```sh
gcloud iam service-accounts create cube-reader --display-name="Cube Core (read-only)" --project=<PROJECT_ID>
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="serviceAccount:cube-reader@<PROJECT_ID>.iam.gserviceaccount.com" --role="roles/bigquery.dataViewer"
gcloud projects add-iam-policy-binding <PROJECT_ID> --member="serviceAccount:cube-reader@<PROJECT_ID>.iam.gserviceaccount.com" --role="roles/bigquery.jobUser"
```

Create the key **outside the repo**. For example, on Windows:

```sh
mkdir $HOME\.gcp
gcloud iam service-accounts keys create $HOME\.gcp\klarix-cube-reader.json --iam-account=cube-reader@<PROJECT_ID>.iam.gserviceaccount.com
```

Set `CUBE_SA_KEY_PATH` in `.env` to that absolute path. Milestone 7 mounts the key read-only into
the Cube container. Never commit it; `make gcp-check` fails if the key is inside the repo.

## 7. Fill in `.env`

```sh
cp .env.example .env
```

Set `GCP_PROJECT_ID` and `CUBE_SA_KEY_PATH`. Leave `VERTEX_LOCATION=eu` (see step 8).

## 8. Why the locations are what they are

- **BigQuery `EU`.** `bigquery-public-data.thelook_ecommerce` lives in the US, and BigQuery can't
  run a cross-region `CREATE TABLE AS SELECT` into an EU dataset. So Milestone 2 pulls the snapshot
  to local Parquet first and loads it into `EU` from there. That also gives Projects 2 and 3 a
  frozen, portable source.
- **Vertex AI `eu`.** `gemini-3.8-flash` isn't documented for the `europe-west4` single-region
  endpoint. It's served from the EU multi-region endpoint, which keeps data residency and ML
  processing inside the EU. `make gcp-check` makes one tiny call to confirm the model answers
  there.

## 9. Verify

```sh
make gcp-check
```

Everything should be PASS. The Anthropic key and the Cube key show WARN until you add them; the
milestones that need them are 6 and 7.
