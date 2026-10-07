# Land cover / land use classifier (`landcover-landuse-classifier`)

Classifies the records in `public.records` (title + abstract) into two separate taxonomies:

- **Land cover**: `LandCover_Types.csv` (LUCAS-style, 3 levels, classes A–H)
- **Land use**: `LandUse_Types.csv` (HILUCS-style, 3 levels, classes U1–U4)

It uses the [Mistral API](https://docs.mistral.ai/) (`mistral-small-latest` by default); record titles
and abstracts are sent to Mistral. **The database is only read** (one `SELECT` into a local snapshot).
All results are written as **CSV files**. It comes with a web UI (Streamlit) and a command-line runner.

---

## Contents

1. [Requirements](#1-requirements)
2. [Setup](#2-setup)
3. [Configure `.env`](#3-configure-env)
4. [Check the installation](#4-check-the-installation)
5. [Use the UI](#5-use-the-ui)
6. [Output files](#6-output-files)
7. [Command line](#7-command-line)
8. [Move to another PC](#8-move-to-another-pc)
9. [Speed and cost](#9-speed-and-cost)
10. [Troubleshooting](#10-troubleshooting)
11. [Project structure](#11-project-structure)

---

## 1. Requirements

| | Requirement |
|---|---|
| Python | 3.10–3.12 |
| Mistral API key | from https://console.mistral.ai/api-keys (paid usage; about $0.37 per 1,000 records for both taxonomies, see [9](#9-speed-and-cost)) |
| Network | for setup, for the Mistral API and for fetching from the DB |
| Disk | < 1 GB |

Check Python:

```bash
python3 --version        # Windows: python --version
```

---

## 2. Setup

### Option A: setup script (recommended)

Run it from inside the project folder.

**Linux / macOS**

```bash
./setup.sh
```

**Windows** (Command Prompt)

```bat
setup.bat
```

The script will:

1. create a virtual environment in `.venv/`
2. install everything in `requirements.txt`
3. copy `example.env` to `.env` if `.env` doesn't exist yet

### Option B: manual setup

**Linux / macOS**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp example.env .env
```

**Windows**

```bat
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
copy example.env .env
```

> In the rest of this guide, `.venv/bin/python` is the Linux/macOS path. On Windows use
> `.venv\Scripts\python` instead.

---

## 3. Configure `.env`

Open `.env` in a text editor. Every setting is explained in `example.env`.

**Database** (only needed to fetch records; it is read-only):

```ini
DB_HOST=your-db-host
DB_PORT=5432
DB_NAME=your-db-name
DB_USER=your-user
DB_PASSWORD=your-password
DB_SCHEMA=public
DB_TABLE=records
DB_SSLMODE=prefer
DB_CONNECT_TIMEOUT=10
```

If the folder already contains `data/records_snapshot.parquet` (e.g. it came in a packed zip), you
can leave the database settings empty and use the snapshot.

**Mistral API**:

```ini
MISTRAL_API_KEY=your-key
# optional
# MISTRAL_MODEL=mistral-small-latest
# MISTRAL_CONCURRENCY=8        # parallel requests
# MISTRAL_PACK=5               # records scored per API call (1 = one record per call)
# MISTRAL_RPM=90               # client-side limits per minute, used until the API reports yours
# MISTRAL_TPM=90000
```

The classifier reads your account's rate limits from the API and stays below them (waiting instead
of triggering HTTP 429 errors).

---

## 4. Check the installation

Classify 5 random records end to end (needs the snapshot; see step 5.1 and your API key):

```bash
.venv/bin/python -m landclass.runner new --sample 5
```

The test run prints lines like:

```
[15:47:24] Mistral API · mistral-small-latest · 5 records/call · 8 parallel
[15:47:31] 5/5  0.71 rec/s  $0.008
finished
```

The cost shown is computed from the token counts the API returns.

---

## 5. Use the UI

Start it:

| Linux / macOS | Windows |
|---|---|
| `./run_ui.sh` | `run_ui.bat` |

Then open **http://localhost:8501** in your browser. To use another port: `PORT=8502 ./run_ui.sh`.

**Simple UI**: start a run, watch a progress bar and see a results table (default thresholds, CSV
download). It has no label editing or threshold sliders:

```bash
.venv/bin/python -m streamlit run simple_app.py
```

(There is no `.venv/bin/streamlit` executable; use `python -m streamlit`.) Both UIs read and write
the same `runs/` folder.

### 5.1 Data tab

Click **Fetch from database**. This downloads `id, identifier, title, abstract` of all records into
`data/records_snapshot.parquet` and shows how many records there are. Click it again later to refresh.

### 5.2 Labels tab

Here you can change what the model sees for each class:

- **name**: the class label
- **hint**: an optional description. Classes without a hint are described by their sub-classes.
- **enabled**: untick to exclude a class. The photo-interpretation-only classes `Bx0/Bx1/Bx2` are off by default.

Click **Save labels** to write `label_hints.csv`. Changes apply to new runs.
**Try a text** classifies any pasted text on the CPU (10–30 s), so you can test hint changes.

> Tip: avoid generic words such as "soil" in hints. Almost every record mentions soil, so every
> class with that word would fire.

### 5.3 Run tab

Choose:

| Setting | Meaning |
|---|---|
| Taxonomies | Land cover, land use, or both |
| Records | Random sample of N, first N, or all |
| Max depth | 1 = top classes only (fastest), 3 = most specific classes |
| Explore threshold | sub-classes are only scored under classes at or above this probability |
| Batch size | 0 = automatic |

Click **Start run**. The run continues in the background, and closing the browser doesn't stop it.
The runs list shows progress, speed and ETA, with **Stop** and **Resume** buttons.
Only one run at a time is allowed.

**Recommended order**

1. Run **10 records** to check that everything works and to measure speed. After that, the Run tab shows an ETA.
2. Run a **random sample of 100–200**, review it in the Results tab, and adjust hints and thresholds.
3. Run **all records**.

### 5.4 Results & export tab

- **Threshold sliders** per level. Results update instantly, without re-running the model.
  A sub-class only counts when its parent class is selected.
- A chart of records per Level 1 class, a filterable table, and **Inspect a record**, which shows
  the abstract and every probability.
- **Export CSVs** writes the files to `output/<run_id>/` and offers them for download.

---

## 6. Output files

For each taxonomy (`landcover`, `landuse`) in `output/<run_id>/`:

**`<taxonomy>_results.csv`**: one row per record

| Column | Content |
|---|---|
| `id`, `identifier`, `title` | from `public.records` |
| `codes` / `labels` | most specific selected classes, e.g. `B17` / `Rice` (separated by `; `) |
| `probabilities` | e.g. `B17=0.98; C=0.71` |
| `L1_codes`, `L1_labels`, `L2_…`, `L3_…` | selected classes per level |
| `n_labels` | 0 = no class matched |
| `abstract` | only if "Include abstract" is ticked |

**`<taxonomy>_scores_long.csv`**: every computed probability:
`id, level, code, label, parent, prob, selected`.

**`<taxonomy>_thresholds.txt`**: the thresholds used for the export.

---

## 7. Command line

Everything the UI does to run classification is also available from a terminal:

```bash
.venv/bin/python -m landclass.runner new --sample 10                # random 10 records
.venv/bin/python -m landclass.runner new --limit 500                # first 500 records
.venv/bin/python -m landclass.runner new                            # all records
.venv/bin/python -m landclass.runner new --max-level 1              # top classes only (fastest)
.venv/bin/python -m landclass.runner new --taxonomies landcover     # one taxonomy
.venv/bin/python -m landclass.runner run runs/<run_id>              # resume a stopped run
```

Other option: `--explore 0.5`. Export the CSVs from the UI (Results tab).

---

## 8. Move to another PC

On the current PC, build a zip next to the project folder:

```bash
.venv/bin/python -m landclass.pack                  # code + data snapshot (~16 MB)
```

| Flag | Adds |
|---|---|
| `--with-results` | `runs/` and `output/` |
| `--with-env` | `.env` (**contains the DB password and the Mistral key**) |

`.venv` is never included. On the new PC: unzip, then follow [2. Setup](#2-setup).

---

## 9. Speed and cost

**The Mistral account limits set the speed.** The API reports them in its response headers; the
account used for testing had **100 requests/min and 100,000 tokens/min**. More parallel requests do
not help, they only cause 429 retries. A higher Mistral tier is the biggest speed-up and needs no
code change.

Each record needs about 3.75 scorings for both taxonomies at depth 3 (level 1 per taxonomy, plus one
per branch above the explore threshold). With `MISTRAL_PACK=5`, five records share one request, which
sends the class list once per five records.

Measured on the same 100 random records (`mistral-small-latest`, $0.15 / $0.60 per million input /
output tokens):

| | 1 record per call | 5 records per call (default) |
|---|---|---|
| Speed | 0.40 records/s | 0.81 records/s |
| Requests / tokens | about 418 / 360k | 93 / 191k |
| Cost | $0.062 | $0.037 |
| All 25,129 records | about $15, 16 h | about **$9.3, 8.5 h** |

Packing changes more labels than normal run-to-run variation: two single-record runs agreed 96% on
land cover level 1 (90% on levels 2–3), a single run and the packed run 84% (71–73%). The differences
were mostly borderline cases in both directions, and the overall label counts were the same. Set
`MISTRAL_PACK=1` for the most stable labels, at about twice the time and 1.4× the cost.
If a packed call fails or returns invalid JSON, it is redone one record at a time.

Depth 1 is about 3× cheaper. Run a small sample first: the Run tab then shows the measured time and
cost, and every run shows its tokens and cost so far. Prices are set in `.env`
(`MISTRAL_PRICE_INPUT/OUTPUT`) and only affect the estimate.

Mistral returns a self-reported confidence (0–1) per class, not a calibrated probability, and results
vary slightly between identical runs even at `temperature=0`. Re-tune the thresholds in the Results
tab after a first sample. See `mistral_migration.md` for the full test notes.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `MISTRAL_API_KEY is not set` / HTTP 401 | Put a valid key in `.env` |
| Run is slow | The Mistral rate limit is the cap, see [9](#9-speed-and-cost). Raise the tier, or keep `MISTRAL_PACK=5` |
| HTTP 429 (rate limit) | Retried automatically; if it keeps happening, lower `MISTRAL_RPM` / `MISTRAL_TPM` |
| "Fetch from database" fails | Check the `DB_*` values in `.env`, the VPN/firewall, and `DB_SSLMODE` |
| `streamlit: No such file` | Use `.venv/bin/python -m streamlit run ...` |
| Port 8501 already in use | `PORT=8502 ./run_ui.sh`, or stop the other Streamlit instance |
| Run shows `interrupted` | The process stopped (PC restarted, killed). Click **Resume**; finished records are kept |
| Many wrong labels | Raise the Level 1 threshold (Results tab) and improve the hints (Labels tab) |

Each run's log is in `runs/<run_id>/log.txt`.

---

## 11. Project structure

```
app.py                     Streamlit UI (labels, runs, results, export)
simple_app.py              simple Streamlit UI (start, progress bar, results table)
landclass/
  config.py                paths and defaults
  data.py                  read-only DB fetch → data/records_snapshot.parquet
  taxonomy.py              loads the taxonomy CSVs and label_hints.csv
  engine.py                Mistral cascade classifier (Level 1 → 2 → 3)
  runner.py                background job (resumable)
  export.py                thresholds → CSV files
  pack.py                  zips the folder for another PC
LandCover_Types.csv        land cover taxonomy
LandUse_Types.csv          land use taxonomy
label_hints.csv            label names/hints the model sees (edited in the UI)
example.env                settings template → copy to .env
requirements.txt           Python dependencies
setup.sh / setup.bat       one-time setup
run_ui.sh / run_ui.bat     start the UI
data/                      record snapshot (created by "Fetch from database")
runs/<run_id>/             per run: settings, probabilities, progress, log
output/<run_id>/           exported CSV files
```

For background on how this approach was chosen, see `classification_options.md`; for the move from
GLiNER to Mistral and the test results, see `mistral_migration.md`.
