"""Voltage of every bus at one moment of a finished run, as the dashboard's profile chart and
tools/plot_profile.py show it:

  true      the voltages GridPACK computed for the grid state the PMUs sampled (grid_truth.csv)
  rx        the bus voltage each PMU delivered over the network, attacks included (cc_received.csv)
  est       the control center's state estimate for every bus from that PMU set (cc_estimates.csv)

The moment is a PMU set: the last one at or before t, or the last complete one within a grid
step before it (a set with missing PMUs may leave buses unobserved).
"""
import bisect
import csv
import json
import os


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return list(csv.DictReader(fh))


def _event_time(a):
    if a.get("event") in (None, "", "none"):
        return None
    return float(a["event"].split(":")[-1]) + (0.07 if a.get("mode") == "dynamic" else 0.2)


def default_time(a):
    """An instant worth looking at: one second into the attack, or just after the grid event."""
    if a.get("attack", "none") != "none":
        return a["attack_start"] + min(1.0, (a["attack_end"] - a["attack_start"]) / 2)
    te = _event_time(a)
    return te if te is not None else a["duration"]


def at(run_dir, t=None):
    a = json.load(open(os.path.join(run_dir, "meta.json")))["args"]
    truth = _rows(os.path.join(run_dir, "grid_truth.csv"))
    est = _rows(os.path.join(run_dir, "cc_estimates.csv"))
    if not truth or not est:
        raise LookupError("no voltages in this run")
    if t is None:
        t = default_time(a)
    qss = a.get("mode", "qss") == "qss"
    step = a["grid_step"] if qss else round(1 / a["rate"], 6)
    t_est = [float(r["t"]) for r in est]
    i = max(bisect.bisect_right(t_est, t + 1e-9) - 1, 0)
    # cc_log.csv and cc_received.csv have one row per PMU set, in the order of cc_estimates.csv
    cc = _rows(os.path.join(run_dir, "cc_log.csv"))
    if len(cc) == len(est):
        k, lim = i, t_est[i] - (step if qss else 0.2)
        while k >= 0 and t_est[k] >= lim and cc[k]["pmus_received"] != cc[k]["pmus_expected"]:
            k -= 1
        if k >= 0 and t_est[k] >= lim:
            i = k
    t_true = [float(r["t"]) for r in truth]
    # the PMUs of a frame sample the grid state published before the frame time
    j = max(bisect.bisect_left(t_true, t_est[i] - 1e-4) - 1, 0)     # times are rounded differently
    cols = [c for c in truth[0] if c != "t"]
    te = _event_time(a)
    out = {"t": t_est[i], "t_true": t_true[j], "t_range": [t_est[0], t_est[-1]], "duration": a["duration"],
           "vmin": a["vmin"], "vmax": a["vmax"], "mode": a.get("mode", "qss"), "attack": a["attack"],
           "attack_window": [a["attack_start"], a["attack_end"]] if a["attack"] != "none" else None,
           "event": a["event"], "buses": [int(c[1:]) for c in cols],
           "true": [float(truth[j][c]) for c in cols], "est": [float(est[i][c]) for c in cols],
           "rx": [], "removed": [], "J": None, "threshold": None, "alarm": None,
           # for stepping through the run: a grid step (a PMU frame in dynamic mode), moments of note
           "step": step,
           "marks": [[name, round(v, 3)] for name, v in (
               ("event", te), ("attack", default_time(a) if a["attack"] != "none" else None), ("end", t_est[-1]))
               if v is not None]}
    rcv = _rows(os.path.join(run_dir, "cc_received.csv"))     # runs before this file existed have none
    if len(rcv) > i and rcv[i]["t"] == est[i]["t"]:
        out["rx"] = [[int(c[1:]), float(v)] for c, v in rcv[i].items() if c != "t" and v]
    if len(cc) > i and cc[i]["t"] == est[i]["t"]:
        r = cc[i]
        out.update(removed=[int(b) for b in r["removed_pmus"].split()], J=float(r["first_J"]),
                   threshold=float(r.get("first_threshold") or r["threshold"]), alarm=int(r["first_alarm"]),
                   pmus=int(r["pmus_received"]), pmus_expected=int(r["pmus_expected"]))
    return out
