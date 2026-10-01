#!/usr/bin/env python3
"""Grid federate: quasi-steady-state power system simulation with GridPACK.

Every grid step the federate
  1. applies control commands that have arrived over the NS-3 network (generator
     voltage setpoints),
  2. updates the loads (slow sinusoidal variation + small random walk, plus an
     optional scheduled event),
  3. re-solves the power flow with GridPACK (or the built-in Newton-Raphson solver),
  4. publishes the true voltage/current phasors seen by every PMU,
and logs the true grid state so experiments can be scored afterwards.

Usage: grid_fed.py <run_dir>/run_config.json
"""
import csv, json, os, sys, time
import numpy as np
import helics as h

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cpslib.network import Network
from cpslib.pmu import PmuLayout
from cpslib.gridpack import GridPackMPISolver, server_available


def main(cfg_path):
    cfg = json.load(open(cfg_path))
    out = cfg["outdir"]
    topo = json.load(open(cfg["topology"]))
    net = Network(topo)
    layout = PmuLayout(net, cfg["pmu_buses"])
    rng = np.random.default_rng(cfg["seed"])
    dt, T = cfg["grid_step"], cfg["duration"]

    solver = None
    mpi = cfg.get("mpi") or {}
    if cfg["solver"] == "gridpack":
        if server_available():
            # one MPI job for the whole run, started before joining HELICS (partitioning takes a while)
            solver = GridPackMPISolver(net, topo, os.path.join(out, "gridpack"), mpi.get("np", 1), mpi.get("hostfile"))
            print(f"[GRID] GridPACK pf_server: {solver.ready.get('nranks')} MPI ranks, "
                  f"setup {solver.setup_s:.2f} s", flush=True)
        else:
            print("[GRID] GridPACK pf_server not found (CPS_PF_SERVER); using the built-in solver", flush=True)
    pd0 = np.array([b["pd"] for b in topo["buses"]])
    qd0 = np.array([b["qd"] for b in topo["buses"]])
    vset = {}
    for g in topo["gens"]:
        if g["status"]:
            vset[g["bus"]] = g["vg"]
    lp = cfg["load"]
    walk = np.zeros(net.n)
    ev = cfg.get("event") or {}

    fi = h.helicsCreateFederateInfo()
    h.helicsFederateInfoSetCoreTypeFromString(fi, "zmq")
    h.helicsFederateInfoSetCoreInitString(fi, cfg.get("helics_core_init", "--federates=1"))
    h.helicsFederateInfoSetFlagOption(fi, h.HELICS_FLAG_UNINTERRUPTIBLE, True)
    fed = h.helicsCreateValueFederate("grid", fi)
    pub = h.helicsFederateRegisterGlobalPublication(fed, "grid/meas", h.HELICS_DATA_TYPE_STRING, "")
    # true state for observers (the live dashboard); no federate in the loop depends on it
    pub_status = h.helicsFederateRegisterGlobalPublication(fed, "grid/status", h.HELICS_DATA_TYPE_STRING, "")
    sub = h.helicsFederateRegisterSubscription(fed, "ns3/cmd_delivered", "")
    h.helicsFederateEnterExecutingMode(fed)
    print(f"[GRID] {len(topo['buses'])}-bus system, {len(cfg['pmu_buses'])} PMUs, solver={cfg['solver']}", flush=True)

    truth = open(os.path.join(out, "grid_truth.csv"), "w", newline="")
    tw = csv.writer(truth)
    tw.writerow(["t"] + [f"v{b}" for b in net.bus_ids])
    applied = open(os.path.join(out, "commands_applied.csv"), "w", newline="")
    aw = csv.writer(applied)
    aw.writerow(["t_applied", "gen_bus", "vset", "issued_t", "delivered_t", "reason"])
    steps = open(os.path.join(out, "grid_steps.csv"), "w", newline="")
    sw = csv.writer(steps)
    sw.writerow(["t", "solver", "converged", "iterations", "total_load_mw", "max_v", "max_v_bus", "min_v", "min_v_bus",
                 "solve_ms", "mpi_ranks", "gridpack_solve_ms"])

    seen_cmds = set()
    k = 0
    while True:
        t = round(k * dt, 9)
        if t > T + 1e-9:
            break
        h.helicsFederateRequestTime(fed, t)
        applied_now = []
        if h.helicsInputIsUpdated(sub):
            for c in json.loads(h.helicsInputGetString(sub) or "[]"):
                if c.get("id") in seen_cmds:
                    continue
                seen_cmds.add(c.get("id"))
                vset[c["gen_bus"]] = c["vset"]
                aw.writerow([t, c["gen_bus"], c["vset"], c.get("issued_t"), c.get("delivered_t"), c.get("reason", "")])
                applied_now.append({"gen_bus": c["gen_bus"], "vset": c["vset"], "issued_t": c.get("issued_t"),
                                    "delivered_t": c.get("delivered_t"), "reason": c.get("reason", "")})
                print(f"[GRID] t={t:.2f}s command applied: gen {c['gen_bus']} vset -> {c['vset']:.3f} pu", flush=True)
        # loads
        walk = walk + lp["walk"] * np.sqrt(dt) * rng.standard_normal(net.n)
        scale = 1 + lp["amplitude"] * np.sin(2 * np.pi * t / lp["period"]) + walk
        pd, qd = pd0 * scale, qd0 * scale
        if ev.get("type") == "load_step" and t >= ev["t"]:
            i = net.idx[ev["bus"]]
            pd[i] *= 1 + ev["pct"] / 100; qd[i] *= 1 + ev["pct"] / 100
        if ev.get("type") == "avr_fault" and ev.get("t") <= t and not ev.get("_done"):
            vset[ev["bus"]] = ev["vset"]; ev["_done"] = True
            aw.writerow([t, ev["bus"], ev["vset"], "", "", "event: AVR setpoint fault"])
            applied_now.append({"gen_bus": ev["bus"], "vset": ev["vset"], "reason": "event: AVR setpoint fault"})
            print(f"[GRID] t={t:.2f}s EVENT: AVR fault at gen {ev['bus']}, vset -> {ev['vset']}", flush=True)
        # solve
        V, it, ok, used = None, 0, False, cfg["solver"]
        t_solve = time.time()
        if solver:
            try:
                V, it, ok = solver.solve(pd, qd, vset)
            except RuntimeError as e:
                # the MPI job died (e.g. a node went down): finish the run with the built-in solver
                print(f"[GRID] t={t:.2f}s GridPACK failed ({e}); using the built-in solver from now on", flush=True)
                solver = None
        t_solve = time.time() - t_solve
        srv = getattr(solver, "last", None) or {}
        if V is None or not ok:
            used = "builtin"
            V, it, ok = net.solve_pf(pd, qd, vset)
        vm = np.abs(V)
        tw.writerow([t] + [f"{x:.6f}" for x in vm])
        sw.writerow([t, used, ok, it, f"{pd.sum():.2f}", f"{vm.max():.5f}", net.bus_ids[int(vm.argmax())],
                     f"{vm.min():.5f}", net.bus_ids[int(vm.argmin())], f"{1000 * t_solve:.2f}",
                     getattr(solver, "np", 1) if used == "gridpack" else "",
                     f"{1000 * float(srv['t_solve']):.2f}" if used == "gridpack" and "t_solve" in srv else ""])
        meas = {str(pm["bus"]): ph for pm, ph in zip(layout.pmus, layout.measure(V))}
        h.helicsPublicationPublishString(pub, json.dumps({"t": t, "pmus": meas}))
        h.helicsPublicationPublishString(pub_status, json.dumps(
            {"t": t, "vm": [round(float(x), 5) for x in vm], "solver": used, "applied": applied_now}))
        k += 1

    for f in (truth, applied, steps):
        f.close()
    if hasattr(solver, "close"):
        solver.close()
    h.helicsFederateDisconnect(fed)
    h.helicsFederateFree(fed)
    print("[GRID] finished", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
