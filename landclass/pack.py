"""Zip this folder for another PC.

  python -m landclass.pack                  code + taxonomies + label hints + data snapshot
  python -m landclass.pack --with-results   also runs/ and output/
  python -m landclass.pack --with-env       also .env (contains the DB password and the Mistral key!)

Never included: .venv (rebuilt by setup.sh / setup.bat), __pycache__.
"""
from __future__ import annotations

import argparse
import zipfile
from datetime import datetime
from pathlib import Path

from .config import ROOT

ALWAYS = ["app.py", "simple_app.py", "mistral_migration.md", "landclass", "LandCover_Types.csv", "LandUse_Types.csv", "label_hints.csv",
          "README.md", "classification_options.md", "requirements.txt", "example.env",
          "setup.sh", "setup.bat", "run_ui.sh", "run_ui.bat", "data"]


def _files(path: Path):
    if path.is_file():
        yield path
    elif path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and ".cache" not in p.parts:
                yield p


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m landclass.pack")
    ap.add_argument("--with-results", action="store_true")
    ap.add_argument("--with-env", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT.parent / f"landcover-landuse-classifier-{datetime.now():%Y%m%d}.zip")
    a = ap.parse_args(argv)

    items = list(ALWAYS)
    if a.with_results:
        items += ["runs", "output"]
    if a.with_env:
        items.append(".env")

    folder = "landcover-landuse-classifier"
    count = 0
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            for f in _files(ROOT / item):
                rel = f.relative_to(ROOT)
                method = zipfile.ZIP_STORED if f.suffix == ".parquet" else zipfile.ZIP_DEFLATED
                zf.write(f, f"{folder}/{rel.as_posix()}", compress_type=method)
                count += 1
    size = a.out.stat().st_size / 2**20
    print(f"Wrote {a.out} ({count} files, {size:,.0f} MB)")
    if not a.with_env:
        print("Note: .env not included; copy it separately or fill example.env on the other PC "
              "(only needed to re-fetch from the database).")


if __name__ == "__main__":
    main()
