"""Read-only access to public.records and the local snapshot.

The database is only ever read: the session is opened read-only and the one
query is a SELECT. Everything downstream works on the local snapshot file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pandas as pd
import psycopg2
from dotenv import dotenv_values

from .config import ENV_FILE, SNAPSHOT_FILE, SNAPSHOT_META

QUERY = "SELECT id::text AS id, identifier, title, abstract FROM {schema}.{table} ORDER BY identifier"


def _env() -> dict:
    env = {**dotenv_values(ENV_FILE), **{k: v for k, v in os.environ.items() if k.startswith("DB_")}}
    missing = [k for k in ("DB_HOST", "DB_NAME", "DB_USER") if not env.get(k)]
    if missing:
        raise RuntimeError(f"Missing in .env: {', '.join(missing)}")
    return env


def fetch_snapshot() -> pd.DataFrame:
    """Download id, identifier, title, abstract and save them as the local snapshot."""
    env = _env()
    schema = env.get("DB_SCHEMA") or "public"
    table = env.get("DB_TABLE") or "records"
    if not (schema.isidentifier() and table.isidentifier()):
        raise RuntimeError("DB_SCHEMA / DB_TABLE must be plain identifiers")
    conn = psycopg2.connect(
        host=env["DB_HOST"], port=env.get("DB_PORT") or 5432, dbname=env["DB_NAME"],
        user=env["DB_USER"], password=env.get("DB_PASSWORD"),
        sslmode=env.get("DB_SSLMODE") or "prefer",
        connect_timeout=int(env.get("DB_CONNECT_TIMEOUT") or 10),
    )
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute(QUERY.format(schema=schema, table=table))
            cols = [c.name for c in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
        conn.rollback()
    finally:
        conn.close()

    df["title"] = df["title"].fillna("").astype(str)
    df["abstract"] = df["abstract"].fillna("").astype(str)
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(SNAPSHOT_FILE, index=False)
    SNAPSHOT_META.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": len(df),
        "source": f"{env['DB_HOST']}/{env['DB_NAME']} {schema}.{table}",
    }, indent=2))
    return df


def load_snapshot() -> pd.DataFrame | None:
    if not SNAPSHOT_FILE.exists():
        return None
    return pd.read_parquet(SNAPSHOT_FILE)


def snapshot_meta() -> dict | None:
    if not SNAPSHOT_META.exists():
        return None
    return json.loads(SNAPSHOT_META.read_text())
