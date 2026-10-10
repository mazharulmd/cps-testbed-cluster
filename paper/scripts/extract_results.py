"""Collect the paper's metrics from the testbed's run directories.

Usage: python extract_results.py RUNS_DIR [OUT_DIR]

RUNS_DIR is the testbed's run directory (/srv/cps/runs). Only the runs of the
paper campaign (campaign/paper118_seeds.yaml) are read, the latest run of each
name. OUT_DIR defaults to ../data. Two kinds of files are written:

  runs.csv            one row per run with the metrics used in the tables
  series_<name>.csv   time series of seed 1 for the figures
  profile_<name>.csv  bus voltages of one PDC set, for the profile figure
  placement.csv       PMU buses of the minimum and redundant placements
"""
import csv
import glob
import json
import os
import re
import sys

import numpy as np

RUNS = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(OUT, exist_ok=True)
NAME = re.compile(r"^\d{8}_\d{6}_((s\d\d)-(.+)|mpi(\d)-s(\d\d))$")


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def violation_time(d, args):
    """Time with some true bus voltage outside the limits. Each logged step stands for
    [t, t + grid_step); the sample at the end of the run is not counted."""
    n = 0
    for r in rows(os.path.join(d, "grid_truth.csv")):
        if float(r["t"]) < args["duration"] - 1e-9 and any(
                not (args["vmin"] <= float(v) <= args["vmax"]) for k, v in r.items() if k != "t"):
            n += 1
    return round(n * args["grid_step"], 3)


def latest_runs():
    found = {}
    for d in sorted(glob.glob(os.path.join(RUNS, "2*_*"))):
        m = NAME.match(os.path.basename(d))
        if m and os.path.exists(os.path.join(d, "summary.json")):
            found[m.group(1)] = d          # sorted by time stamp, so the last one wins
    return found


def metrics(name, d):
    s = json.load(open(os.path.join(d, "summary.json")))
    a = json.load(open(os.path.join(d, "meta.json")))["args"]
    m = NAME.match(os.path.basename(d))
    if m.group(2):
        scen, seed = m.group(3), int(m.group(2)[1:])
    else:
        scen, seed = f"mpi{m.group(4)}", int(m.group(5))
    log = rows(os.path.join(d, "cc_log.csv"))
    cmds = [r for r in rows(os.path.join(d, "commands_applied.csv")) if r["issued_t"]]
    first = cmds[0] if cmds else None
    t0, t1 = a["attack_start"], a["attack_end"]
    win = [r for r in log if t0 < float(r["t"]) <= t1 + 1e-9]
    first_alarm = [float(r["t"]) for r in log if r["first_alarm"] == "1"]
    net = s["network"]
    st = net["status_counts"]
    steps = rows(os.path.join(d, "grid_steps.csv"))
    gp = [float(r["gridpack_solve_ms"]) for r in steps if r["gridpack_solve_ms"]]
    return {
        "name": name, "scenario": scen, "seed": seed,
        "placement": "minimum" if a["placement"] == 1 else "redundant",
        "attack": a["attack"], "bdd_removal": a["bdd"], "control": a["control"],
        "latency_ms": a["latency"], "pdc_wait_ms": a["pdc_wait"], "loss": a["loss"], "mpi_np": a["mpi_np"],
        "violation_s": violation_time(d, a),
        "cmd_issued_t": first["issued_t"] if first else "",
        "cmd_delivered_t": first["delivered_t"] if first else "",
        "cmd_applied_t": first["t_applied"] if first else "",
        "sets": len(log),
        "complete_pct": s["control_center"]["complete_sets_pct"],
        "observable_pct": s["control_center"]["observable_pct"],
        "alarm_sets_first": sum(r["first_alarm"] == "1" for r in log),
        "alarm_sets_final": sum(r["alarm"] == "1" for r in log),
        "removal_sets": sum(bool(r["removed_pmus"].strip()) for r in log),
        "removed_pmus": " ".join(sorted({p for r in log for p in r["removed_pmus"].split()}, key=int)),
        "attack_sets": len(win),
        "attack_sets_usable": sum(r["alarm"] == "0" for r in win),
        "first_alarm_t": f"{first_alarm[0]:.6f}" if first_alarm else "",
        "J_normal_mean": np.mean([float(r["first_J"]) for r in log if float(r["t"]) < 4 and r["observable"] == "1"]),
        "frames_total": net["frames_total"],
        "frames_in_time_pct": 100.0 * st.get("delivered", 0) / max(net["frames_total"], 1),
        "lat_p50_ms": net["latency_ms"]["p50"], "lat_p95_ms": net["latency_ms"]["p95"],
        "pdc_release_ms": s["control_center"]["pdc_release_latency_ms"]["mean"],
        "se_mae_pu": s["control_center"]["se_mean_abs_err_pu"],
        "gridpack_solve_ms_median": float(np.median(gp)) if gp else "",
        "grid_step_ms_mean": s["gridpack"]["step_ms_mean"] if s.get("gridpack") else "",
        "wall_s": s["wall_time_s"],
        "run_dir": os.path.basename(d),
    }


def series(name, d):
    """Seed-1 time series: true and estimated voltage of bus 49, chi-square statistic."""
    truth = rows(os.path.join(d, "grid_truth.csv"))
    est = rows(os.path.join(d, "cc_estimates.csv"))
    log = rows(os.path.join(d, "cc_log.csv"))
    with open(os.path.join(OUT, f"series_{name}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kind", "t", "v49", "J", "threshold", "alarm"])
        for r in truth:
            w.writerow(["truth", r["t"], r["v49"], "", "", ""])
        for r, e in zip(log, est):
            w.writerow(["set", r["t"], e["v49"], r["first_J"], r["first_threshold"], r["first_alarm"]])


def profile(name, d, t_set=4.1):
    """Bus voltages of the set stamped t_set: true state sampled by the PMUs, PMU readings, estimate."""
    est = {round(float(r["t"]), 3): r for r in rows(os.path.join(d, "cc_estimates.csv"))}
    rec = {round(float(r["t"]), 3): r for r in rows(os.path.join(d, "cc_received.csv"))}
    truth = rows(os.path.join(d, "grid_truth.csv"))
    # PMU frames sample the grid state published at the previous grid step (Section IV-F)
    tr = [r for r in truth if float(r["t"]) <= t_set - 1 / 30 + 1e-9][-1]
    e, rc = est[round(t_set, 3)], rec[round(t_set, 3)]
    with open(os.path.join(OUT, f"profile_{name}.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["bus", "true", "pmu", "estimate"])
        for k in tr:
            if not k.startswith("v"):
                continue
            w.writerow([k[1:], tr[k], rc.get(k, ""), e.get(k, "")])


def main():
    runs = latest_runs()
    out = [metrics(n, d) for n, d in sorted(runs.items())]
    with open(os.path.join(OUT, "runs.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    for n in ("noctl", "ctl", "simple-min", "simple-nobdd", "stealthy-min", "delay-min", "drop-min",
              "simple-red", "stealthy-red"):
        series(n, runs[f"s01-{n}"])
    profile("simple-min", runs["s01-simple-min"])
    with open(os.path.join(OUT, "placement.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["placement", "n_pmus", "pmus"])
        for label, n in (("minimum", "s01-simple-min"), ("redundant", "s01-simple-red")):
            pm = [p["bus"] for p in json.load(open(os.path.join(runs[n], "meta.json")))["pmus"]]
            w.writerow([label, len(pm), " ".join(map(str, pm))])
    print(f"{len(out)} runs -> {OUT}")


if __name__ == "__main__":
    main()
