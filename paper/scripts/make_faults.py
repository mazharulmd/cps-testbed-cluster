"""Table and figure of the fault campaign: violation time for every fault type and attack.

Usage: python make_faults.py
Reads ../data/faults.csv (load step, line trip, generator trip, bus fault) and ../data/runs.csv
(AVR fault, seeds 1-5 so that every fault has the same number of seeds).
Writes ../tables/tab_faults.tex and ../figures/fig_fault_impact.pdf.
"""
import csv
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, TAB, FIG = (os.path.join(HERE, "..", d) for d in ("data", "tables", "figures"))
plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8,
                     "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.02})


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


EVENTS = [("avr49", "AVR fault, gen.~49", "AVR fault"), ("load53", "Load step +200\\%, bus 53", "load step"),
          ("line7677", "Line trip 76--77", "line trip"), ("gen80", "Generator trip, bus 80", "gen. trip"),
          ("fault49", "Bus fault 49, 0.1\\,s", "bus fault")]
SCEN = [("noctl", "No ctrl"), ("ctl", "Ctrl"), ("simple-min", "Simple"), ("simple-nobdd", "Simple, no rem."),
        ("stealthy-min", "Stealthy"), ("delay-min", "Delay"), ("drop-min", "Drop"),
        ("simple-red", "Simple"), ("stealthy-red", "Stealthy"), ("delay-red", "Delay"), ("drop-red", "Drop")]

V = {}
for r in rows(os.path.join(DATA, "faults.csv")):
    V.setdefault((r["event"], r["scenario"]), []).append(float(r["violation_s"]))
for r in rows(os.path.join(DATA, "runs.csv")):
    if int(r["seed"]) <= 5:
        V.setdefault(("avr49", r["scenario"]), []).append(float(r["violation_s"]))


def cell(ev, sc):
    x = np.array(V.get((ev, sc), []))
    if len(x) == 0:
        return "--"
    if np.allclose(x, x[0]):
        return f"{x[0]:.2f}"
    return f"{x.mean():.2f}\\,$\\pm$\\,{x.std(ddof=1):.2f}"


# ---------------------------------------------------------------- table
t = [r"\begin{table*}[t]",
     r"\caption{Violation Time (s) for Every Fault Type and Attack, IEEE 118-Bus System. Mean $\pm$ Standard Deviation "
     r"Over Five Seeds; a Single Value Means All Seeds Agreed}", r"\label{tab:faults}", r"\centering", r"\footnotesize",
     r"\setlength{\tabcolsep}{3.2pt}", r"\begin{tabular}{@{}l" + "c" * len(SCEN) + "@{}}", r"\toprule",
     r" & \multicolumn{2}{c}{Baselines} & \multicolumn{5}{c}{32 PMUs} & \multicolumn{4}{c}{68 PMUs} \\",
     r"\cmidrule(lr){2-3}\cmidrule(lr){4-8}\cmidrule(l){9-12}",
     "Fault & " + " & ".join(lab for _, lab in SCEN) + r" \\", r"\midrule"]
for ev, lab, _ in EVENTS:
    t.append(lab + " & " + " & ".join(cell(ev, sc) for sc, _ in SCEN) + r" \\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
with open(os.path.join(TAB, "tab_faults.tex"), "w") as f:
    f.write("\n".join(t))

# ---------------------------------------------------------------- figure: extra violation caused by each attack
ATT = SCEN[2:]
D = np.array([[np.mean(V[(ev, sc)]) - np.mean(V[(ev, "ctl")]) if (ev, sc) in V else np.nan for sc, _ in ATT]
              for ev, _, _ in EVENTS])
fig, ax = plt.subplots(figsize=(3.45, 1.95))
lim = max(1.0, np.nanmax(np.abs(D)))
im = ax.imshow(D, cmap="RdBu_r", norm=TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim), aspect="auto")
for i in range(D.shape[0]):
    for j in range(D.shape[1]):
        if np.isfinite(D[i, j]):
            ax.text(j, i, f"{D[i, j]:+.2f}" if abs(D[i, j]) >= 0.005 else "0", ha="center", va="center", fontsize=5.5,
                    color="white" if abs(D[i, j]) > 0.6 * lim else "0.15")
ax.set_xticks(range(len(ATT)))
ax.set_xticklabels([lab for _, lab in ATT], rotation=55, ha="right", fontsize=6.5)
ax.set_yticks(range(len(EVENTS)))
ax.set_yticklabels([short for _, _, short in EVENTS], fontsize=7)
ax.axvline(4.5, color="k", lw=0.8)
ax.text(2.0, -0.85, "32 PMUs", ha="center", fontsize=6.5)
ax.text(7.5, -0.85, "68 PMUs", ha="center", fontsize=6.5)
ax.tick_params(length=0)
for sp in ax.spines.values():
    sp.set_visible(False)
cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
cb.set_label("extra violation (s)", fontsize=6.5)
cb.ax.tick_params(labelsize=6)
fig.savefig(os.path.join(FIG, "fig_fault_impact.pdf"))
# exact permutation tests of each attack against the attack-free control, per fault
from scipy import stats
with open(os.path.join(TAB, "fault_tests.txt"), "w") as f:
    for ev, _, _ in EVENTS:
        a = np.array(V[(ev, "ctl")])
        for sc, _ in ATT:
            b = np.array(V.get((ev, sc), []))
            if len(b) == 0:
                continue
            if np.allclose(np.r_[a, b], a[0]):
                p = 1.0
            else:
                p = stats.permutation_test((a, b), lambda x, y: np.mean(x) - np.mean(y),
                                           permutation_type="independent", n_resamples=np.inf).pvalue
            f.write(f"{ev} {sc}: ctl={a.mean():.3f} attack={b.mean():.3f} diff={b.mean() - a.mean():+.3f} p={p:.4f}\n")
print("tab_faults.tex, fig_fault_impact.pdf and fault_tests.txt written")


# ---------------------------------------------------------------- dynamic-mode figures (seed 1)
def dyn(ev, sc):
    r = rows(os.path.join(DATA, f"series_dyn_{ev}_{sc}.csv"))
    cols = list(r[0].keys())
    return {c: np.array([float(x[c]) if x[c] != "" else np.nan for x in r]) for c in cols}


W = 3.45
plt.rcParams.update({"axes.labelsize": 8, "legend.fontsize": 6.5, "xtick.labelsize": 7, "ytick.labelsize": 7,
                     "lines.linewidth": 1.0, "axes.linewidth": 0.6})

# bus fault at bus 49: faulted bus and the bus that over-shoots after clearing
fig, ax = plt.subplots(figsize=(W, 1.9))
for sc, ls, tag in (("noctl", "--", "no control"), ("ctl", "-", "control")):
    d = dyn("fault49", sc)
    ax.plot(d["t"], d["v49"], color="C0", ls=ls, label=f"bus 49, {tag}")
    ax.plot(d["t"], d["v66"], color="C3", ls=ls, label=f"bus 66, {tag}")
for v in (0.94, 1.08):
    ax.axhline(v, color="k", ls=":", lw=0.6)
ax.set_xlim(3.9, 7.0); ax.set_ylim(0.88, 1.12)
ax.text(4.15, 0.895, "during the fault: bus 49 at 0, bus 66 at 0.57 pu", fontsize=6)
ax.set_xlabel("time (s)"); ax.set_ylabel("$|V|$ (pu)")
ax.legend(loc="center right", frameon=False, ncol=1, fontsize=6, bbox_to_anchor=(1.0, 0.42))
fig.savefig(os.path.join(FIG, "fig_dyn_busfault.pdf")); plt.close(fig)

# generator trip at bus 80: voltage of bus 76 with and without control
fig, ax = plt.subplots(figsize=(W, 1.75))
for sc, ls, tag in (("noctl", "--", "no control"), ("ctl", "-", "control")):
    d = dyn("gen80", sc)
    ax.plot(d["t"], d["v76"], color="C0" if sc == "ctl" else "0.5", ls=ls, label=f"bus 76, {tag}")
ax.axhline(0.94, color="k", ls=":", lw=0.6)
ax.set_xlim(3, 10); ax.set_xlabel("time (s)"); ax.set_ylabel("$|V_{76}|$ (pu)")
ax.legend(loc="lower right", frameon=False)
fig.savefig(os.path.join(FIG, "fig_dyn_gentrip_voltage.pdf")); plt.close(fig)

# generator trip at bus 80: centre-of-inertia frequency and lowest machine frequency
fig, ax = plt.subplots(figsize=(W, 1.75))
d = dyn("gen80", "ctl")
ax.plot(d["t"], d["f_coi_hz"], color="C0", label="centre of inertia")
ax.plot(d["t"], d["f_min_hz"], color="C1", lw=0.8, label="lowest machine")
ax.set_xlim(3, 10); ax.set_xlabel("time (s)"); ax.set_ylabel("frequency (Hz)")
ax.legend(loc="upper right", frameon=False)
fig.savefig(os.path.join(FIG, "fig_dyn_gentrip_frequency.pdf")); plt.close(fig)
print("dynamic figures written")
