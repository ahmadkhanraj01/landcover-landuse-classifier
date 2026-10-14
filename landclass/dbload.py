"""Load the result CSVs into the `validate` schema of the records database.

Four tables (the schema is created if missing):
  validate.landcover_types / landuse_types    one row per class: code, level, parent_code, name, description
  validate.record_landcover / record_landuse  one row per record; record_id is the primary key and a
                                              foreign key to <DB_SCHEMA>.<DB_TABLE>(id)

The only writes go to the `validate` schema; the records table is only read. Records with no label
(n_labels = 0) are not loaded. Codes are checked against the class lists here, because Postgres
cannot put a foreign key on array elements.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import dotenv_values
from psycopg2.extras import execute_values

from .config import ENV_FILE, ROOT, TAXONOMIES
from .data import _env
from .taxonomy import _nodes_from_csv

SCHEMA = "validate"
SEP = "; "
DESCRIPTIONS_FILE = ROOT / "type_descriptions.csv"   # optional: taxonomy, code, description
RESULT_COLUMNS = ["codes", "probabilities", "L1_codes", "L2_codes", "L3_codes"]


def connect():
    """Connection for writing. DB_WRITE_USER / DB_WRITE_PASSWORD override the read-only account."""
    env = _env()
    env.update({k: v for k, v in {**dotenv_values(ENV_FILE), **os.environ}.items() if k.startswith("DB_WRITE_") and v})
    return psycopg2.connect(
        host=env["DB_HOST"], port=env.get("DB_PORT") or 5432, dbname=env["DB_NAME"],
        user=env.get("DB_WRITE_USER") or env["DB_USER"],
        password=env.get("DB_WRITE_PASSWORD") or env.get("DB_PASSWORD"),
        sslmode=env.get("DB_SSLMODE") or "prefer",
        connect_timeout=int(env.get("DB_CONNECT_TIMEOUT") or 10),
    ), env


def _records_ref(env: dict) -> str:
    schema, table = env.get("DB_SCHEMA") or "public", env.get("DB_TABLE") or "records"
    if not (schema.isidentifier() and table.isidentifier()):
        raise RuntimeError("DB_SCHEMA / DB_TABLE must be plain identifiers")
    return f"{schema}.{table}"


def create_tables(cur, env: dict) -> None:
    ref = _records_ref(env)
    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    for key in TAXONOMIES:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}.{key}_types (
                code        text PRIMARY KEY,
                level       smallint NOT NULL CHECK (level BETWEEN 1 AND 3),
                parent_code text REFERENCES {SCHEMA}.{key}_types (code),
                name        text NOT NULL,
                description text)""")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {SCHEMA}.record_{key} (
                record_id     uuid PRIMARY KEY REFERENCES {ref} (id) ON DELETE CASCADE,
                codes         text[] NOT NULL,
                probabilities text[] NOT NULL,
                l1_codes      text[] NOT NULL DEFAULT '{{}}',
                l2_codes      text[] NOT NULL DEFAULT '{{}}',
                l3_codes      text[] NOT NULL DEFAULT '{{}}',
                n_labels      smallint NOT NULL,
                run_id        text NOT NULL,
                classified_at timestamptz NOT NULL DEFAULT now())""")


def load_types(cur) -> dict[str, int]:
    """Upsert every class of both taxonomies. Existing descriptions are kept unless the file has a new one."""
    desc = {}
    if DESCRIPTIONS_FILE.exists():
        d = pd.read_csv(DESCRIPTIONS_FILE, dtype=str, keep_default_na=False)
        desc = {(r.taxonomy, r.code): r.description for r in d.itertuples() if r.description}
    counts = {}
    for key in TAXONOMIES:
        rows = sorted(_nodes_from_csv(key), key=lambda r: r["level"])   # parents before children
        execute_values(cur, f"""
            INSERT INTO {SCHEMA}.{key}_types (code, level, parent_code, name, description) VALUES %s
            ON CONFLICT (code) DO UPDATE SET level = EXCLUDED.level, parent_code = EXCLUDED.parent_code,
                name = EXCLUDED.name,
                description = COALESCE(EXCLUDED.description, {SCHEMA}.{key}_types.description)""",
            [(r["code"], r["level"], r["parent_code"] or None, r["name"], desc.get((key, r["code"])))
             for r in rows])
        counts[key] = len(rows)
    return counts


def _split(value: str) -> list[str]:
    return [x for x in value.split(SEP) if x]


def read_results(csv_path: Path, key: str, known_codes: set[str]) -> tuple[list[tuple], dict]:
    """Rows ready to insert plus a count of what was skipped and why."""
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = {"id", "n_labels", *RESULT_COLUMNS} - set(df.columns)
    if missing:
        raise RuntimeError(f"{csv_path.name}: missing columns {sorted(missing)}")
    stats = {"read": len(df), "no_label": 0, "duplicate_id": 0, "unknown_code": 0}
    rows, seen = [], set()
    for r in df.to_dict("records"):
        if int(r["n_labels"] or 0) == 0:
            stats["no_label"] += 1
            continue
        if r["id"] in seen:
            stats["duplicate_id"] += 1
            continue
        seen.add(r["id"])
        arrays = [_split(r[c]) for c in RESULT_COLUMNS]
        if not {c for a in arrays[:1] + arrays[2:] for c in a} <= known_codes:
            stats["unknown_code"] += 1
            continue
        rows.append((r["id"], *arrays, int(r["n_labels"])))
    return rows, stats


def existing_ids(cur, env: dict, ids: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(ids), 5000):
        cur.execute(f"SELECT id::text FROM {_records_ref(env)} WHERE id = ANY(%s::uuid[])", (ids[i:i + 5000],))
        found.update(r[0] for r in cur.fetchall())
    return found


def load_results(output_dir: Path, taxonomies: list[str] | None = None, dry_run: bool = False) -> dict:
    """Load `<tax>_results.csv` from an output/<run_id> folder. One transaction: all or nothing."""
    output_dir = Path(output_dir)
    summary = {}
    conn, env = connect()
    try:
        with conn.cursor() as cur:
            if not dry_run:
                create_tables(cur, env)
                load_types(cur)
            for key in taxonomies or list(TAXONOMIES):
                csv_path = output_dir / f"{key}_results.csv"
                if not csv_path.exists():
                    print(f"[{key}] {csv_path} not found, skipped", flush=True)
                    continue
                known = {r["code"] for r in _nodes_from_csv(key)}
                rows, stats = read_results(csv_path, key, known)
                ok = existing_ids(cur, env, [r[0] for r in rows])
                stats["unknown_id"] = len(rows) - sum(r[0] in ok for r in rows)
                rows = [r for r in rows if r[0] in ok]
                stats["inserted"] = stats["updated"] = 0
                if rows and not dry_run:
                    res = execute_values(cur, f"""
                        INSERT INTO {SCHEMA}.record_{key}
                            (record_id, codes, probabilities, l1_codes, l2_codes, l3_codes, n_labels, run_id) VALUES %s
                        ON CONFLICT (record_id) DO UPDATE SET codes = EXCLUDED.codes,
                            probabilities = EXCLUDED.probabilities, l1_codes = EXCLUDED.l1_codes,
                            l2_codes = EXCLUDED.l2_codes, l3_codes = EXCLUDED.l3_codes,
                            n_labels = EXCLUDED.n_labels, run_id = EXCLUDED.run_id, classified_at = now()
                        RETURNING (xmax = 0)""",
                        [(*r, output_dir.name) for r in rows],
                        template="(%s::uuid, %s::text[], %s::text[], %s::text[], %s::text[], %s::text[], %s, %s)",
                        fetch=True)
                    stats["inserted"] = sum(1 for x in res if x[0])
                    stats["updated"] = len(res) - stats["inserted"]
                summary[key] = stats
                print(f"[{key}] {stats}" + (" (dry run, nothing written)" if dry_run else ""), flush=True)
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return summary


def init_db() -> dict[str, int]:
    """Create the schema and tables and load the class lists."""
    conn, env = connect()
    try:
        with conn.cursor() as cur:
            create_tables(cur, env)
            counts = load_types(cur)
        conn.commit()
    finally:
        conn.close()
    return counts
