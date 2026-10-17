"""Table and figure of the location campaign, from ../data/locations.csv.

Usage: python make_locations.py
Writes ../tables/tab_locations.tex, ../tables/locations.txt (numbers quoted in the text) and
../figures/fig_locations.pdf.
"""
import collections
import csv
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
DATA, TAB, FIG = (os.path.join(HERE, "..", d) for d in ("data", "tables", "figures"))
plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 8,
                     "savefig.dpi": 300, "savefig.bbox": "tight", "savefig.pad_inches": 0.02})

rows = list(csv.DictReader(open(os.path.join(DATA, "locations.csv"))))
V = collections.defaultdict(dict)
info = {}
for r in rows:
    k = (r["kind"], int(r["bus"]))
    V[k][r["scenario"]] = float(r["violation_s"])
    info[k] = r
locs = sorted((k for k in V if "noctl" in V[k]), key=lambda k: (k[0], int(info[k]["degree"]), k[1]))
# a location tells something about the attacks only if control shortens the violation there
useful = [k for k in locs if V[k]["ctl"] < V[k]["noctl"] - 0.25]
ATT = [("simple", "Simple FDI"), ("stealthy", "Stealthy FDI"), ("delay", "Delay"), ("drop", "Drop")]
TICK = ["Simple\nFDI", "Stealthy\nFDI", "Delay", "Drop"]


def extended(k, sc):
    return V[k][sc] > V[k]["ctl"] + 0.25


# ---------------------------------------------------------------- table
t = [r"\begin{table*}[t]",
     r"\caption{Violation Time (s) at 20 Fault Locations, IEEE 118-Bus System, Seed 1. Attacks Target the Faulted Bus "
     r"From 4 to 9\,s. Bold: the Attack Extended the Violation Beyond the Attack-Free Control}",
     r"\label{tab:locations}", r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{3.4pt}",
     r"\begin{tabular}{@{}lccccccccccccc@{}}", r"\toprule",
     r" & & \multicolumn{2}{c}{PMUs seeing bus} & \multicolumn{3}{c}{No attack} & \multicolumn{4}{c}{32 PMUs} & "
     r"\multicolumn{4}{c}{68 PMUs} \\",
     r"\cmidrule(lr){3-4}\cmidrule(lr){5-7}\cmidrule(lr){8-11}\cmidrule(l){12-15}".replace("{12-15}", "{12-14}"),
     r"Fault & Degree & 32 & 68 & No ctrl & Dispatch & Telemetry & Simple & Stealthy & Delay & Drop & "
     r"Simple & Stealthy & Delay & Drop \\", r"\midrule"]
t[6] = r"\begin{tabular}{@{}lcccccccccccccc@{}}"
t[9] = r"\cmidrule(lr){3-4}\cmidrule(lr){5-7}\cmidrule(lr){8-11}\cmidrule(l){12-15}"


def cell(k, sc):
    if sc not in V[k]:
        return "--"
    v = f"{V[k][sc]:.1f}"
    return rf"\textbf{{{v}}}" if k in useful and sc not in ("noctl", "ctl", "scada") and extended(k, sc) else v


for k in locs:
    lab = f"AVR, gen.\\ {k[1]}" if k[0] == "avr" else f"Load step, bus {k[1]}"
    r = info[k]
    t.append(f"{lab} & {r['degree']} & {r['pmus_seeing_min']} & {r['pmus_seeing_red']} & " +
             " & ".join(cell(k, sc) for sc in ["noctl", "ctl", "scada"] +
                        [f"{a}-min" for a, _ in ATT] + [f"{a}-red" for a, _ in ATT]) + r" \\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
with open(os.path.join(TAB, "tab_locations.tex"), "w") as f:
    f.write("\n".join(t))

# ---------------------------------------------------------------- figure: share of locations where each attack worked
share = {p: [100 * np.mean([extended(k, f"{a}-{p}") for k in useful]) for a, _ in ATT] for p in ("min", "red")}
fig, ax = plt.subplots(figsize=(3.45, 1.8))
x = np.arange(len(ATT))
w = 0.36
for off, p, col, lab in ((-w / 2, "min", "#2a6fb0", "32 PMUs"), (w / 2, "red", "#e07b2a", "68 PMUs")):
    bars = ax.bar(x + off, share[p], width=w - 0.03, color=col, label=lab)
    for b, v in zip(bars, share[p]):
        ax.text(b.get_x() + b.get_width() / 2, v + 2, f"{round(v / 100 * len(useful))}", ha="center", fontsize=6.5)
ax.set_xticks(x)
ax.set_xticklabels(TICK, fontsize=7)
ax.set_ylim(0, 128)
ax.set_ylabel(f"attack worked (% of\n{len(useful)} locations)")
ax.set_yticks([0, 25, 50, 75, 100])
ax.legend(loc="upper center", frameon=False, fontsize=7, ncol=2, bbox_to_anchor=(0.5, 1.04))
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
fig.savefig(os.path.join(FIG, "fig_locations.pdf"))

with open(os.path.join(TAB, "locations.txt"), "w") as f:
    f.write(f"locations {len(locs)}, informative {len(useful)}: {useful}\n")
    for a, _ in ATT:
        for p in ("min", "red"):
            ok = [k for k in useful if extended(k, f"{a}-{p}")]
            f.write(f"{a}-{p}: worked at {len(ok)} of {len(useful)}; held at "
                    f"{[k for k in useful if k not in ok]}\n")
    # why an attack did not extend the violation: the first command was for a neighbouring bus,
    # for the faulted bus seen correctly, or for the faulted bus seen on the wrong side of the limits
    # (the falsified estimate overshot, and the absolute setpoint of the dispatch mode removed the fault)
    why = collections.defaultdict(list)
    for r in rows:
        k = (r["kind"], int(r["bus"]))
        if k not in useful or r["scenario"] in ("noctl", "ctl", "scada") or extended(k, r["scenario"]):
            continue
        bus = int(r["first_cmd_reason"][1:].split("=")[0])
        v = float(r["first_cmd_reason"].split("=")[1])
        kind = ("neighbour exposed the fault" if bus != k[1] else
                "estimate on the wrong side, command overwrote the fault" if (v < 1.0) == (k[0] == "avr") else
                "faulted bus seen correctly")
        why[(r["scenario"], kind)].append(k[1])
    for key in sorted(why):
        f.write(f"held {key[0]}: {key[1]}: {len(why[key])} {sorted(why[key])}\n")
    f.write(f"telemetry mode violation at AVR locations: {sorted({V[k]['scada'] for k in V if 'scada' in V[k]})}\n")
print("tab_locations.tex, fig_locations.pdf and locations.txt written")
