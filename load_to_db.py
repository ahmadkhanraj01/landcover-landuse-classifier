"""Load classification CSVs into the `validate` schema.

  python load_to_db.py types                                  # create tables, load the class lists
  python load_to_db.py results output/<run_id> [--taxonomy landuse] [--dry-run]
"""
import argparse
import sys
from pathlib import Path

from landclass.config import TAXONOMIES
from landclass.dbload import init_db, load_results


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="load_to_db.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("types", help="create the tables and load the land cover / land use class lists")
    r = sub.add_parser("results", help="load <taxonomy>_results.csv of an output folder")
    r.add_argument("output_dir", type=Path)
    r.add_argument("--taxonomy", choices=list(TAXONOMIES), help="only this taxonomy (default: both)")
    r.add_argument("--dry-run", action="store_true", help="validate against the database, write nothing")
    a = p.parse_args(argv)
    try:
        if a.cmd == "types":
            print(init_db())
        else:
            load_results(a.output_dir, [a.taxonomy] if a.taxonomy else None, a.dry_run)
    except Exception as e:
        sys.exit(f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
