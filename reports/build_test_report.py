"""Builds reports/test_500_records.pdf for one run (needs google-chrome).

  .venv/bin/python reports/build_test_report.py [run_id] [reference_run_id]
"""
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from landclass import metrics            # noqa: E402
from landclass.taxonomy import build_taxonomy  # noqa: E402

run_id = sys.argv[1] if len(sys.argv) > 1 else "20261012-151353"
ref_id = sys.argv[2] if len(sys.argv) > 2 else "20261007-162217"
run, ref = ROOT / "runs" / run_id, ROOT / "runs" / ref_id
summ = metrics.run_summary(run)
keys = ("landcover", "landuse")
cc = {k: metrics.label_quality(run, k) for k in keys}
names = {k: {n.code: n.name for n in build_taxonomy(k).roots()} for k in keys}
ag = {k: {l: metrics.agreement(run, ref, k, l) for l in (1, 2, 3)} for k in keys}


def bars(series, nm):
    mx = max(series.values)
    return "".join(f'<tr><td>{c} {nm.get(c, "")}</td><td class="bar"><div style="width:{v / mx * 100:.0f}%"></div></td>'
                   f'<td class="n">{v}</td></tr>' for c, v in series.items())


def prf(a, b):
    tp = len(a & b); fp = len(a - b); fn = len(b - a)
    return tp, fp, fn


ver = pd.read_csv(ROOT / "reports" / "claude_verification_60.csv", keep_default_na=False)
vstats = {}
for short, key in (("lc", "landcover"), ("lu", "landuse")):
    tp = fp = fn = 0
    for c, m in zip(ver[f"claude_{short}"], ver[f"mistral_{short}"]):
        a, b = set(m.split(",")) - {"-"}, set(c.split(",")) - {"-"}
        t, f, n = prf(a, b); tp += t; fp += f; fn += n
    p, r = tp / (tp + fp), tp / (tp + fn)
    vstats[key] = (int(ver[f"{short}_match"].sum()), p, r, 2 * p * r / (p + r))
diffs = ver[~ver["lu_match"]]
u1_over = sum(1 for _, r in diffs.iterrows() if "U1" in r["mistral_lu"].split(",") and "U1" not in r["claude_lu"].split(","))

# ---- land use: fix attempts, scored against Claude's labels on two sets of records
from landclass.config import DEFAULT_THRESHOLDS  # noqa: E402
from landclass.export import load_scores, select  # noqa: E402

fresh = pd.read_csv(ROOT / "reports" / "claude_verification_fresh40_landuse.csv", keep_default_na=False)
sets_ = {"first 60": (ver["id"].tolist(), ver["claude_lu"].tolist()),
         "fresh 40": (fresh["id"].tolist(), fresh["claude_lu"].tolist())}
sets_["all 100"] = (sets_["first 60"][0] + sets_["fresh 40"][0], sets_["first 60"][1] + sets_["fresh 40"][1])
# (name, run, apply the saved gate scores offline?, cost note)
GATE_RUN = "20261012-162611"
attempts = [("Small, original hint, no gate", "20261012-151353", False, "$0.18 (both taxonomies)"),
            ("Small, new U1 hint, no gate", "20261012-160555", False, None),
            ("Small, new U1 hint + gate (current)", GATE_RUN, False, None),
            ("Medium, new U1 hint, no gate", "20261012-161249", False, None),
            ("Medium + gate (offline estimate, not run)", "20261012-161249", True, "about $0.25 + $0.03")]


def lu_sets(run_id):
    sel = select(load_scores(ROOT / "runs" / run_id, "landuse"), DEFAULT_THRESHOLDS)
    return sel[sel["selected"] & (sel["level"] == 1)].groupby("id")["code"].agg(set)


def lu_score(m, ids, labels, gate=None):
    tp = fp = fn = ex = 0
    for i, c in zip(ids, labels):
        a, b = m.get(i, set()), set(c.split(",")) - {"-"}
        if gate is not None and gate[i] < 0.5:
            a = set()
        t, f, n = prf(a, b); tp += t; fp += f; fn += n; ex += a == b
    p, r = tp / (tp + fp), tp / (tp + fn)
    return ex, len(ids), p, r, 2 * p * r / (p + r)


gate_g = pd.read_csv(ROOT / "runs" / GATE_RUN / "gate_landuse.csv")
gate_s = gate_g.set_index("id")["gate"]
n_pass = int((gate_g["gate"] >= 0.5).sum())
fix_rows = ""
for name, rid, use_gate, note in attempts:
    m = lu_sets(rid)
    cost = note or f"${metrics.run_summary(ROOT / 'runs' / rid)['cost_usd']:.3f}"
    cells = ""
    for key, (ids_, labs) in sets_.items():
        ex, n, p, r, f1 = lu_score(m, ids_, labs, gate_s if use_gate else None)
        cells += (f"<td>{ex}/{n}</td><td><b>{f1:.2f}</b></td>" if key != "all 100"
                  else f"<td>{ex}/{n}</td><td>{p:.2f}</td><td>{r:.2f}</td><td><b>{f1:.2f}</b></td>")
    fix_rows += f"<tr><td>{name}</td>{cells}<td>{cost}</td></tr>"

