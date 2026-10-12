"""Charts for the README (docs/img/*.png) from run 20261012-151353 and reports/claude_verification_60.csv.

  .venv/bin/python docs/make_charts.py
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from landclass import metrics                      # noqa: E402
from landclass.taxonomy import build_taxonomy      # noqa: E402

RUN = ROOT / "runs" / "20261012-151353"
REF = ROOT / "runs" / "20261007-162217"
OUT = ROOT / "docs" / "img"
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
BLUE, ORANGE = "#2a78d6", "#eb6834"      # categorical slots 1 and 2
TAX = {"landcover": "Land cover", "landuse": "Land use"}

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "text.color": INK, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": GRID,
                     "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def style(ax, grid="y"):
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    if grid:
        ax.grid(axis=grid, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig, name):
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    print(OUT / name)


# 1. level-1 class distribution (one measure, one hue, sorted)
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [8, 4]})
for ax, key in zip(axes, TAX):
    counts = metrics.label_quality(RUN, key)["class_counts"]
    names = {n.code: n.name for n in build_taxonomy(key).roots()}
    labels = [f"{c} {names[c]}" for c in counts.index]
    ax.barh(labels[::-1], counts.values[::-1], color=BLUE, height=0.55)
    for y, v in enumerate(counts.values[::-1]):
        ax.text(v + counts.max() * 0.015, y, str(v), va="center", color=INK, fontsize=9)
    ax.set_title(f"{TAX[key]}: records per level-1 class", loc="left", fontsize=11, fontweight="bold")
    ax.set_xlim(0, counts.max() * 1.12)
    ax.set_xticks([])
    style(ax, grid=None)
fig.suptitle("500 records, default thresholds (a record can have several labels)", x=0.01, ha="left",
             fontsize=9, color=MUTED, y=-0.02)
fig.tight_layout()
save(fig, "class_distribution.png")

# 2. depth reached
fig, ax = plt.subplots(figsize=(6.4, 3.6))
x = range(3)
w = 0.36
for off, (key, col) in zip((-w / 2, w / 2), zip(TAX, (BLUE, ORANGE))):
    r = metrics.label_quality(RUN, key)["reach_level"]
    vals = [r[l] * 100 for l in (1, 2, 3)]
    bars = ax.bar([i + off for i in x], vals, w - 0.03, color=col, label=TAX[key])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}%", ha="center", fontsize=9)
ax.set_xticks(list(x), ["Level 1", "Level 2", "Level 3"])
ax.set_ylim(0, 85)
ax.set_ylabel("% of the 500 records")
ax.set_title("Records that get a label at each depth", loc="left", fontsize=11, fontweight="bold")
ax.legend(frameon=False, loc="upper right")
style(ax)
save(fig, "depth_reached.png")

# 3. Claude check: precision / recall / F1 per taxonomy
ver = pd.read_csv(ROOT / "reports" / "claude_verification_60.csv", keep_default_na=False)
res = {}
for short, key in (("lc", "landcover"), ("lu", "landuse")):
    tp = fp = fn = 0
    for c, m in zip(ver[f"claude_{short}"], ver[f"mistral_{short}"]):
        a, b = set(m.split(",")) - {"-"}, set(c.split(",")) - {"-"}
        tp += len(a & b); fp += len(a - b); fn += len(b - a)
    p, r = tp / (tp + fp), tp / (tp + fn)
    res[key] = {"Precision": p, "Recall": r, "F1": 2 * p * r / (p + r), "Exact match": ver[f"{short}_match"].mean()}
fig, ax = plt.subplots(figsize=(7, 3.8))
metrics_ = ["Precision", "Recall", "F1", "Exact match"]
for off, (key, col) in zip((-w / 2, w / 2), zip(TAX, (BLUE, ORANGE))):
    vals = [res[key][m] for m in metrics_]
    bars = ax.bar([i + off for i in range(4)], vals, w - 0.03, color=col, label=TAX[key])
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=9)
ax.set_xticks(range(4), metrics_)
ax.set_ylim(0, 1.05)
ax.set_title("Mistral Small vs Claude's labels (60 records, level 1)", loc="left", fontsize=11, fontweight="bold")
ax.legend(frameon=False, loc="upper right", ncol=2, bbox_to_anchor=(1, 1.02))
style(ax)
save(fig, "claude_check.png")

# 4. land use: why precision is low (kinds of difference)
lu = ver[~ver["lu_match"]]
extra_u1 = sum(1 for _, r in lu.iterrows() if "U1" in r["mistral_lu"].split(",") and "U1" not in r["claude_lu"].split(","))
other = len(lu) - extra_u1
fig, ax = plt.subplots(figsize=(6.4, 2.8))
vals = [("Agree", int(ver["lu_match"].sum()), "#9a9890"), ("Mistral added U1 (Primary sector)", extra_u1, ORANGE),
        ("Other differences", other, BLUE)]
left = 0
for label, v, col in vals:
    ax.barh([0], [v], left=left, color=col, height=0.5, edgecolor=SURFACE, linewidth=2)
    ax.text(left + v / 2, 0, str(v), ha="center", va="center", color="white", fontweight="bold")
    left += v
ax.set_xlim(0, 60); ax.set_yticks([]); ax.set_xticks([])
ax.set_title("Land use: 60 records, Claude vs Mistral", loc="left", fontsize=11, fontweight="bold")
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in vals], labels=[l for l, _, _ in vals],
          frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=3, fontsize=8.5)
for s in ax.spines.values():
    s.set_visible(False)
save(fig, "land_use_differences.png")

# 5. land use setups: F1 against Claude's labels on 100 records (60 + 40 fresh)
from landclass.export import load_scores, select   # noqa: E402
from landclass.config import DEFAULT_THRESHOLDS     # noqa: E402

fresh = pd.read_csv(ROOT / "reports" / "claude_verification_fresh40_landuse.csv", keep_default_na=False)
ids100 = ver["id"].tolist() + fresh["id"].tolist()
labs100 = ver["claude_lu"].tolist() + fresh["claude_lu"].tolist()
gate_s = pd.read_csv(ROOT / "runs" / "20261012-162611" / "gate_landuse.csv").set_index("id")["gate"]


def f1_for(run_id, use_gate=False):
    sel = select(load_scores(ROOT / "runs" / run_id, "landuse"), DEFAULT_THRESHOLDS)
    m = sel[sel["selected"] & (sel["level"] == 1)].groupby("id")["code"].agg(set)
    tp = fp = fn = 0
    for i, c in zip(ids100, labs100):
        a, b = m.get(i, set()), set(c.split(",")) - {"-"}
        if use_gate and gate_s[i] < 0.5:
            a = set()
        tp += len(a & b); fp += len(a - b); fn += len(b - a)
    p, r = tp / (tp + fp), tp / (tp + fn)
    return 2 * p * r / (p + r)


setups = [("Small, original hint", f1_for("20261012-151353"), "about $0.09", BLUE),
          ("Small, tighter U1 hint", f1_for("20261012-160555"), "$0.085", BLUE),
          ("Small, hint + gate (current)", f1_for("20261012-162611"), "$0.10", BLUE),
          ("Medium, hint", f1_for("20261012-161249"), "$0.25", ORANGE),
          ("Medium, hint + gate (estimate)", f1_for("20261012-161249", True), "about $0.28", ORANGE)]
fig, ax = plt.subplots(figsize=(8, 3.6))
ys = list(range(len(setups)))[::-1]
for y, (name, f1, cost, col) in zip(ys, setups):
    ax.barh(y, f1, color=col, height=0.55)
    ax.text(f1 + 0.01, y, f"F1 {f1:.2f}  ·  {cost} per 500", va="center", fontsize=9)
ax.set_yticks(ys, [s[0] for s in setups])
ax.set_xlim(0, 1.0); ax.set_xticks([])
ax.set_title("Land use fixes: F1 vs Claude's labels (100 records)", loc="left", fontsize=11, fontweight="bold")
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=BLUE), plt.Rectangle((0, 0), 1, 1, color=ORANGE)],
          labels=["Mistral Small", "Mistral Medium"], frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, fontsize=9)
style(ax, grid=None)
save(fig, "land_use_fixes.png")
