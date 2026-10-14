"""End to end: records -> classify -> CSV files -> database tables.

  python pipeline.py --sample 20                 # random 20 records
  python pipeline.py                             # all records
  python pipeline.py --resume runs/<run_id>      # continue an interrupted run
  python pipeline.py --sample 20 --no-db         # stop after the CSV files
"""
import argparse
import sys
from pathlib import Path

from landclass.config import DEFAULT_GATE_THRESHOLD, DEFAULT_MAX_LEVEL, DEFAULT_THRESHOLDS, TAXONOMIES
from landclass.data import fetch_snapshot, load_snapshot
from landclass.export import export
from landclass.runner import create_run, read_progress, run


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="pipeline.py")
    p.add_argument("--sample", type=int, help="random sample of N records")
    p.add_argument("--limit", type=int, help="first N records")
    p.add_argument("--resume", type=Path, help="continue this run folder instead of creating one")
    p.add_argument("--max-level", type=int, default=DEFAULT_MAX_LEVEL, choices=[1, 2, 3])
    p.add_argument("--no-gate", action="store_true", help="skip the land use gate")
    p.add_argument("--no-db", action="store_true", help="do not load the CSV files into the database")
    a = p.parse_args(argv)

    if a.resume:
        run_dir = a.resume
    else:
        if load_snapshot() is None:
            print("No local snapshot: fetching records from the database...", flush=True)
            print(f"{len(fetch_snapshot()):,} records fetched", flush=True)
        mode, n = ("sample", a.sample) if a.sample else ("first", a.limit) if a.limit else ("all", None)
        run_dir = create_run(list(TAXONOMIES), mode, n, max_level=a.max_level,
                             gate=None if a.no_gate else DEFAULT_GATE_THRESHOLD)
    print(f"== 1/3 classify: {run_dir}", flush=True)
    run(run_dir)
    status = read_progress(run_dir).get("status")
    if status != "finished":
        print(f"Run is '{status}', not finished. Continue with: python pipeline.py --resume {run_dir}")
        return 1

    print("== 2/3 write CSV files", flush=True)
    keys = list(TAXONOMIES)
    for key in keys:
        wide, _ = export(run_dir, key, DEFAULT_THRESHOLDS)
        print(f"   {wide}", flush=True)
    out_dir = wide.parent
    if a.no_db:
        print("== 3/3 database: skipped (--no-db)")
        return 0

    print("== 3/3 load into the database (schema validate)", flush=True)
    from landclass.dbload import load_results
    load_results(out_dir, keys)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        sys.exit(f"{type(e).__name__}: {e}")