rows = "".join(f'<tr><td>{l}</td>' + "".join(
    f'<td>{ag[k][l]["precision"]:.0%}</td><td>{ag[k][l]["recall"]:.0%}</td><td>{ag[k][l]["f1"]:.2f}</td>'
    f'<td>{ag[k][l]["exact_match"]:.0%}</td>' for k in keys) + '</tr>' for l in (1, 2, 3))
vrows = "".join(f'<tr><td>{nm}</td><td>{vstats[k][0]}/60 ({vstats[k][0] / 60:.0%})</td><td>{vstats[k][1]:.2f}</td>'
                f'<td>{vstats[k][2]:.2f}</td><td><b>{vstats[k][3]:.2f}</b></td></tr>'
                for k, nm in (("landcover", "Land cover"), ("landuse", "Land use")))
dtab = "".join(f'<tr><td>{r["n"]}</td><td>{r["title"][:70]}</td><td>{r["claude_lu"]}</td><td>{r["mistral_lu"]}</td></tr>'
               for _, r in diffs.iterrows())

html = f'''<!doctype html><meta charset=utf-8><title>Test on 500 records</title><style>
body{{font:13px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1d2330;margin:0}}
h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:16px;margin:26px 0 8px;border-bottom:1px solid #d8dde6;padding-bottom:4px}}
.sub{{color:#5b6475}}.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}
.k{{border:1px solid #d8dde6;border-radius:8px;padding:10px 12px}}.k b{{display:block;font-size:20px}}.k span{{color:#5b6475;font-size:11px}}
table{{border-collapse:collapse;width:100%;margin:6px 0}}th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid #e6e9ef}}th{{background:#f3f5f9;font-size:11px;text-transform:uppercase;letter-spacing:.03em}}
td.n{{width:40px;text-align:right}}td.bar{{width:55%}}td.bar div{{height:10px;background:#2a78d6;border-radius:3px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}.note{{background:#f3f5f9;border-radius:8px;padding:10px 12px;margin-top:10px}}
.small td,.small th{{font-size:11px;padding:3px 6px}}.pb{{page-break-before:always}}
@page{{size:A4;margin:16mm}}</style>
<h1>Land cover / land use classifier: test on 500 records</h1>
<div class=sub>Run {run_id} · 500 random records (seed 42) of 25,129 · both taxonomies, depth 3 · mistral-small-latest, 5 records/call, 8 parallel · 12 Oct 2026</div>
<div class=kpis><div class=k><b>{int(summ["wall_seconds"] // 60)} min {int(summ["wall_seconds"] % 60)} s</b><span>total time ({summ["records_per_second"]:.2f} records/s)</span></div>
<div class=k><b>${summ["cost_usd"]:.3f}</b><span>total cost (${summ["cost_per_1000"]:.2f} per 1,000)</span></div>
<div class=k><b>{summ["calls"]}</b><span>API calls</span></div><div class=k><b>{(summ["input_tokens"] + summ["output_tokens"]) // 1000}k</b><span>tokens (about {summ["tokens_per_record"]:,.0f} per record)</span></div></div>
<h2>Time and cost</h2>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Wall time</td><td>{summ["wall_seconds"]:.0f} s ({summ["seconds_per_record"]:.2f} s per record)</td></tr>
<tr><td>Input / output tokens</td><td>{summ["input_tokens"]:,} / {summ["output_tokens"]:,}</td></tr>
<tr><td>Cost per record</td><td>${summ["cost_per_record"]:.5f} (prices: $0.15 / $0.60 per million input / output tokens)</td></tr>
<tr><td>Extrapolated to all 25,129 records</td><td>about {25129 / summ["records_per_second"] / 3600:.1f} h, about ${25129 * summ["cost_per_record"]:.2f}</td></tr></table>
<h2>Label coverage and confidence (default thresholds)</h2>
<table><tr><th></th><th>Land cover</th><th>Land use</th></tr>
<tr><td>Records with at least 1 label</td>{"".join(f'<td>{cc[k]["with_label"]} ({cc[k]["coverage"]:.0%})</td>' for k in keys)}</tr>
<tr><td>Records reaching level 2 / level 3</td>{"".join(f'<td>{cc[k]["reach_level"][2]:.0%} / {cc[k]["reach_level"][3]:.0%}</td>' for k in keys)}</tr>
<tr><td>Labels per record (deepest)</td>{"".join(f'<td>{cc[k]["labels_per_record"]:.2f}</td>' for k in keys)}</tr>
<tr><td>Mean level-1 confidence</td>{"".join(f'<td>{cc[k]["mean_l1_confidence"]:.2f}</td>' for k in keys)}</tr>
<tr><td>Level-1 labels with confidence ≥ 0.8</td>{"".join(f'<td>{cc[k]["high_confidence_share"]:.1%}</td>' for k in keys)}</tr></table>
<div class=cols><div><h2>Land cover: level 1 classes</h2><table>{bars(cc["landcover"]["class_counts"], names["landcover"])}</table></div>
<div><h2>Land use: level 1 classes</h2><table>{bars(cc["landuse"]["class_counts"], names["landuse"])}</table></div></div>
<div class=pb></div>
<h2>Accuracy 1: independent check by Claude (60 records)</h2>
<p>The records table has no human labels. Claude labelled 60 of the 500 records (random, seed 7) at level 1 <b>before</b> seeing Mistral's answers, from the title and the first 650 characters of the abstract (Mistral saw the full text). Mistral's labels use the default thresholds. Details: <code>reports/claude_verification_60.csv</code>.</p>
<table><tr><th>Level 1</th><th>Exact match</th><th>Precision</th><th>Recall</th><th>F1</th></tr>{vrows}</table>
<div class=note><b>Land cover</b> is good: most of the 13 differences are a second class Mistral missed (wetland, shrubland, bare soil); in 3 cases it added one Claude did not.<br>
<b>Land use</b> has a clear problem: Mistral puts U1 (Primary sector) on soil-science records that are not about farming, forestry, fishing or mining (biochar, an E. coli lab column, soil enzymes, a global salinity map). {u1_over} of the {len(diffs)} differences are this, and U1 is 307 of 337 labelled land-use records in the whole run. <b>Suggested fix:</b> tighten the U1 hint in the Labels tab; a changed hint reclassifies the records once (about $0.18 per 500).<br>
<b>Limits:</b> one annotator (some labels are judgment calls), level 1 only, small sample. This is a second opinion from a stronger model, not human ground truth.</div>
<h2>Land use: the {len(diffs)} differences</h2>
<table class=small><tr><th>#</th><th>Title</th><th>Claude</th><th>Mistral</th></tr>{dtab}</table>
<div class=pb></div>
<h2>Land use: fixing the "Primary sector" over-labelling</h2>
<p>Mistral Small puts U1 (Primary sector) on soil-science records that are not about farming, forestry, fishing or mining. Five setups (the last is an offline estimate) were scored against Claude's level-1 labels on two sets, and their union: the <b>first 60</b> records (used to tune the hint and the gate wording, so slightly optimistic) and <b>40 fresh</b> records labelled blind afterwards (the fairer test). Gate = one extra cheap call per record asking whether it concerns land that is actually used or unused; records scoring below 0.5 get no land use label.</p>
<table class=small><tr><th rowspan=2>Setup</th><th colspan=2>First 60</th><th colspan=2>Fresh 40</th><th colspan=4>All 100</th><th rowspan=2>Cost (500 records, land use)</th></tr>
<tr><th>Exact</th><th>F1</th><th>Exact</th><th>F1</th><th>Exact</th><th>Prec.</th><th>Recall</th><th>F1</th></tr>{fix_rows}</table>
<div class=note><b>Result:</b> the tighter hint and the gate each help a little. Small goes from F1 0.59 (original) to 0.64 (hint + gate) over all 100 records. <b>Mistral Medium is better: F1 0.69 over all 100 (0.71 on the fresh 40), mainly through higher recall (0.80 vs 0.65), at about 2.5x the land use cost</b> ($0.25 vs $0.10 per 500 records; roughly $12 vs $5 for all 25,129 records). Medium plus the gate gives the best exact match (74/100) at the same F1. Small was kept as the default for cost; this table is the evidence if that decision is revisited. Medium still puts U1 on soil-science records, and the gate passed {n_pass} of 500 records and still lets some datasets, maps and project reports through. The first 60 records were also used to tune the hint and gate wording, so the fresh 40 are the fairer test. Run-to-run variation is about ±0.03 F1. The labels are one reviewer's (Claude), not human ground truth. Details: <code>reports/claude_verification_60.csv</code>, <code>reports/claude_verification_fresh40_landuse.csv</code>.</div>
<h2>Accuracy 2: agreement with an earlier run</h2>
<p>Agreement with run {ref_id} (1 record per call) on the 100 records both runs contain. The reference is not human-verified: this measures consistency, not correctness. Precision, recall and F1 treat the reference labels as truth.</p>
<table><tr><th rowspan=2>Level</th><th colspan=4>Land cover</th><th colspan=4>Land use</th></tr>
<tr><th>Prec.</th><th>Recall</th><th>F1</th><th>Exact</th><th>Prec.</th><th>Recall</th><th>F1</th><th>Exact</th></tr>{rows}</table>
'''
out = ROOT / "reports"
(out / "_tmp.html").write_text(html)
subprocess.run(["google-chrome", "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                f"--print-to-pdf={out / 'test_500_records.pdf'}", str(out / "_tmp.html")], check=True,
               capture_output=True)
(out / "_tmp.html").unlink()
print(out / "test_500_records.pdf")
