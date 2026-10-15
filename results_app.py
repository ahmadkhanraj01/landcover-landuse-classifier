"""Results viewer: id, identifier, title, abstract and the top 2 land use / land cover classes.

Run with:  .venv/bin/python -m streamlit run results_app.py
Works on any run folder in runs/, including ones copied from another PC.
"""
from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from landclass import runner
from landclass.data import load_snapshot
from landclass.export import run_taxonomy

TOP_N = 2
TAXES = {"landuse": "LU", "landcover": "LC"}
# fixed categorical order; a pie never gets more slices than this, the rest fold into "Other"
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
OTHER, NONE = "Other", "No class"
GRAY = {OTHER: "#8a8984", NONE: "#c9c8c2"}

st.set_page_config(page_title="Classification results", page_icon="🗺️", layout="wide")
st.title("Classification results")


@st.cache_data
def records() -> pd.DataFrame | None:
    return load_snapshot()


@st.cache_data
def scores(run_dir: str, tax_key: str) -> pd.DataFrame:
    path = Path(run_dir) / f"scores_{tax_key}.csv"
    if not path.exists():
        return pd.DataFrame(columns=["id", "level", "code", "parent", "prob"])
    # skipinitialspace + strip: tolerate files re-saved with padded columns
    df = pd.read_csv(path, dtype=str, skipinitialspace=True)
    df.columns = df.columns.str.strip()
    for c in df.columns:
        df[c] = df[c].str.strip()
    df["level"] = df["level"].astype(int)
    df["prob"] = df["prob"].astype(float)
    # a record scored twice keeps its last score, like export.load_scores
    return df.drop_duplicates(["id", "code"], keep="last")


@st.cache_data
def top_table(run_dir: str, level: int) -> pd.DataFrame:
    snap = records()
    ids = [l for l in (Path(run_dir) / "ids.txt").read_text().split("\n") if l]
    out = snap[snap["id"].isin(ids)][["id", "identifier", "title", "abstract"]].set_index("id")
    for key, short in TAXES.items():
        names = run_taxonomy(Path(run_dir), key).nodes
        s = scores(run_dir, key)
        s = s[(s["level"] == level) & (s["prob"] > 0)]
        s = s.sort_values(["id", "prob"], ascending=[True, False]).groupby("id").head(TOP_N)
        s["rank"] = s.groupby("id").cumcount() + 1
        s["label"] = [names[c].name if c in names else c for c in s["code"]]
        for r in range(1, TOP_N + 1):
            part = s[s["rank"] == r].set_index("id")
            out[f"{short} {r}"] = part["label"]
            out[f"{short} {r} p"] = part["prob"]
    return out.reset_index()


def class_order(run_dir: str, key: str, level: int) -> list[str]:
    """Class names of a level in taxonomy order, so a class keeps its color across filters."""
    return [n.name for n in run_taxonomy(Path(run_dir), key).nodes.values() if n.level == level]


def pie(counts: pd.Series, order: list[str]) -> alt.Chart:
    """Share of records per top class: first len(PALETTE) classes in taxonomy order, rest as Other."""
    named = [c for c in order if c in counts.index]
    top = counts.drop(NONE, errors="ignore").nlargest(len(PALETTE) - 1).index
    keep = named if len(named) <= len(PALETTE) else [c for c in named if c in top]
    d = counts.rename(lambda c: c if c in keep or c == NONE else OTHER).groupby(level=0).sum()
    d = d.reset_index().set_axis(["class", "records"], axis=1)
    d["share"] = d["records"] / d["records"].sum()
    domain = [c for c in order if c in keep] + [c for c in (OTHER, NONE) if c in d["class"].values]
    # a level with <= 8 classes colors by taxonomy position, so a class keeps its color under any filter
    slot = {c: i for i, c in enumerate(order if len(order) <= len(PALETTE) else keep)}
    colors = [GRAY[c] if c in GRAY else PALETTE[slot[c]] for c in domain]
    d["sort"] = d["class"].map({c: i for i, c in enumerate(domain)})
    return alt.Chart(d).mark_arc(innerRadius=60, stroke="white", strokeWidth=2).encode(
        theta=alt.Theta("records:Q", stack=True),
        color=alt.Color("class:N", scale=alt.Scale(domain=domain, range=colors),
                        legend=alt.Legend(title=None, orient="right", labelLimit=220)),
        order=alt.Order("sort:Q"),
        tooltip=[alt.Tooltip("class:N"), alt.Tooltip("records:Q", format=","),
                 alt.Tooltip("share:Q", format=".1%")],
    ).properties(height=300)


