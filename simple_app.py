"""Simple UI: start a run, watch the progress bar, see the results table.

Run with:  .venv/bin/python -m streamlit run simple_app.py
Every run is stored in runs/<run_id>/ (scores_*.csv, progress.json, log.txt).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from landclass import runner
from landclass.config import DEFAULT_THRESHOLDS, MISTRAL_API_KEY, MISTRAL_MODEL, RUNS_DIR, TAXONOMIES
from landclass.data import load_snapshot
from landclass.export import load_scores, run_records, run_taxonomy, select, wide_table

st.set_page_config(page_title="Land Classifier", page_icon="🗺️", layout="wide")
st.title("Land cover & land use classifier")

snap = load_snapshot()
if snap is None:
    st.error("No records found. Fetch them first with the full UI (`streamlit run app.py`, tab 1).")
    st.stop()
if not MISTRAL_API_KEY:
    st.error("MISTRAL_API_KEY is not set in .env")
    st.stop()

active = [r for r in runner.list_runs() if runner.read_progress(r)["status"] in ("running", "starting")]

c1, c2, c3 = st.columns([1, 1, 3])
n = c1.number_input("Records", 1, len(snap), 20)
if c2.button("Start run", type="primary", disabled=bool(active), width="stretch"):
    run_dir = runner.create_run(list(TAXONOMIES), "sample", int(n))
    runner.start_run(run_dir)
    st.rerun()
c3.caption(f"Model: {MISTRAL_MODEL} · about $0.60 per 1,000 records · random sample of {len(snap):,} records · "
           f"results are saved in `{RUNS_DIR}/<run_id>/`")

runs = runner.list_runs()
if not runs:
    st.info("No runs yet. Choose a number of records and click Start run.")
    st.stop()
run_dir = st.selectbox("Run", runs, format_func=lambda r: r.name)


@st.fragment(run_every="3s")
def progress():
    prog = runner.read_progress(run_dir)
    done, total = prog.get("done", 0), prog.get("total", 0)
    st.progress(done / total if total else 0.0, text=f"{done:,} / {total:,} records · {prog.get('status')}")
    cost = prog.get("cost_usd")
    parts = [f"{prog.get('rate') or '–'} records/s"]
    if prog.get("cost_usd") is not None:
        parts.append(f"${prog['cost_usd']:.3f} so far")
    if prog.get("eta_seconds"):
        parts.append(f"ETA {int(prog['eta_seconds']) // 60 + 1} min")
    st.caption(" · ".join(parts))
    if prog.get("error"):
        st.error(prog["error"])
    if prog.get("status") in ("running", "starting") and st.button("Stop"):
        runner.request_stop(run_dir)
    if prog.get("status") in ("stopped", "interrupted", "failed") and done < total and st.button("Resume"):
        runner.start_run(run_dir)


progress()


@st.fragment(run_every="5s")
def table():
    records = run_records(run_dir)
    if records.empty:
        st.caption("No results yet.")
        return
    cfg = runner.read_run(run_dir)
    out = records[["id", "title"]].copy()
    for key in cfg["taxonomies"]:
        w = wide_table(select(load_scores(run_dir, key), DEFAULT_THRESHOLDS), run_taxonomy(run_dir, key), records)
        out = out.merge(w[["id", "labels"]].rename(columns={"labels": TAXONOMIES[key]["name"]}), on="id", how="left")
    out = out.drop(columns="id").fillna("")
    st.dataframe(out, hide_index=True, width="stretch", height=500)
    st.download_button("Download CSV", out.to_csv(index=False), f"{run_dir.name}.csv", "text/csv")


table()
