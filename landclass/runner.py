"""Background classification job.

A run lives in runs/<run_id>/:
  run.json            settings (taxonomies, selection, explore threshold)
  label_hints.csv     the label hints frozen at run creation
  ids.txt             record ids to classify
  done_ids.txt        record ids already classified (resume point)
  scores_<tax>.csv    every computed probability: id, level, code, parent, prob
  progress.json       status for the UI
  log.txt             stdout/stderr of the job
  STOP                created by the UI to ask the job to stop after the current step

Usage:
  python -m landclass.runner new --taxonomies landcover,landuse [--limit N] [--sample N]
  python -m landclass.runner run runs/<run_id>
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from .config import (DEFAULT_EXPLORE_THRESHOLD, DEFAULT_MAX_LEVEL, LABEL_HINTS_FILE,
                     MISTRAL_MODEL, RECORDS_PER_STEP, ROOT, RUNS_DIR, TAXONOMIES)
from .data import load_snapshot, snapshot_meta
from .taxonomy import build_taxonomy, load_hints

SCORE_COLUMNS = ["id", "level", "code", "parent", "prob"]


# -- run management (used by the UI) ---------------------------------------

def create_run(taxonomies: list[str], mode: str = "all", n: int | None = None, seed: int = 42,
               explore: float = DEFAULT_EXPLORE_THRESHOLD,
               max_level: int = DEFAULT_MAX_LEVEL) -> Path:
    df = load_snapshot()
    if df is None:
        raise RuntimeError("No snapshot yet: fetch the records first")
    if mode == "first" and n:
        ids = df["id"].head(n).tolist()
    elif mode == "sample" and n:
        ids = df.sample(n=min(n, len(df)), random_state=seed)["id"].tolist()
    else:
        ids = df["id"].tolist()

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True)
    load_hints()  # creates label_hints.csv if missing
    shutil.copy(LABEL_HINTS_FILE, run_dir / "label_hints.csv")
    (run_dir / "ids.txt").write_text("\n".join(ids) + "\n")
    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_id,
        "taxonomies": taxonomies,
        "selection": {"mode": mode, "n": n, "seed": seed, "records": len(ids)},
        "model": MISTRAL_MODEL,
        "explore_threshold": explore,
        "max_level": max_level,
        "snapshot": snapshot_meta(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }, indent=2))
    _write_progress(run_dir, status="created", done=0, total=len(ids))
    return run_dir


def start_run(run_dir: Path) -> int:
    """Launch the job as a detached process so it survives UI reloads."""
    (run_dir / "STOP").unlink(missing_ok=True)
    log = open(run_dir / "log.txt", "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "landclass.runner", "run", str(run_dir)],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
    (run_dir / "pid").write_text(str(proc.pid))
    return proc.pid


def request_stop(run_dir: Path) -> None:
    (run_dir / "STOP").touch()


def is_alive(run_dir: Path) -> bool:
    pid_file = run_dir / "pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text())
        os.kill(pid, 0)
        # a zombie child still answers kill(0); check its state
        stat = Path(f"/proc/{pid}/stat")
        return not (stat.exists() and stat.read_text().split()[2] == "Z")
    except (ProcessLookupError, ValueError, PermissionError):
        return False


def list_runs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    return sorted((p for p in RUNS_DIR.iterdir() if (p / "run.json").exists()), reverse=True)


def read_progress(run_dir: Path) -> dict:
    try:
        prog = json.loads((run_dir / "progress.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        prog = {"status": "unknown", "done": 0, "total": 0}
    if prog.get("status") == "running" and not is_alive(run_dir):
        prog["status"] = "interrupted"
    return prog


def read_run(run_dir: Path) -> dict:
    return json.loads((run_dir / "run.json").read_text())


def _write_progress(run_dir: Path, **fields) -> None:
    path = run_dir / "progress.json"
    try:
        prog = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        prog = {}
    prog.update(fields, updated_at=datetime.now().isoformat(timespec="seconds"))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(prog, indent=2))
    tmp.replace(path)


# -- the job ---------------------------------------------------------------

def run(run_dir: Path) -> None:
    from .engine import Engine

    cfg = read_run(run_dir)
    hints = load_hints(run_dir / "label_hints.csv")
    taxes = [build_taxonomy(k, hints) for k in cfg["taxonomies"]]

    ids = [l for l in (run_dir / "ids.txt").read_text().split("\n") if l]
    done_file = run_dir / "done_ids.txt"
    done = set(done_file.read_text().split()) if done_file.exists() else set()
    todo = [i for i in ids if i not in done]

    df = load_snapshot().set_index("id")
    _write_progress(run_dir, status="starting", done=len(done), total=len(ids), error=None)
    print(f"[{datetime.now():%H:%M:%S}] {len(todo)} records to do", flush=True)
    engine = Engine(model=cfg.get("model", MISTRAL_MODEL))
    print(f"[{datetime.now():%H:%M:%S}] {engine.describe()}", flush=True)
    _write_progress(run_dir, engine=engine.describe())
    step = RECORDS_PER_STEP

    writers = {}
    for tax in taxes:
        path = run_dir / f"scores_{tax.key}.csv"
        new = not path.exists()
        fh = open(path, "a", newline="")
        w = csv.writer(fh)
        if new:
            w.writerow(SCORE_COLUMNS)
        writers[tax.key] = (fh, w)

    prog0 = read_progress(run_dir)   # usage from before a resume
    prev_calls, prev_in, prev_out, prev_cost = (prog0.get(k, 0) for k in
                                                ("calls", "input_tokens", "output_tokens", "cost_usd"))
    started = time.time()
    processed = 0
    _write_progress(run_dir, status="running", started_at=datetime.now().isoformat(timespec="seconds"))
    for start in range(0, len(todo), step):
        if (run_dir / "STOP").exists():
            _write_progress(run_dir, status="stopped")
            print("stopped by request", flush=True)
            break
        batch_ids = todo[start:start + step]
        records = [{"id": i, "title": df.at[i, "title"], "abstract": df.at[i, "abstract"]} for i in batch_ids]
        for tax in taxes:
            fh, w = writers[tax.key]
            for s in engine.classify(tax, records, cfg["explore_threshold"], cfg.get("max_level", 3)):
                w.writerow([s.record_id, s.level, s.code, s.parent, f"{s.prob:.4f}"])
            fh.flush()
        with open(done_file, "a") as f:
            f.write("\n".join(batch_ids) + "\n")
        processed += len(batch_ids)
        done_n = len(done) + processed
        rate = processed / max(time.time() - started, 1e-6)
        eta = (len(ids) - done_n) / rate if rate else None
        _write_progress(run_dir, status="running", done=done_n, rate=round(rate, 2),
                        eta_seconds=round(eta) if eta is not None else None,
                        calls=prev_calls + engine.calls,
                        input_tokens=prev_in + engine.input_tokens,
                        output_tokens=prev_out + engine.output_tokens,
                        cost_usd=round(prev_cost + engine.cost_usd, 4))
        print(f"[{datetime.now():%H:%M:%S}] {done_n}/{len(ids)}  {rate:.2f} rec/s  "
              f"${prev_cost + engine.cost_usd:.3f}", flush=True)
    else:
        _write_progress(run_dir, status="finished", done=len(ids), eta_seconds=0)
        print("finished", flush=True)

    for fh, _ in writers.values():
        fh.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m landclass.runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="create a run and start it in the foreground")
    n.add_argument("--taxonomies", default=",".join(TAXONOMIES))
    n.add_argument("--limit", type=int, help="first N records")
    n.add_argument("--sample", type=int, help="random sample of N records")
    n.add_argument("--explore", type=float, default=DEFAULT_EXPLORE_THRESHOLD)
    n.add_argument("--max-level", type=int, default=DEFAULT_MAX_LEVEL, choices=[1, 2, 3])
    r = sub.add_parser("run", help="run or resume an existing run")
    r.add_argument("run_dir", type=Path)
    a = p.parse_args(argv)

    if a.cmd == "new":
        mode, count = ("sample", a.sample) if a.sample else ("first", a.limit) if a.limit else ("all", None)
        run_dir = create_run(a.taxonomies.split(","), mode, count,
                             explore=a.explore, max_level=a.max_level)
        print(run_dir)
    else:
        run_dir = a.run_dir
    (run_dir / "pid").write_text(str(os.getpid()))
    try:
        run(run_dir)
    except Exception as e:
        _write_progress(run_dir, status="failed", error=f"{type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
