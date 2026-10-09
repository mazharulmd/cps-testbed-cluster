"""Draw the paper's result figures from the files in ../data.

Usage: python make_figures.py
Each figure is written as its own PDF in ../figures (vector, 300 dpi for any raster part).
"""
import csv
import json
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
FIG = os.path.join(HERE, "..", "figures")
ROOT = os.path.join(HERE, "..", "..")
W = 3.45            # IEEE column width (in)
plt.rcParams.update({
    "font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8, "axes.labelsize": 8,
    "legend.fontsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7, "lines.linewidth": 1.0,
    "axes.linewidth": 0.6, "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.02})


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def series(name):
    r = rows(os.path.join(DATA, f"series_{name}.csv"))
    tr = np.array([[float(x["t"]), float(x["v49"])] for x in r if x["kind"] == "truth"])
    st = np.array([[float(x["t"]), float(x["v49"]), float(x["J"]), float(x["threshold"])]
                   for x in r if x["kind"] == "set"])
    return tr, st


def save(fig, name):
    fig.savefig(os.path.join(FIG, name))
    plt.close(fig)


def attack_window(ax):
    ax.axvspan(4, 9, color="0.92", lw=0, zorder=0)


def clipped(m, e, lo=0.0, hi=100.0):
    """Asymmetric error bars that stay inside [lo, hi] (shares in percent)."""
    m, e = np.asarray(m), np.asarray(e)
    return [m - np.maximum(m - e, lo), np.minimum(m + e, hi) - m]


def ci95(x):
    x = np.asarray(x, float)
    if len(x) < 2 or np.all(x == x[0]):
        return 0.0
    return stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


RUNS = rows(os.path.join(DATA, "runs.csv"))


def by(scen, key):
    return np.array([float(r[key]) for r in RUNS if r["scenario"] == scen and r[key] != ""])


# ---------------------------------------------------------------- bus 49, closed loop
fig, ax = plt.subplots(figsize=(W, 1.85))
tr, _ = series("noctl")
ax.step(tr[:, 0], tr[:, 1], where="post", color="0.5", ls="--", label="true, control off")
tr, st = series("ctl")
ax.step(tr[:, 0], tr[:, 1], where="post", color="C0", label="true, control on")
ax.plot(st[:, 0], st[:, 1], color="C3", lw=0.7, label="estimated, control on")
ax.axhline(1.08, color="k", ls=":", lw=0.7)
ax.set_xlim(0, 10); ax.set_xlabel("time (s)"); ax.set_ylabel("$|V_{49}|$ (pu)")
ax.legend(loc="upper right", frameon=False)
save(fig, "fig_v49_control.pdf")

# ---------------------------------------------------------------- bus 49, estimates under attack
fig, ax = plt.subplots(figsize=(W, 1.85))
attack_window(ax)
tr, _ = series("ctl")
ax.step(tr[:, 0], tr[:, 1], where="post", color="0.6", ls="--", label="true, no attack")
for n, c, lab in (("simple-min", "C0", "simple FDI"), ("stealthy-min", "C1", "stealthy FDI"),
                  ("delay-min", "C2", "delay 100 ms")):
    _, st = series(n)
    ax.plot(st[:, 0], st[:, 1], color=c, lw=0.8, label=f"estimated, {lab}")
ax.axhline(1.08, color="k", ls=":", lw=0.7)
ax.set_xlim(0, 10); ax.set_xlabel("time (s)"); ax.set_ylabel("$|\\hat V_{49}|$ (pu)")
ax.legend(loc="upper right", frameon=False, fontsize=6.5)
save(fig, "fig_v49_attacks.pdf")

# ---------------------------------------------------------------- chi-square statistic
fig, ax = plt.subplots(figsize=(W, 1.85))
attack_window(ax)
for n, c, lab in (("simple-min", "C0", "simple FDI, 32 PMUs"), ("simple-red", "C3", "simple FDI, 68 PMUs"),
                  ("stealthy-min", "C1", "stealthy FDI, 32 PMUs")):
    _, st = series(n)
    ax.plot(st[:, 0], st[:, 2], color=c, lw=0.8, label=lab)
    ax.axhline(st[0, 3], color=c, ls="--", lw=0.6)
ax.set_yscale("log"); ax.set_xlim(0, 10)
ax.set_xlabel("time (s)"); ax.set_ylabel("$J$ before removal")
ax.legend(loc="upper right", frameon=False, fontsize=6.5)
save(fig, "fig_chi2.pdf")

# ---------------------------------------------------------------- voltage profile of one set
p = rows(os.path.join(DATA, "profile_simple-min.csv"))
bus = np.array([int(r["bus"]) for r in p])
fig, ax = plt.subplots(figsize=(W, 1.85))
ax.plot(bus, [float(r["true"]) for r in p], color="0.55", lw=0.9, label="true")
pm = [(int(r["bus"]), float(r["pmu"])) for r in p if r["pmu"]]
ax.plot([b for b, _ in pm], [v for _, v in pm], "o", ms=2.6, mfc="none", mec="C0", mew=0.7, label="PMU reading")
ax.plot(bus, [float(r["estimate"]) for r in p], color="C3", lw=0.7, ls="--", label="estimate")
b49 = [r for r in p if r["bus"] == "49"][0]
ax.annotate("PMU 49", (49, float(b49["pmu"])), xytext=(62, 1.06), fontsize=6.5,
            arrowprops=dict(arrowstyle="-", lw=0.5))
ax.axhline(1.08, color="k", ls=":", lw=0.7); ax.axhline(0.94, color="k", ls=":", lw=0.7)
ax.set_xlim(0, 119); ax.set_xlabel("bus"); ax.set_ylabel("$|V|$ (pu)")
ax.set_ylim(0.93, 1.15)
ax.legend(loc="upper right", frameon=False, ncol=3, fontsize=6.5)
save(fig, "fig_profile.pdf")

# ---------------------------------------------------------------- violation time over seeds
cases = [("noctl", "no control"), ("ctl", "control, no attack"), ("simple-min", "simple FDI"),
         ("simple-nobdd", "simple FDI, no removal"), ("stealthy-min", "stealthy FDI"),
         ("delay-min", "delay"), ("drop-min", "drop"), ("loss5-min", "5% loss"),
         ("simple-red", "simple FDI"), ("stealthy-red", "stealthy FDI"), ("delay-red", "delay"),
         ("drop-red", "drop"), ("loss5-red", "5% loss")]
fig, ax = plt.subplots(figsize=(W, 2.3))
y = np.arange(len(cases))[::-1]
for yi, (s, lab) in zip(y, cases):
    v = by(s, "violation_s")
    col = "C0" if s.endswith("-red") else ("0.5" if s in ("noctl", "ctl") else "C3")
    ax.barh(yi, v.mean(), xerr=ci95(v), color=col, height=0.62, error_kw=dict(lw=0.7, capsize=1.5))
    ax.text(v.mean() + 0.12, yi, f"{v.mean():.1f}", va="center", fontsize=6)
ax.set_yticks(y); ax.set_yticklabels([c[1] for c in cases], fontsize=6.5)
ax.axhline(y[7] - 0.5, color="k", lw=0.5)
ax.text(6.9, y[2], "32 PMUs", ha="right", fontsize=6.5, color="C3")
ax.text(6.9, y[9], "68 PMUs", ha="right", fontsize=6.5, color="C0")
ax.set_xlim(0, 7.2); ax.set_xlabel("violation time (s), mean over 10 seeds")
save(fig, "fig_violation.pdf")

# ---------------------------------------------------------------- latency sweep
L = [5, 10, 20, 40, 80]
names = {5: "lat5", 10: "ctl", 20: "lat20", 40: "lat40", 80: "lat80"}
fig, ax = plt.subplots(figsize=(W, 1.85))
for key, c, lab in (("frames_in_time_pct", "C0", "frames in time"), ("complete_pct", "C3", "complete sets")):
    m = [by(names[l], key).mean() for l in L]
    e = [ci95(by(names[l], key)) for l in L]
    ax.errorbar(L, m, yerr=clipped(m, e), color=c, marker="o", ms=3, capsize=2, lw=0.9, label=lab)
ax.set_xscale("log"); ax.set_xticks(L); ax.set_xticklabels([str(l) for l in L])
ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
ax.set_xlabel("mean link latency $L$ (ms), PDC wait $w$ = 20 ms"); ax.set_ylabel("share (%)")
ax.set_ylim(-5, 105); ax.legend(loc="lower left", frameon=False)
save(fig, "fig_latency.pdf")

# ---------------------------------------------------------------- PDC wait window sweep at L = 40 ms
Wn = [10, 20, 40, 60, 80]
names = {10: "lat40-w10", 20: "lat40", 40: "lat40-w40", 60: "lat40-w60", 80: "lat40-w80"}
fig, ax = plt.subplots(figsize=(W, 1.85))
m = [by(names[w], "complete_pct").mean() for w in Wn]
e = [ci95(by(names[w], "complete_pct")) for w in Wn]
ax.errorbar(Wn, m, yerr=clipped(m, e), color="C3", marker="o", ms=3, capsize=2, lw=0.9, label="complete sets")
ax.set_xlabel("PDC wait window $w$ (ms), $L$ = 40 ms"); ax.set_ylabel("complete sets (%)", color="C3")
ax.set_ylim(-5, 105)
ax2 = ax.twinx()
m = [by(names[w], "pdc_release_ms").mean() for w in Wn]
ax2.plot(Wn, m, color="C0", marker="s", ms=3, lw=0.9)
ax2.set_ylabel("PDC release delay (ms)", color="C0")
ax2.set_ylim(0, 100)
save(fig, "fig_pdc_wait.pdf")


# ---------------------------------------------------------------- PMU placements
def placement_figure(pm, fname):
    import networkx as nx
    t = json.load(open(os.path.join(ROOT, "cases", "ieee118", "topology.json")))
    G = nx.Graph()
    G.add_nodes_from(b["id"] for b in t["buses"])
    G.add_edges_from((br["from"], br["to"]) for br in t["branches"] if br["status"])
    gens = {g["bus"] for g in t["gens"] if g["status"]}
    pos = nx.kamada_kawai_layout(G)
    fig, a = plt.subplots(figsize=(W, 2.9))
    nx.draw_networkx_edges(G, pos, ax=a, width=0.5, edge_color="0.65")
    other = [n for n in G if n not in pm]
    kw = dict(ax=a, linewidths=0.5)
    nx.draw_networkx_nodes(G, pos, nodelist=[n for n in other if n not in gens], node_size=9,
                           node_color="white", edgecolors="0.35", **kw)
    nx.draw_networkx_nodes(G, pos, nodelist=[n for n in other if n in gens], node_size=11, node_shape="s",
                           node_color="white", edgecolors="0.35", **kw)
    nx.draw_networkx_nodes(G, pos, nodelist=[n for n in pm if n not in gens], node_size=16,
                           node_color="C0", edgecolors="k", **kw)
    nx.draw_networkx_nodes(G, pos, nodelist=[n for n in pm if n in gens], node_size=18, node_shape="s",
                           node_color="C0", edgecolors="k", **kw)
    nx.draw_networkx_nodes(G, pos, nodelist=[49], ax=a, node_size=70, node_color="none",
                           edgecolors="C3", linewidths=1.1)
    nx.draw_networkx_labels(G, {49: (pos[49][0] + 0.07, pos[49][1] + 0.07)}, labels={49: "49"}, ax=a,
                            font_size=7, font_color="C3")
    from matplotlib.lines import Line2D
    h = [Line2D([], [], marker="o", ls="", mfc="C0", mec="k", ms=4, label=f"PMU ({len(pm)})"),
         Line2D([], [], marker="o", ls="", mfc="white", mec="0.35", ms=4, label="no PMU"),
         Line2D([], [], marker="s", ls="", mfc="white", mec="0.35", ms=4, label="generator bus"),
         Line2D([], [], marker="o", ls="", mfc="none", mec="C3", ms=7, label="bus 49")]
    a.legend(handles=h, loc="lower center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.1), fontsize=6.5)
    a.axis("off"); a.margins(0.01)
    save(fig, fname)


pl = {r["placement"]: r["pmus"].split() for r in rows(os.path.join(DATA, "placement.csv"))}
placement_figure([int(b) for b in pl["minimum"]], "fig_placement_min.pdf")
placement_figure([int(b) for b in pl["redundant"]], "fig_placement_red.pdf")
print("figures written to", os.path.abspath(FIG))
