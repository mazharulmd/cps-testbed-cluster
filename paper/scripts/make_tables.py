"""Write the result tables of the paper as LaTeX files in ../tables from the files in ../data.

Usage: python make_tables.py
"""
import csv
import os

import numpy as np
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
TAB = os.path.join(HERE, "..", "tables")
os.makedirs(TAB, exist_ok=True)


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


RUNS = rows(os.path.join(DATA, "runs.csv"))


def by(scen, key):
    return np.array([float(r[key]) for r in RUNS if r["scenario"] == scen and r[key] != ""])


def ms(x, fmt="{:.1f}"):
    """mean, or mean +- standard deviation when the seeds differ."""
    x = np.asarray(x, float)
    if len(x) == 0:
        return "--"
    if np.allclose(x, x[0]):
        return fmt.format(x[0])
    return (fmt + r"\,$\pm$\," + fmt).format(x.mean(), x.std(ddof=1))


def ci95(x):
    x = np.asarray(x, float)
    if np.allclose(x, x[0]):
        return 0.0
    return stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


def perm_p(a, b):
    """Two-sided exact permutation test on the difference of means."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if np.allclose(np.r_[a, b], a[0]):
        return 1.0
    r = stats.permutation_test((a, b), lambda x, y: np.mean(x) - np.mean(y), permutation_type="independent",
                               alternative="two-sided", n_resamples=np.inf)
    return r.pvalue


def pfmt(p):
    if p >= 0.999:
        return "1"
    if p < 1e-3:
        m, e = f"{p:.1e}".split("e")
        return rf"${m}\times10^{{{int(e)}}}$"
    return f"{p:.3f}"


def write(name, text):
    with open(os.path.join(TAB, name), "w") as f:
        f.write(text)


def cmd_t(scen):
    x = by(scen, "cmd_issued_t")
    return ms(x, "{:.3f}") if len(x) == len(by(scen, "violation_s")) else ("--" if len(x) == 0 else ms(x, "{:.3f}") + "$^\\ast$")


# ---------------------------------------------------------------- attacks and placement
ATT = [("noctl", "No control (baseline)", "--"), ("ctl", "Control, no attack (baseline)", "--"),
       ("simple-min", "Simple FDI", "49"), ("simple-nobdd", "Simple FDI, no removal", "49"),
       ("stealthy-min", "Stealthy FDI", "45, 49"), ("delay-min", "Delay 100\\,ms", "45, 49"),
       ("drop-min", "Drop", "45, 49"), ("loss5-min", "5\\% frame loss", "--"),
       ("simple-red", "Simple FDI", "49"), ("stealthy-red", "Stealthy FDI", "42, 45, 49, 51, 66"),
       ("delay-red", "Delay 100\\,ms", "42, 45, 49, 51, 66"), ("drop-red", "Drop", "42, 45, 49, 51, 66"),
       ("loss5-red", "5\\% frame loss", "--")]
t = [r"\begin{table*}[t]", r"\caption{Attacks and PMU Placement, IEEE 118-Bus System, AVR Fault at Generator 49 at 4\,s, "
     r"Attacks on Bus 49 From 4 to 9\,s. Mean $\pm$ Standard Deviation Over Ten Seeds; a Single Value Means "
     r"All Seeds Gave the Same Result}", r"\label{tab:attacks}", r"\centering", r"\footnotesize",
     r"\begin{tabular}{@{}llcccccc@{}}", r"\toprule",
     r"Case & Attacked PMUs (bus) & Complete & Observable & Alarm sets & Alarm sets & First command & Violation \\",
     r" & & sets (\%) & sets (\%) & (first test) & (after removal) & issued (s) & time (s) \\", r"\midrule",
     r"\multicolumn{8}{@{}l}{\emph{Minimum placement, 32 PMUs}} \\"]
for s, lab, pm in ATT:
    if s == "simple-red":
        t += [r"\midrule", r"\multicolumn{8}{@{}l}{\emph{Redundant placement, 68 PMUs}} \\"]
    t.append(f"{lab} & {pm} & {ms(by(s, 'complete_pct'))} & {ms(by(s, 'observable_pct'))} & "
             f"{ms(by(s, 'alarm_sets_first'), '{:.0f}')} & {ms(by(s, 'alarm_sets_final'), '{:.0f}')} & "
             f"{cmd_t(s)} & {ms(by(s, 'violation_s'))} \\\\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
write("tab_attacks.tex", "\n".join(t))

# ---------------------------------------------------------------- latency and PDC wait window
LAT = [(5, 20, "lat5"), (10, 20, "ctl"), (20, 20, "lat20"), (40, 20, "lat40"), (80, 20, "lat80"),
       (40, 10, "lat40-w10"), (40, 40, "lat40-w40"), (40, 60, "lat40-w60"), (40, 80, "lat40-w80")]
t = [r"\begin{table*}[t]", r"\caption{Effect of Mean Link Latency $L$ and PDC Wait Window $w$, IEEE 118-Bus System, "
     r"Minimum Placement, AVR Fault, No Attack. Mean $\pm$ Standard Deviation Over Ten Seeds}", r"\label{tab:latency}",
     r"\centering", r"\footnotesize", r"\begin{tabular}{@{}rrcccccccc@{}}", r"\toprule",
     r"$L$ & $w$ & Frames & Complete & Observable & Latency & Latency & PDC release & Estimation & Violation \\",
     r"(ms) & (ms) & in time (\%) & sets (\%) & sets (\%) & p50 (ms) & p95 (ms) & delay (ms) & error ($10^{-3}$\,pu) & time (s) \\",
     r"\midrule"]
for L, w, s in LAT:
    if s == "lat40-w10":
        t.append(r"\midrule")
    t.append(f"{L} & {w} & {ms(by(s, 'frames_in_time_pct'))} & {ms(by(s, 'complete_pct'))} & "
             f"{ms(by(s, 'observable_pct'))} & {ms(by(s, 'lat_p50_ms'))} & {ms(by(s, 'lat_p95_ms'))} & "
             f"{ms(by(s, 'pdc_release_ms'))} & {ms(1000 * by(s, 'se_mae_pu'), '{:.2f}')} & {ms(by(s, 'violation_s'))} \\\\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""]
write("tab_latency.tex", "\n".join(t))

# ---------------------------------------------------------------- statistical tests
TESTS = [("violation_s", "ctl", "noctl", "Control (A) vs.\\ no control (B)"),
         ("violation_s", "simple-min", "simple-nobdd", "Simple FDI, 32 PMUs: removal (A) vs.\\ no removal (B)"),
         ("violation_s", "ctl", "simple-min", "No attack (A) vs.\\ simple FDI with removal (B)"),
         ("violation_s", "ctl", "stealthy-min", "No attack (A) vs.\\ stealthy FDI (B), 32 PMUs"),
         ("violation_s", "delay-red", "delay-min", "Delay: 68 PMUs (A) vs.\\ 32 PMUs (B)"),
         ("violation_s", "drop-red", "drop-min", "Drop: 68 PMUs (A) vs.\\ 32 PMUs (B)"),
         ("observable_pct", "loss5-red", "loss5-min", "5\\% loss, observable sets: 68 PMUs (A) vs.\\ 32 PMUs (B)"),
         ("complete_pct", "ctl", "lat20", "Complete sets: $L$ = 10\\,ms (A) vs.\\ 20\\,ms (B)"),
         ("complete_pct", "lat40-w40", "lat40", "Complete sets at $L$ = 40\\,ms: $w$ = 40\\,ms (A) vs.\\ 20\\,ms (B)"),
         ("violation_s", "lat40-w40", "lat40-w10", "Violation at $L$ = 40\\,ms: $w$ = 40\\,ms (A) vs.\\ 10\\,ms (B)"),
         ("violation_s", "ctl", "lat80", "Violation: $L$ = 10\\,ms (A) vs.\\ 80\\,ms (B)")]
t = [r"\begin{table}[t]", r"\caption{Statistical Tests Between Configurations, Ten Seeds Each. Difference of Means "
     r"(B $-$ A) With 95\% Confidence Interval and Two-Sided Exact Permutation Test}", r"\label{tab:stats}",
     r"\centering", r"\footnotesize", r"\setlength{\tabcolsep}{3pt}", r"\begin{tabular}{@{}P{3.3cm}ccc@{}}",
     r"\toprule", r"Comparison (A vs.\ B) & Mean A & Mean B $-$ A & $p$ \\", r"\midrule"]
out = []
for key, a, b, lab in TESTS:
    xa, xb = by(a, key), by(b, key)
    d = xb.mean() - xa.mean()
    se = np.sqrt(xa.var(ddof=1) / len(xa) + xb.var(ddof=1) / len(xb))
    dfree = len(xa) + len(xb) - 2
    half = stats.t.ppf(0.975, dfree) * se
    p = perm_p(xa, xb)
    unit = "\\,s" if key == "violation_s" else "\\,\\%"
    diff = f"{d:+.1f}" + (f" [{d - half:+.1f}, {d + half:+.1f}]" if half > 0 else "") + unit
    t.append(f"{lab} & {xa.mean():.1f}{unit} & {diff} & {pfmt(p)} \\\\")
    out.append((lab, xa.mean(), d, half, p))
t += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
write("tab_stats.tex", "\n".join(t))

# ---------------------------------------------------------------- MPI ranks
t = [r"\begin{table}[t]", r"\caption{Computing Time per Experiment With 1, 2 and 4 GridPACK MPI Ranks, Base Scenario, "
     r"Five Seeds Each (Mean $\pm$ Standard Deviation)}", r"\label{tab:mpi}", r"\centering", r"\footnotesize",
     r"\begin{tabular}{@{}lccc@{}}", r"\toprule", r"Ranks & Solve time (ms) & Grid step (ms) & Wall time (s) \\",
     r"\midrule"]
for n in (1, 2, 4):
    s = f"mpi{n}"
    t.append(f"{n} & {ms(by(s, 'gridpack_solve_ms_median'))} & {ms(by(s, 'grid_step_ms_mean'))} & {ms(by(s, 'wall_s'))} \\\\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
write("tab_mpi.tex", "\n".join(t))

# ---------------------------------------------------------------- estimator timing
b = rows(os.path.join(DATA, "bench_estimator.csv"))
t = [r"\begin{table}[t]", r"\caption{Control-Center Computing Time per PDC Set, IEEE 118-Bus System}", r"\label{tab:bench}",
     r"\centering", r"\footnotesize", r"\begin{tabular}{@{}llccc@{}}", r"\toprule",
     r"PMUs & Set & Median (ms) & p95 (ms) & Max (ms) \\", r"\midrule"]
for r in b:
    case = "clean" if r["case"] == "clean" else f"FDI, PMU {r['removed']} removed"
    t.append(f"{r['pmus']} & {case} & {r['median_ms']} & {r['p95_ms']} & {r['max_ms']} \\\\")
t += [r"\bottomrule", r"\end{tabular}", r"\end{table}", ""]
write("tab_bench.tex", "\n".join(t))

# numbers quoted in the text
with open(os.path.join(TAB, "numbers.txt"), "w") as f:
    for s in sorted({r["scenario"] for r in RUNS}):
        f.write(f"{s}: n={len(by(s, 'violation_s'))} viol={by(s, 'violation_s').mean():.2f} "
                f"complete={by(s, 'complete_pct').mean():.1f}+-{ci95(by(s, 'complete_pct')):.1f} "
                f"obs={by(s, 'observable_pct').mean():.1f} frames={by(s, 'frames_in_time_pct').mean():.1f} "
                f"p50={by(s, 'lat_p50_ms').mean():.1f} p95={by(s, 'lat_p95_ms').mean():.1f} "
                f"pdc={by(s, 'pdc_release_ms').mean():.1f} mae={1000 * by(s, 'se_mae_pu').mean():.2f} "
                f"Jn={np.nanmean(by(s, 'J_normal_mean')):.1f} wall={by(s, 'wall_s').mean():.1f} "
                f"wall_range={by(s, 'wall_s').min():.1f}-{by(s, 'wall_s').max():.1f}\n")
    for lab, m, d, h, p in out:
        f.write(f"TEST {lab}: meanA={m:.2f} d={d:.2f} ci={h:.2f} p={p:.3g}\n")
print("tables written to", os.path.abspath(TAB))