def bars(counts: pd.Series) -> alt.Chart:
    """Records per top class, largest first, one hue (it shows magnitude, not identity)."""
    d = counts.drop(NONE, errors="ignore").sort_values(ascending=False).reset_index()
    d.columns = ["class", "records"]
    d["share"] = d["records"] / counts.sum()
    y = alt.Y("class:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260))
    base = alt.Chart(d).encode(y=y, x=alt.X("records:Q", title="records", axis=alt.Axis(grid=False)))
    bar = base.mark_bar(color=PALETTE[0], cornerRadiusEnd=4, height={"band": 0.8}).encode(
        tooltip=[alt.Tooltip("class:N"), alt.Tooltip("records:Q", format=","),
                 alt.Tooltip("share:Q", format=".1%")])
    text = base.mark_text(align="left", dx=4).encode(text=alt.Text("records:Q", format=","))
    return (bar + text).properties(height=max(120, 26 * len(d)))


snap = records()
if snap is None:
    st.error("No records snapshot found (data/records_snapshot.parquet).")
    st.stop()

runs = [r for r in runner.list_runs() if (r / "ids.txt").exists()]
if not runs:
    st.info("No runs found in runs/.")
    st.stop()

c1, c2, c3 = st.columns([2, 1, 3])
run_dir = c1.selectbox("Run", runs, format_func=lambda r: (
    f"{r.name} · {runner.read_progress(r).get('done', 0):,} records · {runner.read_progress(r).get('status')}"))
level = c2.selectbox("Level", [1, 2, 3], help="Rank the classes of this level")
query = c3.text_input("Search", placeholder="id, identifier, title or abstract")

df = top_table(str(run_dir), level)
if query:
    q = query.lower()
    hay = df[["id", "identifier", "title", "abstract"]].fillna("").agg(" ".join, axis=1).str.lower()
    df = df[hay.str.contains(q, regex=False)]

tab_table, tab_charts = st.tabs(["Table", "Charts"])

with tab_charts:
    st.caption(f"Top class (LU 1 / LC 1) of the {len(df):,} records shown · level {level}")
    show_none = st.checkbox("Include records with no class", value=False)
    cols = st.columns(2)
    for col, (key, short) in zip(cols, TAXES.items()):
        counts = df[f"{short} 1"].fillna(NONE).value_counts()
        if not show_none:
            counts = counts.drop(NONE, errors="ignore")
        with col:
            st.subheader("Land use" if key == "landuse" else "Land cover")
            if counts.empty:
                st.info("No classes at this level.")
                continue
            none_n = int(df[f"{short} 1"].isna().sum())
            st.caption(f"{int(counts.drop(NONE, errors='ignore').sum()):,} classified · {none_n:,} with no class")
            st.altair_chart(pie(counts, class_order(str(run_dir), key, level)), width="stretch")
            st.altair_chart(bars(counts), width="stretch")

tab_table.caption(f"{len(df):,} records · top {TOP_N} classes at level {level} · empty = no class scored above 0")

with tab_table:
    prob_cols = {c: st.column_config.ProgressColumn(c, min_value=0.0, max_value=1.0, format="%.2f")
                 for c in df.columns if c.endswith(" p")}
    event = st.dataframe(
        df, hide_index=True, height=560, on_select="rerun", selection_mode="single-row",
        column_config={"abstract": st.column_config.TextColumn("abstract", width="large"), **prob_cols},
    )

    rows = event.selection.rows
    if rows:
        rec = df.iloc[rows[0]]
        st.subheader(rec["title"])
        st.caption(f"id `{rec['id']}` · identifier `{rec['identifier']}`")
        a, b = st.columns(2)
        for col, (key, short) in zip((a, b), TAXES.items()):
            col.markdown(f"**{short}**")
            for r in range(1, TOP_N + 1):
                if pd.notna(rec[f"{short} {r}"]):
                    col.write(f"{r}. {rec[f'{short} {r}']} — {rec[f'{short} {r} p']:.2f}")
        st.write(rec["abstract"])
    else:
        st.caption("Select a row to read the full abstract.")
