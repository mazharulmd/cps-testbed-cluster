#!/usr/bin/env python3
"""Observer federate: follows a running experiment for the live dashboard.

It joins the HELICS federation like the other federates but only subscribes (true grid
state, what the control center sees, commands issued and delivered) and publishes nothing,
so no federate waits for it. Every half second of wall time it writes the experiment's
live state to <run_dir>/live.json, which the experiment API serves to the Node-RED "Live"
page. The page can ask for any bus by writing <run_dir>/watch.json ({"bus": N}).

Usage: observer_fed.py <run_dir>/observer_config.json
"""
import json, os, sys, time
import helics as h


def write_atomic(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"))
    os.replace(tmp, path)


def main(cfg_path):
    cfg = json.load(open(cfg_path))
    out, T = cfg["outdir"], cfg["duration"]
    meta = json.load(open(os.path.join(out, "meta.json")))
    topo = json.load(open(cfg["topology"]))
    bus_ids = [b["id"] for b in topo["buses"]]
    idx = {b: i for i, b in enumerate(bus_ids)}
    a = meta["args"]
    default_bus = meta["target_bus"]

    fi = h.helicsCreateFederateInfo()
    h.helicsFederateInfoSetCoreTypeFromString(fi, "zmq")
    h.helicsFederateInfoSetCoreInitString(fi, cfg.get("helics_core_init", "--federates=1"))
    fed = h.helicsCreateValueFederate("observer", fi)
    subs = {name: h.helicsFederateRegisterSubscription(fed, name, "")
            for name in ("grid/status", "cc/status", "cc/commands", "ns3/cmd_delivered")}
    h.helicsFederateEnterExecutingMode(fed)
    print(f"[OBS] following {meta['grid_name']} for {T} s", flush=True)

    truth = []            # (t, vm list) per grid step
    est = []              # (t, vm list) about once per grid step
    sets = []             # per PMU set: t, J, thr, alarm, complete, max_v, ...
    commands = {}         # id -> issued / delivered / applied
    events = []
    max_true = []
    freq = []             # dynamic mode: (t, f centre of inertia, f min, f max) per grid step
    spread = []           # dynamic mode: (t, rotor angle spread) per grid step
    gens_last = []
    live_path = os.path.join(out, "live.json")
    watch_path = os.path.join(out, "watch.json")
    last_write, t = 0.0, 0.0

    def snapshot(done=False):
        bus = default_bus
        try:
            bus = int(json.load(open(watch_path)).get("bus", default_bus))
        except (OSError, ValueError, TypeError):
            pass
        if bus not in idx:
            bus = default_bus
        i = idx[bus]
        step = max(1, len(sets) // 600)     # keep the per-set series light
        gstep = max(1, len(truth) // 900)   # and the per-grid-step ones (dynamic: 30 per second)
        write_atomic(live_path, {
            "run_id": os.path.basename(out), "name": a["name"], "grid": meta["grid_name"], "t": t, "duration": T,
            "done": done, "bus": bus, "vmax": a["vmax"], "vmin": a["vmin"], "attack": a["attack"],
            "attack_window": [a["attack_start"], a["attack_end"]] if a["attack"] != "none" else None,
            "event": a["event"], "mpi_np": a.get("mpi_np"), "cluster": meta.get("cluster"),
            "mode": a.get("mode", "qss"),
            "truth": [[tt, v[i]] for tt, v in truth[::gstep]],
            "estimate": [[tt, v[i]] for tt, v in est[::gstep]],
            "truth_max": max_true[::gstep],
            "freq": freq[::gstep], "angle_spread": spread[::gstep], "gens": gens_last,
            "est_max": [[s["t"], s["max_v"]] for s in sets[::step]],
            "chi2": [[s["t"], s["J"], s["thr"], s["alarm"]] for s in sets[::step]],
            "completeness": [[s["t"], s["complete"]] for s in sets[::step]],
            "alarms": sum(s["alarm"] for s in sets), "sets": len(sets),
            "violations_seen": sum(1 for s in sets if s["viol"]),
            "last": sets[-1] if sets else None,
            "commands": sorted(commands.values(), key=lambda c: c.get("issued_t") or c.get("applied_t") or 0),
            "events": events,
        })

    while t < T:
        t = h.helicsFederateRequestTime(fed, T)       # returns early whenever a value arrives
        if h.helicsInputIsUpdated(subs["grid/status"]):
            g = json.loads(h.helicsInputGetString(subs["grid/status"]))
            truth.append((g["t"], g["vm"]))
            m = max(range(len(g["vm"])), key=g["vm"].__getitem__)
            max_true.append([g["t"], g["vm"][m], bus_ids[m]])
            if "freq_coi" in g:
                freq.append([g["t"], g["freq_coi"], g["freq_min"], g["freq_max"]])
                spread.append([g["t"], g["angle_spread"]])
                gens_last = g.get("gens", [])
            for c in g.get("applied", []):
                if c.get("reason", "").startswith("event"):
                    events.append(dict(c, applied_t=g["t"]))
                else:
                    key = f"{c['gen_bus']}@{c.get('issued_t')}"
                    commands.setdefault(key, {}).update(c, applied_t=g["t"])
        if h.helicsInputIsUpdated(subs["cc/status"]):
            c = json.loads(h.helicsInputGetString(subs["cc/status"]))
            sets.extend(c["sets"])
            if c.get("vm_est"):
                est.append((c["t_est"], c["vm_est"]))
        for name in ("cc/commands", "ns3/cmd_delivered"):
            if h.helicsInputIsUpdated(subs[name]):
                for c in json.loads(h.helicsInputGetString(subs[name]) or "[]"):
                    key = f"{c['gen_bus']}@{c.get('issued_t')}"
                    commands.setdefault(key, {}).update(c)
        if time.time() - last_write > 0.5:
            snapshot()
            last_write = time.time()
    snapshot(done=True)
    h.helicsFederateDisconnect(fed)
    h.helicsFederateFree(fed)
    print(f"[OBS] finished: {len(truth)} grid steps, {len(sets)} PMU sets, {len(commands)} commands", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
