"""Tables and figure of the detection campaign and the location seeds.

Usage: python make_detection.py
Reads ../data/detection.csv, matched_avr.csv, location_seeds.csv, locations.csv and runs.csv.
Writes ../tables/tab_detection.tex, ../tables/tab_seeds.tex, ../tables/detection.txt and
../figures/fig_detection.pdf.
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


def rows(name):
    with open(os.path.join(DATA, name)) as f:
        return list(csv.DictReader(f))


det = rows("detection.csv")
G = collections.defaultdict(list)
for r in det:
    G[(float(r["sigma"]), r["placement"], float(r["offset_pu"]))].append(r)
OFFS = sorted({k[2] for k in G if k[2] > 0})
CASES = [(0.002, "minimum"), (0.002, "redundant"), (0.001, "minimum"), (0.001, "redundant")]


def rate(rs, num, den):
    n, d = sum(int(r[num]) for r in rs), sum(int(r[den]) for r in rs)
    return 100.0 * n / d if d else float("nan")


# ---------------------------------------------------------------- table
t = [r"\begin{table*}[t]",
     r"\caption{Bad Data Detection Without a Fault, Simple FDI on Bus 49 From 2 to 9\,s, Five Seeds per Cell. "
     r"Estimator $\sigma$ = 0.002 (Default) or 0.001 (Matched to the Simulated Noise)}",
     r"\label{tab:detection}", r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{4pt}",
     r"\begin{tabular}{@{}llcc" + "c" * len(OFFS) + "c@{}}", r"\toprule",
     r"$\sigma$ & PMUs & Mean $J$ & False alarms & \multicolumn{" + str(len(OFFS)) +
     r"}{c}{Detected sets (\%) for an offset of} & PMU 49 removed \\",
     r"\cmidrule(lr){5-" + str(4 + len(OFFS)) + "}",
     r" & & no attack & (\% of sets) & " + " & ".join(f"{o:.3f}\\,pu" for o in OFFS) + r" & first (\%) \\", r"\midrule"]
for sig, pl in CASES:
    none = G[(sig, pl, 0.0)]
    cells = [f"{rate(G[(sig, pl, o)], 'alarm_sets', 'tested_sets'):.1f}" for o in OFFS]
    att = [r for o in OFFS for r in G[(sig, pl, o)]]
    t.append(f"{sig:.3f} & {68 if pl == 'redundant' else 32} & {np.mean([float(r['J_mean']) for r in none]):.1f} & "
             f"{rate(none, 'alarm_sets', 'tested_sets'):.2f} & " + " & ".join(cells) +
             f" & {rate(att, 'removed_49_first', 'alarm_sets'):.1f} \\\\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
with open(os.path.join(TAB, "tab_detection.tex"), "w") as f:
    f.write("\n".join(t))

# ---------------------------------------------------------------- figure
fig, ax = plt.subplots(figsize=(3.45, 2.0))
style = {(0.002, "minimum"): ("#2a6fb0", "-", "o"), (0.002, "redundant"): ("#2a6fb0", "--", "s"),
         (0.001, "minimum"): ("#e07b2a", "-", "o"), (0.001, "redundant"): ("#e07b2a", "--", "s")}
for sig, pl in CASES:
    c, ls, mk = style[(sig, pl)]
    y = [rate(G[(sig, pl, o)], "alarm_sets", "tested_sets") for o in OFFS]
    ax.plot(OFFS, y, color=c, ls=ls, marker=mk, ms=3.5, lw=1.0,
            label=f"$\\sigma$ = {sig:.3f}, {68 if pl == 'redundant' else 32} PMUs")
ax.set_xscale("log")
ax.set_xticks(OFFS)
ax.set_xticklabels([f"{o:g}" for o in OFFS])
ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
ax.set_xlabel("injected offset on the voltage channel of PMU 49 (pu)")
ax.set_ylabel("detected sets (%)")
ax.set_ylim(-3, 103)
ax.legend(loc="upper left", frameon=False, fontsize=6.5)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
fig.savefig(os.path.join(FIG, "fig_detection.pdf"))

# ---------------------------------------------------------------- matched sigma with the AVR fault, against the default
mat = collections.defaultdict(list)
for r in rows("matched_avr.csv"):
    mat[r["scenario"]].append(r)
base = collections.defaultdict(list)
for r in rows("runs.csv"):
    if int(r["seed"]) <= 5:
        base[r["scenario"]].append(r)
lines = []
for sc in ("ctl", "simple-min", "simple-red", "stealthy-min", "stealthy-red"):
    m, b = mat[sc], base[sc]
    lines.append(f"AVR {sc}: matched viol {sorted({x['violation_s'] for x in m})} alarms_first {sorted({x['alarm_sets_first'] for x in m})} "
                 f"alarms_final {sorted({x['alarm_sets_final'] for x in m})} before_fault {sorted({x['alarms_before_fault'] for x in m})} | "
                 f"default viol {sorted({x['violation_s'] for x in b})} alarms_first {sorted({x['alarm_sets_first'] for x in b})}")

# ---------------------------------------------------------------- location seeds: does the outcome hold for seeds 1-5?
V = collections.defaultdict(dict)
for r in rows("locations.csv"):
    V[(r["kind"], int(r["bus"]), r["scenario"])][1] = float(r["violation_s"])
for r in rows("location_seeds.csv"):
    V[(r["kind"], int(r["bus"]), r["scenario"])][int(r["seed"])] = float(r["violation_s"])
locs = sorted({(k[0], k[1]) for k in V if len(V[k]) > 1})
SC = ["simple-min", "simple-red", "stealthy-min", "stealthy-red", "delay-min", "delay-red"]
same, total, spread = 0, 0, []
t = [r"\begin{table*}[t]", r"\caption{Extra Violation (s) Over the Attack-Free Control at Ten Locations, Seeds 1--5 "
     r"(Mean; Range in Brackets When the Seeds Differ)}", r"\label{tab:seeds}", r"\centering", r"\footnotesize",
     r"\setlength{\tabcolsep}{6pt}", r"\begin{tabular}{@{}l" + "c" * len(SC) + "@{}}", r"\toprule",
     r" & \multicolumn{2}{c}{Simple FDI} & \multicolumn{2}{c}{Stealthy FDI} & \multicolumn{2}{c}{Delay} \\",
     r"\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(l){6-7}",
     r"Fault & 32 & 68 & 32 & 68 & 32 & 68 \\", r"\midrule"]
for kind, bus in locs:
    ctl = V[(kind, bus, "ctl")]
    cells = []
    for sc in SC:
        v = V[(kind, bus, sc)]
        ex = [v[s] - ctl[s] for s in sorted(v) if s in ctl]
        worked = [e > 0.25 for e in ex]
        total += 1
        same += len(set(worked)) == 1
        spread.append(max(ex) - min(ex))
        cells.append(f"{np.mean(ex):.1f}" + (f" [{min(ex):.1f}, {max(ex):.1f}]" if max(ex) - min(ex) > 1e-9 else ""))
    lab = f"AVR {bus}" if kind == "avr" else f"Load {bus}"
    t.append(lab + " & " + " & ".join(cells) + r" \\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
with open(os.path.join(TAB, "tab_seeds.tex"), "w") as f:
    f.write("\n".join(t))
with open(os.path.join(TAB, "detection.txt"), "w") as f:
    f.write("\n".join(lines) + "\n")
    f.write(f"location seeds: {same} of {total} attack/location cells gave the same outcome (worked or not) in all seeds; "
            f"largest spread of the extra violation {max(spread):.3f} s\n")
print("tab_detection.tex, tab_seeds.tex, fig_detection.pdf and detection.txt written")
