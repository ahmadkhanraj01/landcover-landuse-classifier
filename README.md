# Land cover / land use classifier (`landcover-landuse-classifier`)

Classifies the records in `public.records` (title + abstract) into two separate taxonomies:

- **Land cover**: `LandCover_Types.csv` (LUCAS-style, 3 levels, classes A–H)
- **Land use**: `LandUse_Types.csv` (HILUCS-style, 3 levels, classes U1–U4)

It uses the [GLiNER2.5-Decide](https://huggingface.co/fastino/GLiNER2.5-Decide) model, running
locally on your machine. **The database is only read** (one `SELECT` into a local snapshot). All
results are written as **CSV files**. It comes with a web UI (Streamlit) and a command-line runner.

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
9. [Speed and hardware](#9-speed-and-hardware)
10. [Troubleshooting](#10-troubleshooting)
11. [Project structure](#11-project-structure)

---

## 1. Requirements

| | Minimum | Recommended |
|---|---|---|
| Python | 3.10 | 3.10–3.12 |
| GPU | none (CPU works, but slowly) | NVIDIA GPU with ≥ 8 GB VRAM |
| NVIDIA driver | one that supports your PyTorch CUDA build | latest |
| RAM | 8 GB | 16 GB+ |
| Disk | ~6 GB (Python packages + 2 GB model) | |
| Network | for setup (packages + model download) and for fetching from the DB | |

Check Python and the GPU:

```bash
python3 --version        # Windows: python --version
nvidia-smi               # shows the GPU and driver if NVIDIA drivers are installed
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
2. install PyTorch and everything in `requirements.txt`
3. download the model (about 2 GB) into `models/GLiNER2.5-Decide/`
4. copy `example.env` to `.env` if `.env` doesn't exist yet
5. print the detected hardware, e.g. `NVIDIA GeForce RTX 4090, 24 GB · cuda · bf16 · batch 64`

**Choosing a CUDA build of PyTorch**

- **Linux:** the default PyPI torch already includes CUDA. To choose a specific build:
  `TORCH_INDEX=https://download.pytorch.org/whl/cu126 ./setup.sh`
- **Windows:** PyPI torch is CPU-only, so `setup.bat` installs from the PyTorch index
  (default `cu130`). With an older NVIDIA driver, pick an older build first:
  ```bat
  set TORCH_INDEX=https://download.pytorch.org/whl/cu126
  setup.bat
  ```
  See https://pytorch.org/get-started/locally/ for the builds that match your driver.

### Option B: manual setup

**Linux / macOS**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
# optional, to choose a CUDA build: .venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cu126
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m landclass.download_model
cp example.env .env
```

**Windows**

```bat
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install torch --index-url https://download.pytorch.org/whl/cu130
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m landclass.download_model
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

**Hardware** (optional): leave these commented out to auto-detect. Set them only to override:

```ini
# LANDCLASS_DEVICE=cuda      # cuda | cuda:1 | mps | cpu
# LANDCLASS_DTYPE=bf16       # fp32 | fp16 | bf16
# LANDCLASS_BATCH=32
```

---

## 4. Check the installation

```bash
# 1. Which device, precision and batch size will be used
.venv/bin/python -m landclass.hardware

# 2. Classify 5 random records end to end (needs the snapshot; see step 5.1)
.venv/bin/python -m landclass.runner new --sample 5
```

The test run prints lines like:

```
[15:47:24] model on NVIDIA GeForce GTX 1650 Ti, 4 GB · cuda · fp32 · batch 4
[15:47:35] 5/5  0.48 rec/s
finished
```

If the first line says `cpu` but you have an NVIDIA GPU, see [Troubleshooting](#10-troubleshooting).

---

## 5. Use the UI

Start it:

| Linux / macOS | Windows |
|---|---|
| `./run_ui.sh` | `run_ui.bat` |

Then open **http://localhost:8501** in your browser. To use another port: `PORT=8502 ./run_ui.sh`.

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
Only one run at a time fits on the GPU.

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

Other options: `--batch-size N`, `--explore 0.5`. Export the CSVs from the UI (Results tab).

---

## 8. Move to another PC

On the current PC, build a zip next to the project folder:

```bash
.venv/bin/python -m landclass.pack --with-model     # code + data snapshot + model (~2 GB)
.venv/bin/python -m landclass.pack                  # without model (~16 MB; downloaded during setup)
```

| Flag | Adds |
|---|---|
| `--with-model` | the model, so the new PC needs no model download |
| `--with-results` | `runs/` and `output/` |
| `--with-env` | `.env` (**contains the DB password**) |

`.venv` is never included. On the new PC: unzip, then follow [2. Setup](#2-setup).

---

## 9. Speed and hardware

Settings are picked automatically from the GPU (`landclass/hardware.py`):

| GPU | Precision | Batch size |
|---|---|---|
| RTX 30xx / 40xx / 50xx, A100, … | bf16 | from VRAM × 2 |
| RTX 20xx, T4, V100 | fp16 | from VRAM × 2 |
| GTX 16xx and older | fp32 (fp16 is ~4× slower on these) | from VRAM |
| Apple Silicon (mps) / CPU | fp32 | 8 |

Batch size from VRAM: < 6 GB → 4, < 10 GB → 8, < 20 GB → 16, otherwise 32.

Measured: GTX 1650 Ti (4 GB) ≈ **0.5 records/s** for both taxonomies at depth 3, so all
25k records take about 15 hours. Depth 1 is about 3× faster. A modern RTX GPU should be many
times faster; the Run tab shows the measured speed after a first test run.

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| Hardware check says `cpu` although there is an NVIDIA GPU | PyTorch was installed without CUDA. Reinstall it from the PyTorch index: `.venv/bin/python -m pip install --force-reinstall torch --index-url https://download.pytorch.org/whl/cu126` (pick the build for your driver) |
| `CUDA error: no kernel image` / driver too old | Install an older CUDA build of torch (see above) or update the NVIDIA driver |
| `CUDA out of memory` | The batch halves automatically. If it still fails, set `LANDCLASS_BATCH=2` in `.env` and stop other GPU programs |
| Run is much slower than expected | Check the hardware line in the run's log. On GTX cards use `fp32` (default); on RTX cards `bf16`/`fp16` |
| "Fetch from database" fails | Check the `DB_*` values in `.env`, the VPN/firewall, and `DB_SSLMODE` |
| Model download fails / no internet | On a PC with internet, run `python -m landclass.pack --with-model` and copy the zip |
| Port 8501 already in use | `PORT=8502 ./run_ui.sh`, or stop the other Streamlit instance |
| Run shows `interrupted` | The process stopped (PC restarted, killed). Click **Resume**; finished records are kept |
| Many wrong labels | Raise the Level 1 threshold (Results tab) and improve the hints (Labels tab) |

Each run's log is in `runs/<run_id>/log.txt`.

---

## 11. Project structure

```
app.py                     Streamlit UI
landclass/
  config.py                paths and defaults
  data.py                  read-only DB fetch → data/records_snapshot.parquet
  taxonomy.py              loads the taxonomy CSVs and label_hints.csv
  engine.py                GLiNER2 cascade classifier (Level 1 → 2 → 3)
  hardware.py              picks device / precision / batch size
  runner.py                background job (resumable)
  export.py                thresholds → CSV files
  download_model.py        downloads the model into models/
  pack.py                  zips the folder for another PC
LandCover_Types.csv        land cover taxonomy
LandUse_Types.csv          land use taxonomy
label_hints.csv            label names/hints the model sees (edited in the UI)
example.env                settings template → copy to .env
requirements.txt           Python dependencies
setup.sh / setup.bat       one-time setup
run_ui.sh / run_ui.bat     start the UI
data/                      record snapshot (created by "Fetch from database")
models/                    downloaded model
runs/<run_id>/             per run: settings, probabilities, progress, log
output/<run_id>/           exported CSV files
```

For background on how this approach was chosen, see `classification_options.md`.
