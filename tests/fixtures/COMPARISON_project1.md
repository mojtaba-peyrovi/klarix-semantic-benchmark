# Cross-run comparison

Compares the three required eval runs (DEV_PLAN section 12.4).

| Run | Directory |
|---|---|
| naive_bigquery x gemini (baseline) | `runs/20260930_114339_naive_bigquery_gemini` |
| cube x gemini (headline) | `runs/20260930_133906_cube_gemini` |
| cube x anthropic (control) | `runs/20260930_144420_cube_anthropic` |

## Overall pass rate

| Run | Pass rate |
|---|---|
| naive_bigquery x gemini (baseline) | 40% (8/20) |
| cube x gemini (headline) | 45% (9/20) |
| cube x anthropic (control) | 30% (6/20) |

## Pass rate by category

| Category | naive_bigquery x gemini (baseline) | cube x gemini (headline) | cube x anthropic (control) |
|---|---|---|---|
| ambiguous | 33% (1/3) | 33% (1/3) | 0% (0/3) |
| definition | 25% (1/4) | 25% (1/4) | 25% (1/4) |
| insight | 0% (0/3) | 33% (1/3) | 0% (0/3) |
| straightforward | 60% (3/5) | 60% (3/5) | 60% (3/5) |
| trap | 60% (3/5) | 60% (3/5) | 40% (2/5) |

## Pass rate by planted problem

| Problem | naive_bigquery x gemini (baseline) | cube x gemini (headline) | cube x anthropic (control) |
|---|---|---|---|
| P1 | 50% (1/2) | 50% (1/2) | 0% (0/2) |
| P2 | 50% (1/2) | 50% (1/2) | 0% (0/2) |
| P3 | 100% (2/2) | 100% (2/2) | 100% (2/2) |
| P4 | 60% (3/5) | 40% (2/5) | 20% (1/5) |
| P5 | 0% (0/3) | 33% (1/3) | 0% (0/3) |

## Cost, tokens, latency

| Run | Tokens in | Tokens out | Estimated cost | Median latency |
|---|---|---|---|---|
| naive_bigquery x gemini (baseline) | 8,194,043 | 88,318 | $7.0839 | 55,280ms |
| cube x gemini (headline) | 11,838,684 | 77,667 | $10.0285 | 55,258ms |
| cube x anthropic (control) | 1,998,016 | 199,047 | $14.9663 | 40,906ms |

## Expected-shape check (DEV_PLAN section 15)

- Naive baseline on trap/definition questions: 44% (4/9) -- matches expectation (fails most).
- cube x gemini (headline) on P1/P2/P4 questions: 38% (3/8) -- DEVIATES (fails most).
- cube x anthropic (control) on P1/P2/P4 questions: 12% (1/8) -- DEVIATES (fails most).
