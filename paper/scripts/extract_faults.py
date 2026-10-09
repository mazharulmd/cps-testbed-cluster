"""Collect the metrics of the fault campaign (campaign/paper118_faults.yaml).

Usage: python extract_faults.py RUNS_DIR [OUT_DIR]
Writes OUT_DIR/faults.csv (default ../data), one row per run, the latest run of each name.
"""
import csv
import glob
import json
import os
import re
import sys

RUNS = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "data")
NAME = re.compile(r"^\d{8}_\d{6}_(f(\d\d)-([a-z0-9]+)-(.+))$")


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


found = {}
for d in sorted(glob.glob(os.path.join(RUNS, "2*_f*"))):
    m = NAME.match(os.path.basename(d))
    if m and os.path.exists(os.path.join(d, "summary.json")):
        found[m.group(1)] = (d, m)

out = []
for name, (d, m) in sorted(found.items()):
    s = json.load(open(os.path.join(d, "summary.json")))
    a = json.load(open(os.path.join(d, "meta.json")))["args"]
    log = rows(os.path.join(d, "cc_log.csv"))
    cmds = [r for r in rows(os.path.join(d, "commands_applied.csv")) if r["issued_t"]]
    steps = rows(os.path.join(d, "grid_steps.csv"))
    net = s["network"]
    att = s.get("attack", {})
    out.append({
        "name": name, "event": m.group(3), "scenario": m.group(4), "seed": int(m.group(2)),
        "mode": a["mode"], "placement": "minimum" if a["placement"] == 1 else "redundant",
        "attack": a["attack"], "target": a["target"], "bdd_removal": a["bdd"], "control": a["control"],
        "violation_s": s["grid"]["true_violation_time_s"],
        "commands": len(cmds),
        "cmd_issued_t": cmds[0]["issued_t"] if cmds else "",
        "min_v_true": min(float(r["min_v"]) for r in steps),
        "complete_pct": s["control_center"]["complete_sets_pct"],
        "observable_pct": s["control_center"]["observable_pct"],
        "alarm_sets_first": sum(r["first_alarm"] == "1" for r in log),
        "alarm_sets_final": sum(r["alarm"] == "1" for r in log),
        "removal_sets": sum(bool(r["removed_pmus"].strip()) for r in log),
        "compromised_pmus": " ".join(map(str, att.get("compromised_pmus", []))),
        "frames_in_time_pct": 100.0 * net["status_counts"].get("delivered", 0) / max(net["frames_total"], 1),
        "se_mae_pu": s["control_center"]["se_mean_abs_err_pu"],
        "wall_s": s["wall_time_s"],
        "run_dir": os.path.basename(d),
    })
with open(os.path.join(OUT, "faults.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)
print(f"{len(out)} runs -> {os.path.join(OUT, 'faults.csv')}")
