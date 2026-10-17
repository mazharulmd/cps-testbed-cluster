"""Collect the location campaign (campaign/paper118_locations.yaml) into ../data/locations.csv.

Usage: python extract_locations.py RUNS_DIR [OUT_DIR]
One row per run (the latest run of each name), with the degree of the faulted bus and the number
of PMUs that observe it under each placement.
"""
import collections
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "..", "data")
NAME = re.compile(r"^\d{8}_\d{6}_l-(avr|load)(\d+)-(.+)$")


def rows(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def violation_time(d, args):
    """Each logged step stands for [t, t + grid_step); the sample at the end of the run is not counted."""
    n = sum(1 for r in rows(os.path.join(d, "grid_truth.csv"))
            if float(r["t"]) < args["duration"] - 1e-9
            and any(not (args["vmin"] <= float(v) <= args["vmax"]) for k, v in r.items() if k != "t"))
    return round(n * args["grid_step"], 3)


topo = json.load(open(os.path.join(HERE, "..", "..", "cases", "ieee118", "topology.json")))
nb = collections.defaultdict(set)
for br in topo["branches"]:
    if br["status"]:
        nb[br["from"]].add(br["to"])
        nb[br["to"]].add(br["from"])
pl = {r["placement"]: set(map(int, r["pmus"].split())) for r in rows(os.path.join(OUT, "placement.csv"))}

found = {}
for d in sorted(glob.glob(os.path.join(RUNS, "2*_l-*"))):
    m = NAME.match(os.path.basename(d))
    if m and os.path.exists(os.path.join(d, "summary.json")):
        found[m.group(0)[16:]] = (d, m)

out = []
for name, (d, m) in sorted(found.items()):
    a = json.load(open(os.path.join(d, "meta.json")))["args"]
    s = json.load(open(os.path.join(d, "summary.json")))
    log = rows(os.path.join(d, "cc_log.csv"))
    cmds = [r for r in rows(os.path.join(d, "commands_applied.csv")) if r["issued_t"]]
    bus = int(m.group(2))
    out.append({
        "name": name, "kind": m.group(1), "bus": bus, "scenario": m.group(3), "degree": len(nb[bus]),
        "pmus_seeing_min": len(({bus} | nb[bus]) & pl["minimum"]),
        "pmus_seeing_red": len(({bus} | nb[bus]) & pl["redundant"]),
        "violation_s": violation_time(d, a), "commands": len(cmds),
        "cmd_issued_t": cmds[0]["issued_t"] if cmds else "",
        "first_cmd_gen": cmds[0]["gen_bus"] if cmds else "",
        "first_cmd_reason": cmds[0]["reason"] if cmds else "",
        "alarm_sets_first": sum(r["first_alarm"] == "1" for r in log),
        "alarm_sets_final": sum(r["alarm"] == "1" for r in log),
        "observable_pct": s["control_center"]["observable_pct"],
        "compromised_pmus": " ".join(map(str, s.get("attack", {}).get("compromised_pmus", []))),
        "run_dir": os.path.basename(d),
    })
with open(os.path.join(OUT, "locations.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)
print(f"{len(out)} runs -> {os.path.join(OUT, 'locations.csv')}")
