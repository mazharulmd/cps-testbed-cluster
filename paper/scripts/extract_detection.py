"""Collect the detection campaign and the location seeds (campaign/paper118_detection.yaml,
campaign/paper118_location_seeds.yaml).

Usage: python extract_detection.py RUNS_DIR [OUT_DIR]
Writes OUT_DIR/detection.csv (no-fault runs with and without a simple FDI on bus 49),
OUT_DIR/matched_avr.csv (AVR-fault attacks at bus 49 with the matched estimator sigma) and
appends seeds 2-5 of the location campaign to OUT_DIR/location_seeds.csv.
"""
import csv
import glob
import json
import os
import re
import sys

RUNS = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "data")


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def violation_time(d, args):
    """Each logged step stands for [t, t + grid_step); the sample at the end of the run is not counted."""
    n = sum(1 for r in rows(os.path.join(d, "grid_truth.csv"))
            if float(r["t"]) < args["duration"] - 1e-9
            and any(not (args["vmin"] <= float(v) <= args["vmax"]) for k, v in r.items() if k != "t"))
    return round(n * args["grid_step"], 3)


def latest(pattern):
    found = {}
    for d in sorted(glob.glob(os.path.join(RUNS, pattern))):
        if os.path.exists(os.path.join(d, "summary.json")):
            found[os.path.basename(d)[16:]] = d       # sorted by time stamp: the last run of a name wins
    return found


def write(name, out):
    if not out:
        print(f"no runs for {name}")
        return
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    print(f"{len(out)} rows -> {name}")


# ---------------------------------------------------------------- detection (no fault)
DET = re.compile(r"^d-(s1|s2)-(min|red)-(none|o\d{3})-(\d)$")
out = []
for name, d in sorted(latest("2*_d-*").items()):
    m = DET.match(name)
    if not m:
        continue
    a = json.load(open(os.path.join(d, "meta.json")))["args"]
    log = rows(os.path.join(d, "cc_log.csv"))
    win = [r for r in log if a["attack_start"] < float(r["t"]) <= a["attack_end"] + 1e-9] if a["attack"] != "none" else log
    tested = [r for r in win if r["observable"] == "1" or r["first_alarm"] == "1"]
    alarmed = [r for r in win if r["first_alarm"] == "1"]
    first_removed = [r["removed_pmus"].split()[0] for r in alarmed if r["removed_pmus"].strip()]
    outside = [r for r in log if a["attack"] != "none" and not (a["attack_start"] < float(r["t"]) <= a["attack_end"] + 1e-9)]
    out.append({
        "name": name, "sigma": 0.001 if m.group(1) == "s1" else 0.002, "placement": "minimum" if m.group(2) == "min" else "redundant",
        "offset_pu": 0.0 if m.group(3) == "none" else int(m.group(3)[1:]) / 1000, "seed": int(m.group(4)),
        "sets": len(win), "tested_sets": len(tested), "alarm_sets": len(alarmed),
        "removed_49_first": sum(p == "49" for p in first_removed),
        "removed_other_first": sum(p != "49" for p in first_removed),
        "alarm_after_removal": sum(r["alarm"] == "1" for r in alarmed),
        "alarms_outside_window": sum(r["first_alarm"] == "1" for r in outside), "sets_outside_window": len(outside),
        "J_mean": round(sum(float(r["first_J"]) for r in tested) / max(len(tested), 1), 2),
        "threshold": float(log[0]["first_threshold"]),
        "violation_s": violation_time(d, a),
    })
write("detection.csv", out)

# ---------------------------------------------------------------- matched sigma, AVR fault at bus 49
MAT = re.compile(r"^m-(.+)-(\d)$")
out = []
for name, d in sorted(latest("2*_m-*").items()):
    m = MAT.match(name)
    if not m:
        continue
    a = json.load(open(os.path.join(d, "meta.json")))["args"]
    log = rows(os.path.join(d, "cc_log.csv"))
    cmds = [r for r in rows(os.path.join(d, "commands_applied.csv")) if r["issued_t"]]
    out.append({"name": name, "scenario": m.group(1), "seed": int(m.group(2)), "sigma": a["se_sigma"],
                "violation_s": violation_time(d, a), "cmd_issued_t": cmds[0]["issued_t"] if cmds else "",
                "alarm_sets_first": sum(r["first_alarm"] == "1" for r in log),
                "alarm_sets_final": sum(r["alarm"] == "1" for r in log),
                "alarms_before_fault": sum(r["first_alarm"] == "1" for r in log if float(r["t"]) <= 4.0)})
write("matched_avr.csv", out)

# ---------------------------------------------------------------- location campaign, seeds 2-5
LOC = re.compile(r"^l-(avr|load)(\d+)-(.+)-s(\d)$")
out = []
for name, d in sorted(latest("2*_l-*-s[2-5]").items()):
    m = LOC.match(name)
    if not m:
        continue
    a = json.load(open(os.path.join(d, "meta.json")))["args"]
    out.append({"name": name, "kind": m.group(1), "bus": int(m.group(2)), "scenario": m.group(3),
                "seed": int(m.group(4)), "violation_s": violation_time(d, a)})
write("location_seeds.csv", out)
