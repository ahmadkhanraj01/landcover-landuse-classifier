# Mistral migration: what changed, cost, speed, and test results

Date: 2026-10-07

GLiNER2.5-Decide was replaced by the Mistral API (`mistral-small-latest`). The cascade (Level 1 → 2 → 3) is unchanged;
each API call scores one sibling group of classes and returns a 0–1 confidence per class as JSON.

## What changed

| Area | Change |
|---|---|
| `landclass/engine.py` | Rewritten. Mistral calls with strict JSON schema, `temperature=0`, retries, client-side rate limiter, **5 records per call** (`MISTRAL_PACK`), token and cost tracking |
| `landclass/config.py` | Mistral settings (`MISTRAL_API_KEY`, `MISTRAL_MODEL`, `MISTRAL_CONCURRENCY`, `MISTRAL_PACK`, `MISTRAL_RPM`, `MISTRAL_TPM`, prices). GPU/model settings removed |
| `landclass/runner.py`, `app.py` | No GPU/batch settings. Runs record calls, tokens and cost; UI shows time and cost estimates |
| `simple_app.py` (new) | Simple UI: start a run, progress bar, results table, CSV download |
| Deleted | `hardware.py`, `download_model.py`; torch, transformers, gliner2 removed from requirements |

## Run the UIs

```bash
.venv/bin/python -m streamlit run simple_app.py   # simple UI
./run_ui.sh                                       # full UI (labels, thresholds, export)
```

Note: there is no `.venv/bin/streamlit` executable; use `python -m streamlit`.

## Where results are stored

| What | Where |
|---|---|
| Per run | `runs/<run_id>/`: `scores_landcover.csv`, `scores_landuse.csv`, `progress.json`, `log.txt`, `ids.txt`, `done_ids.txt`, `label_hints.csv` |
| Input records | `data/records_snapshot.parquet` (local copy of `public.records`) |
| Exported CSVs | `output/<run_id>/` (written by the full UI, Results tab) |

The database is only read. `runs/`, `data/`, `output/` and `.env` are git-ignored.

## Why it was slow: the account rate limit

The Mistral account limits are **100 requests/min** and **100,000 tokens/min** (from the API response headers).
The first full run used one record per call (about 3.75 calls and 2.8k tokens per record), so it ran at the
request limit: about 0.44 records/s. More concurrency does not help; it only causes 429 retries.

## Cost and time for the remaining 24,873 records

| Option | Cost | Time |
|---|---|---|
| One record per call | about $12.7 | about 15.7 h |
| **5 records per call (measured on 100 records)** | **about $9.3** | **about 8.5 h** (token limit) |
| Higher Mistral tier (either mode) | unchanged | about 1–3 h (estimate) |
| Batch API | about half price | not predictable (async, about 3 rounds) |

## Test: single vs packed, same 100 records

| | Single | Packed (5) |
|---|---|---|
| Speed | 0.40 rec/s | 0.81 rec/s |
| Requests | about 418 | 93 |
| Tokens | about 360k | 191k |
| Cost | $0.062 | $0.037 |

Label agreement (exact match, land cover):

| Level | single vs single | single vs packed |
|---|---|---|
| 1 | 96% | 84% |
| 2–3 | 90% | 71–73% |

Aggregates are the same (land cover: 37 vs 40 records without a label; 1.33 vs 1.32 labels per record).
Differences are mostly borderline cases and go both ways (packed adds a class in 7 records, drops one in 9
at land-cover level 1), but packing changes more labels than plain run-to-run noise does.

## Known limitations

- Mistral returns a self-reported confidence, not a calibrated probability; thresholds (0.60 / 0.50 / 0.50)
  may need re-tuning in the Results tab.
- Results vary slightly between identical runs even at `temperature=0`.
- Land use fires on some non-land-use records (datasets, methods papers).
- Titles and abstracts are sent to Mistral (the old setup ran fully locally).

## Status of the full run

Run `20261007-160031` (all 25,129 records) was **stopped** at 256 records, $0.131 spent.
Resume from the UI (Resume button) or:

```bash
.venv/bin/python -m landclass.runner run runs/20261007-160031
```

Resuming uses packing (default `MISTRAL_PACK=5`). Set `MISTRAL_PACK=1` in `.env` for single-record mode.
The first 256 records were scored in single-record mode.
