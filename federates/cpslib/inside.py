"""What happens inside a running co-simulation, for the dashboard's Inside page.

The observer federate feeds every message it receives into Inside; Inside keeps a compact
picture of each engine and a running log in plain words:

  helics     federates with the node they run on and their granted simulation time (asked
             from the broker), and per topic the number of messages and bytes so far
  gridpack   the last grid step: solver, MPI ranks and how the grid is split over them,
             Newton iterations with their power mismatch (power flow) or integration steps
             (dynamic simulation), times; and a short history of the step times
  ns3        per PMU frames sent, delivered, late and dropped, link delay and latency; the
             PDC's sets; commands on the way to the generators; the attacker
  cc         the last state estimation: measurements, chi-square test, removed PMUs, time
  trace      [[t, engine, text, key event?], ...] oldest first
"""
import json
from collections import deque

import helics as h

TOPICS = {  # topic: (from, to, what)
    "grid/meas": ("grid", "ns3_network", "true phasors of every PMU"),
    "ns3/pdc": ("ns3_network", "control_center", "time-aligned PMU sets"),
    "cc/commands": ("control_center", "ns3_network", "generator setpoint commands"),
    "ns3/cmd_delivered": ("ns3_network", "grid", "commands that reached a generator"),
    "grid/status": ("grid", "observer", "true grid state (live view)"),
    "cc/status": ("control_center", "observer", "estimation results (live view)"),
    "ns3/status": ("ns3_network", "observer", "network counters (live view)"),
}


def _s(t):
    return "?" if t is None else f"{float(t):.3f}".rstrip("0").rstrip(".")


