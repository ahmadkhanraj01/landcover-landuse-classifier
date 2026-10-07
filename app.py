"""Land cover / land use classifier UI.

Run with:  .venv/bin/streamlit run app.py
The database is only read (one SELECT into a local snapshot); results are CSV files.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from landclass import runner
from landclass.config import (DEFAULT_EXPLORE_THRESHOLD, DEFAULT_MAX_LEVEL,
                              DEFAULT_THRESHOLDS, MISTRAL_API_KEY, MISTRAL_MODEL, TAXONOMIES)
from landclass.data import fetch_snapshot, load_snapshot, snapshot_meta
from landclass.export import (export, load_scores, long_table, run_records, run_taxonomy,
                              select, wide_table)
from landclass.taxonomy import HINT_COLUMNS, build_taxonomy, default_hints, load_hints, save_hints

st.set_page_config(page_title="Land Classifier", page_icon="🗺️", layout="wide")

TAX_NAMES = {k: v["name"] for k, v in TAXONOMIES.items()}


def bar_color() -> str:
    try:
        return "#3987e5" if st.context.theme.type == "dark" else "#2a78d6"
    except AttributeError:
        return "#2a78d6"


def measured_speed(taxes: list[str], max_level: int):
    """Records/s and cost per record of the latest run with the same taxonomies and depth."""
    for run_dir in runner.list_runs():
        cfg, prog = runner.read_run(run_dir), runner.read_progress(run_dir)
        if (sorted(cfg["taxonomies"]) == sorted(taxes) and cfg.get("max_level", 3) == max_level
                and prog.get("rate") and prog.get("cost_usd") and prog.get("done")):
            return prog["rate"], prog["cost_usd"] / prog["done"]
    return None


def fmt_eta(seconds) -> str:
    if seconds is None:
        return "–"
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min" if m else "< 1 min"


st.title("Land cover & land use classifier")
st.caption(f"Mistral API ({MISTRAL_MODEL}): record titles and abstracts are sent to Mistral. "
           "The database is only read; results are saved as CSV files.")

tab_data, tab_labels, tab_run, tab_results = st.tabs(
    ["1 · Data", "2 · Labels", "3 · Run", "4 · Results & export"])

# ---------------------------------------------------------------- 1 · Data
with tab_data:
    meta = snapshot_meta()
    snap = load_snapshot()
    c1, c2 = st.columns([3, 1])
    with c1:
        if meta:
            st.success(f"Snapshot: **{meta['rows']:,} records**, fetched {meta['fetched_at']} "
                       f"from `{meta['source']}`")
        else:
            st.info("No snapshot yet. Fetch the records from the database first.")
    with c2:
        if st.button("Fetch from database", help="Read-only SELECT of id, identifier, title, abstract",
                     width="stretch"):
            with st.spinner("Reading public.records…"):
                try:
                    snap = fetch_snapshot()
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not read the database: {e}")
    if snap is not None:
        words = snap["abstract"].str.split().str.len()
        m1, m2, m3 = st.columns(3)
        m1.metric("Records", f"{len(snap):,}")
        m2.metric("Median abstract length", f"{int(words.median())} words")
        m3.metric("Empty abstracts", f"{int((words == 0).sum()):,}")
        st.dataframe(snap.head(200), width="stretch", hide_index=True,
                     column_config={"abstract": st.column_config.TextColumn(width="large")})

# ---------------------------------------------------------------- 2 · Labels
with tab_labels:
    st.markdown(
        "What the model sees for each class: its **name** and an optional **hint**. Classes without a hint "
        "are described by their sub-classes. Untick **enabled** to drop a class. Changes apply to new runs.")
    hints = load_hints()
    edited = {}
    for key, tab in zip(TAXONOMIES, st.tabs(list(TAX_NAMES.values()))):
        with tab:
            edited[key] = st.data_editor(
                hints[hints["taxonomy"] == key].reset_index(drop=True),
                key=f"hints_{key}", width="stretch", hide_index=True, num_rows="fixed",
                disabled=["taxonomy", "code", "level", "parent_code"],
                column_config={
                    "hint": st.column_config.TextColumn(width="large"),
                    "name": st.column_config.TextColumn(width="medium"),
                    "enabled": st.column_config.CheckboxColumn(),
                })
    b1, b2, _ = st.columns([1, 1, 4])
    if b1.button("Save labels", type="primary"):
        save_hints(pd.concat(edited.values())[HINT_COLUMNS])
        st.success("Saved to label_hints.csv")
    if b2.button("Reset to defaults"):
        save_hints(default_hints())
        for key in TAXONOMIES:
            st.session_state.pop(f"hints_{key}", None)
        st.rerun()

    st.divider()
    st.subheader("Try a text")
    st.caption("Sends the text to the Mistral API (a few seconds, a fraction of a cent). Uses the saved labels.")
    text = st.text_area("Title and abstract", height=150,
                        placeholder="Paste a title and abstract to see how it is classified…")
    if st.button("Classify text", disabled=not text.strip()):
        from landclass.engine import Engine, MistralError

        try:
            eng = Engine()
        except MistralError as e:
            st.error(str(e))
            st.stop()
        with st.spinner("Classifying…"):
            cols = st.columns(len(TAXONOMIES))
            for col, key in zip(cols, TAXONOMIES):
                tax = build_taxonomy(key)
                scores = eng.classify(tax, [{"id": "x", "title": "", "abstract": text}],
                                      DEFAULT_EXPLORE_THRESHOLD)
                df = pd.DataFrame([s.__dict__ for s in scores]).rename(columns={"record_id": "id"})
                sel = select(df, DEFAULT_THRESHOLDS)
                tbl = long_table(sel, tax).sort_values(["prob"], ascending=False)
                col.markdown(f"**{tax.name}**")
                col.dataframe(tbl[["level", "code", "label", "prob", "selected"]],
                              hide_index=True, width="stretch")

# ---------------------------------------------------------------- 3 · Run
with tab_run:
    snap = load_snapshot()
    if snap is None:
        st.info("Fetch the records first (tab 1).")
    else:
        with st.form("new_run"):
            st.subheader("New run")
            c1, c2 = st.columns(2)
            taxes = c1.multiselect("Taxonomies", list(TAXONOMIES), default=list(TAXONOMIES),
                                   format_func=TAX_NAMES.get)
            mode = c2.radio("Records", ["sample", "first", "all"], horizontal=True,
                            format_func={"sample": "Random sample", "first": "First N", "all": f"All ({len(snap):,})"}.get)
            c3, c4, c5 = st.columns(3)
            n = c3.number_input("N (for sample / first N)", 1, len(snap), 10)
            max_level = c4.selectbox("Max depth", [1, 2, 3], index=DEFAULT_MAX_LEVEL - 1,
                                     help="Level 1 only is about 3× cheaper and faster than the full cascade")
            explore = c5.slider("Explore threshold", 0.1, 0.9, DEFAULT_EXPLORE_THRESHOLD, 0.05,
                                help="Sub-classes are only scored under classes at or above this probability. "
                                     "Lower = more detail but slower.")
            n_rec = len(snap) if mode == "all" else n
            speed = measured_speed(taxes, max_level)
            if speed:
                rate, per_rec = speed
                st.caption(f"Estimated time: **{fmt_eta(n_rec / rate)}**, cost: **≈ ${n_rec * per_rec:,.2f}** "
                           f"(measured {rate:.2f} records/s, ${per_rec * 1000:.2f} per 1,000 records "
                           "in an earlier run with these settings)")
            else:
                st.caption("No measurement yet for these settings: run a small sample first to get a time "
                           "and cost estimate. Rough guide for both taxonomies at depth 3: "
                           "$0.55 per 1,000 records with Mistral Small.")
            if not MISTRAL_API_KEY:
                st.warning("MISTRAL_API_KEY is not set in .env: a run will fail.")
            if st.form_submit_button("Start run", type="primary", disabled=not taxes):
                active = [r for r in runner.list_runs() if runner.read_progress(r)["status"] in ("running", "starting")]
                if active:
                    st.error(f"Run {active[0].name} is still running. Stop it first.")
                else:
                    run_dir = runner.create_run(taxes, mode, None if mode == "all" else int(n),
                                                explore=explore, max_level=max_level)
                    runner.start_run(run_dir)
                    st.success(f"Started run {run_dir.name}")

        st.subheader("Runs")

        @st.fragment(run_every="3s")
        def runs_panel():
            runs = runner.list_runs()
            if not runs:
                st.caption("No runs yet.")
                return
            for run_dir in runs[:10]:
                cfg = runner.read_run(run_dir)
                prog = runner.read_progress(run_dir)
                status, done, total = prog.get("status"), prog.get("done", 0), prog.get("total", 0)
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.markdown(f"**{run_dir.name}** · {', '.join(TAX_NAMES[t] for t in cfg['taxonomies'])} · "
                                f"{cfg['selection']['mode']} · depth {cfg.get('max_level', 3)}")
                    c2.markdown(f"`{status}` · {done:,}/{total:,} · "
                                f"{prog.get('rate') or '–'} rec/s · ETA {fmt_eta(prog.get('eta_seconds'))}")
                    if status in ("running", "starting"):
                        if c3.button("Stop", key=f"stop_{run_dir.name}"):
                            runner.request_stop(run_dir)
                    elif status in ("stopped", "interrupted", "failed", "created") and done < total:
                        if c3.button("Resume", key=f"resume_{run_dir.name}"):
                            runner.start_run(run_dir)
                    st.progress(done / total if total else 0.0)
                    if prog.get("cost_usd") is not None:
                        st.caption(f"{prog.get('engine', '')} · {prog.get('calls', 0):,} calls · "
                                   f"{prog.get('input_tokens', 0) + prog.get('output_tokens', 0):,} tokens · "
                                   f"${prog['cost_usd']:.3f} so far")
                    if prog.get("error"):
                        st.error(prog["error"])
                    log = run_dir / "log.txt"
                    if status == "failed" and log.exists():
                        st.code("\n".join(log.read_text().splitlines()[-15:]))

        runs_panel()

# ---------------------------------------------------------------- 4 · Results
with tab_results:
    runs = [r for r in runner.list_runs() if runner.read_progress(r).get("done", 0) > 0]
    if not runs:
        st.info("No results yet. Start a run in tab 3.")
    else:
        run_dir = st.selectbox("Run", runs, format_func=lambda r: (
            f"{r.name} · {runner.read_progress(r)['done']:,} records · {runner.read_progress(r)['status']}"))
        cfg = runner.read_run(run_dir)
        records = run_records(run_dir)
        include_abstract = st.checkbox("Include abstract in exported CSV", value=False)

        for key, tab in zip(cfg["taxonomies"], st.tabs([TAX_NAMES[t] for t in cfg["taxonomies"]])):
            with tab:
                tax = run_taxonomy(run_dir, key)
                scores = load_scores(run_dir, key)
                c1, c2, c3 = st.columns(3)
                th = {
                    1: c1.slider("Level 1 threshold", 0.05, 0.95, DEFAULT_THRESHOLDS[1], 0.05, key=f"t1_{key}"),
                    2: c2.slider("Level 2 threshold", 0.05, 0.95, DEFAULT_THRESHOLDS[2], 0.05, key=f"t2_{key}"),
                    3: c3.slider("Level 3 threshold", 0.05, 0.95, DEFAULT_THRESHOLDS[3], 0.05, key=f"t3_{key}"),
                }
                st.caption(f"Sub-classes were only scored under classes ≥ {cfg['explore_threshold']} "
                           f"(explore threshold of this run), down to level {cfg.get('max_level', 3)}.")
                sel = select(scores, th)
                wide = wide_table(sel, tax, records)

                m1, m2, m3 = st.columns(3)
                m1.metric("Records", f"{len(wide):,}")
                m2.metric("With ≥ 1 label", f"{int((wide['n_labels'] > 0).sum()):,}")
                m3.metric("No label", f"{int((wide['n_labels'] == 0).sum()):,}")

                l1 = sel[(sel["level"] == 1) & sel["selected"]].groupby("code").size()
                chart_df = pd.DataFrame({
                    "class": [f"{n.code} · {n.name}" for n in tax.roots()],
                    "records": [int(l1.get(n.code, 0)) for n in tax.roots()],
                })
                chart = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4, color=bar_color(), size=14).encode(
                    x=alt.X("records:Q", title="Records"),
                    y=alt.Y("class:N", sort="-x", title=None),
                    tooltip=["class", "records"],
                ).properties(height=34 * len(chart_df), title="Records per Level 1 class")
                st.altair_chart(chart, width="stretch")

                f1, f2 = st.columns([2, 1])
                codes = f1.multiselect("Filter by class", sorted(sel.loc[sel["selected"], "code"].unique()),
                                       format_func=lambda c: f"{c} · {tax.nodes[c].name}", key=f"f_{key}")
                query = f2.text_input("Search title", key=f"q_{key}")
                view = wide
                if codes:
                    ids = set(sel[sel["selected"] & sel["code"].isin(codes)]["id"])
                    view = view[view["id"].isin(ids)]
                if query:
                    view = view[view["title"].str.contains(query, case=False, na=False)]
                st.dataframe(view.drop(columns=["id"]), width="stretch", hide_index=True, height=360)

                with st.expander("Inspect a record"):
                    rid = st.selectbox("Record", view["id"].head(500), key=f"r_{key}",
                                       format_func=lambda i: records.set_index("id").at[i, "title"][:120])
                    if rid:
                        rec = records.set_index("id").loc[rid]
                        st.markdown(f"**{rec['title']}**  \n`{rec['identifier']}`")
                        st.write(rec["abstract"])
                        tree = long_table(sel[sel["id"] == rid], tax).sort_values(["level", "prob"], ascending=[True, False])
                        st.dataframe(tree[["level", "code", "label", "parent", "prob", "selected"]],
                                     hide_index=True, width="stretch")

                if st.button(f"Export {TAX_NAMES[key]} CSVs", key=f"exp_{key}", type="primary"):
                    wide_path, long_path = export(run_dir, key, th, include_abstract)
                    st.session_state[f"exported_{key}"] = (wide_path, long_path)
                if f"exported_{key}" in st.session_state:
                    wide_path, long_path = st.session_state[f"exported_{key}"]
                    st.success(f"Saved `{wide_path}` and `{long_path.name}`")
                    d1, d2 = st.columns(2)
                    d1.download_button("Download results CSV", wide_path.read_bytes(), wide_path.name,
                                       "text/csv", key=f"dw_{key}")
                    d2.download_button("Download all scores (long) CSV", long_path.read_bytes(), long_path.name,
                                       "text/csv", key=f"dl_{key}")