class Inside:
    def __init__(self, meta, run_cfg):
        self.meta, self.cfg = meta, run_cfg
        self.dynamic = run_cfg.get("mode") == "dynamic"
        self.trace = deque(maxlen=400)
        self.topics = {k: {"from": f, "to": to, "what": w, "count": 0, "bytes": 0, "last_t": None}
                       for k, (f, to, w) in TOPICS.items()}
        self.gp, self.gp_hist, self.rank_map = None, deque(maxlen=3000), []
        self.ns3, self.ns3_prev, self.ns3_rate = None, None, {}
        self.cc, self.cc_hist = None, deque(maxlen=3000)
        self.federates, self.query_ok = [], None
        self.alarm_on, self.removed, self.attack_on = False, (), False
        self.last_gp_note, self.last_ns3_note = -1e9, -1e9
        cl = meta.get("cluster", {})
        place = cl.get("placement", {})
        self.where = {"grid": place.get("grid"), "ns3_network": place.get("ns3"), "control_center": place.get("cc"),
                      "observer": place.get("broker"), "broker": place.get("broker")}

    def note(self, t, engine, text, key=True):
        """One line of the log; key=False for the routine report of every step."""
        self.trace.append([round(float(t), 3), engine, text, bool(key)])

    # ------------------------------------------------------------ messages
    def count(self, topic, payload, t):
        tp = self.topics.get(topic)
        if tp is not None:
            tp["count"] += 1
            tp["bytes"] += len(payload)
            tp["last_t"] = t

    def on_grid(self, g):
        t, gp = g["t"], g.get("gp")
        for c in g.get("applied", []):
            if c.get("reason", "").startswith("event"):
                what = c["reason"][len("event: "):]
                self.note(t, "GridPACK", f"grid event: {what}" + (f" at bus {c['gen_bus']}" if c.get("gen_bus") else "")
                          + (f", setpoint {c['vset']} pu" if c.get("vset") else ""))
            else:
                self.note(t, "GridPACK", f"applies the command for generator {c['gen_bus']}: voltage setpoint "
                                         f"{c['vset']} pu (issued {_s(c.get('issued_t'))} s, delivered {_s(c.get('delivered_t'))} s)")
        if not gp:
            return
        if gp.get("rank_map"):
            if not self.rank_map:
                hosts = {}
                for r in gp["rank_map"]:
                    hosts.setdefault(r["host"], []).append(r["rank"])
                self.note(t, "GridPACK", f"{gp['server']} runs on {len(gp['rank_map'])} MPI rank(s): " + "; ".join(
                    f"{h_} ranks {', '.join(map(str, rs))}" for h_, rs in hosts.items())
                    + f"; the {gp['buses']}-bus grid is split among them")
            self.rank_map = gp["rank_map"]
        self.gp = dict(gp, t=t)
        it = gp.get("iterations") or []
        self.gp_hist.append([t, gp.get("t_mpi_ms"), gp.get("t_step_ms"), len([i for i in it if i[0] > 0]) or None, gp.get("steps")])
        if t - self.last_gp_note >= (1.0 if self.dynamic else 0.5) - 1e-9 or not gp.get("converged"):
            self.last_gp_note = t
            if self.dynamic:
                self.note(t, "GridPACK", key=not gp.get("converged"), text=f"integrated {gp.get('steps')} steps of {gp.get('dt_ms')} ms for "
                                         f"{gp.get('machines')} machines in {gp.get('t_mpi_ms')} ms on {gp['ranks']} rank(s); "
                                         f"f = {g.get('freq_coi', 0):.3f} Hz, highest V {gp['max_v'][0]} pu at bus {gp['max_v'][1]}")
            else:
                its = [x for x in it if x[0] > 0]
                conv = (f"Newton converged in {len(its)} iteration(s), mismatch "
                        + " → ".join(f"{x[1]:.1e}" for x in it if x[1] is not None)) if it else "solved"
                self.note(t, "GridPACK", key=not gp.get("converged"), text=f"power flow for {gp['load_mw']} MW of load on {gp['ranks']} rank(s) in "
                                         f"{gp.get('t_mpi_ms') or gp['t_step_ms']} ms: {conv}; highest V "
                                         f"{gp['max_v'][0]} pu at bus {gp['max_v'][1]}"
                                         + ("" if gp.get("converged") else " — NOT converged"))

    def on_ns3(self, n):
        t = n["t"]
        prev = self.ns3_prev
        # per PMU over the last interval: sent, delivered, late, dropped
        rate = {}
        if prev:
            old = {p[0]: p for p in prev["pmus"]}
            for p in n["pmus"]:
                o = old.get(p[0], [p[0], 0, 0, 0, 0, 0, 0, -1])
                rate[p[0]] = [p[2] - o[2], p[3] - o[3], p[4] - o[4], p[5] - o[5], p[6] - o[6]]
        self.ns3_rate, self.ns3_prev, self.ns3 = rate, n, n
        atk = n.get("attack", {})
        if atk.get("active") != self.attack_on:
            self.attack_on = atk.get("active")
            self.note(t, "NS-3", f"the attacker {'starts' if self.attack_on else 'stops'} ({atk.get('type')})")
        if rate and t - self.last_ns3_note >= 1.0 - 1e-9:
            self.last_ns3_note = t
            s = [sum(v[i] for v in rate.values()) for i in range(5)]
            lost = s[0] - s[1] - s[2] - s[3]
            worst = sorted(((v[1] / v[0] if v[0] else 1, b) for b, v in rate.items()))[:3]
            bad = [f"PMU {b} {100 * r:.0f}%" for r, b in worst if r < 0.999]
            pdc = n.get("pdc", {})
            self.note(t, "NS-3", key=False, text=f"{s[0]} PMU frames sent in the last 0.5 s: {s[1]} reached the PDC in time, "
                                 f"{s[2]} late, {max(lost, 0)} lost or on the way" + (f", {s[3]} dropped by the attacker" if s[3] else "")
                                 + (f", {s[4]} attacked" if s[4] else "")
                                 + (f"; lowest delivery {', '.join(bad)}" if bad else "")
                                 + f"; PDC released {pdc.get('sets')} sets so far, {pdc.get('complete')} complete")

    def on_cc(self, c):
        for s in c.get("sets", []):
            self.cc = s
            obs = s.get("obs", 1)
            # a set with PMUs missing cannot be tested for bad data (not observable): no J on the chart
            self.cc_hist.append([s["t"], s.get("est_ms"), s["J"] if obs else None, s["thr"] if obs else None, s.get("J_final")])
            if not obs:
                continue
            alarm, removed = bool(s["alarm"]), tuple(s.get("removed") or ())
            if alarm and (not self.alarm_on or removed != self.removed):
                self.note(s["t"], "Control center", f"chi-square J = {s['J']:.1f} > threshold {s['thr']:.1f}: bad data"
                          + (f"; removed PMU(s) {', '.join(map(str, removed))}, J after removal {s.get('J_final', 0):.1f}"
                             if removed else "; could not isolate it, control is held"))
            elif not alarm and self.alarm_on:
                self.note(s["t"], "Control center", f"measurements consistent again (J = {s['J']:.1f} ≤ {s['thr']:.1f})")
            self.alarm_on, self.removed = alarm, removed

    def on_commands(self, cmds, delivered):
        for c in cmds:
            if delivered:
                lat = (c["delivered_t"] - c["issued_t"]) * 1000 if c.get("issued_t") is not None else None
                self.note(c["delivered_t"], "NS-3", f"command for generator {c['gen_bus']} delivered"
                          + (f" after {lat:.0f} ms" if lat is not None else ""))
            else:
                self.note(c["issued_t"], "Control center", f"{c.get('reason', '')} out of limits: command generator "
                                                           f"{c['gen_bus']} to {c['vset']} pu, sent over the network")

    # ------------------------------------------------------------ HELICS
    def query(self, fed):
        """Ask the broker for every federate's granted time (HELICS global_time query)."""
        if self.query_ok is False:
            return
        try:
            q = h.helicsCreateQuery("root", "global_time")
            raw = h.helicsQueryExecute(q, fed)
            h.helicsQueryFree(q)
            data = raw if isinstance(raw, dict) else json.loads(raw)   # pyhelics returns parsed JSON
            feds = []

            def walk(node):
                for f in node.get("federates", []) or []:
                    name = f.get("attributes", {}).get("name") or f.get("name")
                    feds.append({"name": name, "granted": f.get("granted_time"), "send": f.get("send_time")})
                for c in node.get("cores", []) or []:
                    walk(c)
                for b in node.get("brokers", []) or []:
                    walk(b)
            walk(data)
            if feds:
                self.federates = [dict(f, host=self.where.get(f["name"])) for f in feds]
            self.query_ok = True
        except Exception as e:  # older brokers or a query during shutdown
            if self.query_ok is None:
                self.query_ok = False
                print(f"[OBS] HELICS time query not available: {e}", flush=True)

    # ------------------------------------------------------------ state
    def state(self):
        step = max(1, len(self.gp_hist) // 300)
        cc_step = max(1, len(self.cc_hist) // 300)
        ns3 = None
        if self.ns3:
            ns3 = {"t": self.ns3["t"], "pdc": self.ns3.get("pdc"), "commands": self.ns3.get("commands"),
                   "attack": self.ns3.get("attack"), "events": self.ns3.get("events"),
                   # bus, link delay ms, sent, delivered, late, dropped, attacked, last latency ms, recent [sent, delivered, late, dropped, attacked]
                   "pmus": [p + [self.ns3_rate.get(p[0])] for p in self.ns3["pmus"]],
                   "loss": self.cfg.get("loss"), "rate": None}
        return {
            "mode": "dynamic" if self.dynamic else "qss",
            "helics": {"federates": self.federates, "topics": self.topics,
                       "port": self.meta.get("cluster", {}).get("helics_port"), "core": "zmq"},
            "gridpack": {"last": self.gp, "ranks": self.rank_map, "history": list(self.gp_hist)[::step]},
            "ns3": ns3,
            "cc": {"last": self.cc, "history": list(self.cc_hist)[::cc_step]},
            "trace": sorted(self.trace, key=lambda x: x[0])[-200:],
        }
