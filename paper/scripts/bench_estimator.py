"""Time the control center's estimator on the IEEE 118-bus system.

Usage (from the repository root, with the testbed's Python environment):
    python paper/scripts/bench_estimator.py [REPEATS] > paper/data/bench_estimator.csv

For each PMU placement it builds noisy PMU sets from the base-case power flow,
with the same noise model as the network federate, and times
StateEstimator.estimate_with_bdd for a clean set and for a set in which the
voltage channel of PMU 49 is falsified by -0.1 pu (an alarm followed by
removal and a second estimate).
"""
import os
import sys
import time

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "federates"))
from cpslib.network import Network                      # noqa: E402
from cpslib.placement import optimal_placement          # noqa: E402
from cpslib.pmu import PmuLayout                        # noqa: E402
from cpslib.estimation import StateEstimator            # noqa: E402

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
rng = np.random.default_rng(1)
net = Network(os.path.join(ROOT, "cases", "ieee118", "topology.json"))
V = net.solve_pf()
V = V[0] if isinstance(V, tuple) else V

print("placement,pmus,channels,case,median_ms,p95_ms,max_ms,alarm_first,removed")
for k, label in ((1, "minimum"), (2, "redundant")):
    buses = optimal_placement(net, k)[0]
    lay = PmuLayout(net, buses)
    se = StateEstimator(lay, sigma=0.002, alpha=0.01)
    p49 = [p for p, pm in enumerate(lay.pmus) if pm["bus"] == 49][0]
    for case in ("clean", "fdi49"):
        times, res = [], None
        for _ in range(REPEATS):
            meas = {}
            for p, ph in enumerate(lay.measure(V)):
                for c, (re, im) in enumerate(ph):
                    z = complex(re, im)
                    mag = abs(z) * (1 + 0.001 * rng.standard_normal())
                    ang = np.angle(z) + 0.001 * rng.standard_normal()
                    meas[(p, c)] = mag * np.exp(1j * ang)
            if case == "fdi49":
                z = meas[(p49, 0)]
                meas[(p49, 0)] = (abs(z) - 0.1) * np.exp(1j * np.angle(z))
            t0 = time.perf_counter()
            res = se.estimate_with_bdd(meas)
            times.append(1000 * (time.perf_counter() - t0))
        removed = " ".join(str(lay.pmus[p]["bus"]) for p in res["removed_pmus"])
        print(f"{label},{len(buses)},{len(lay.row)},{case},{np.median(times):.2f},"
              f"{np.percentile(times, 95):.2f},{max(times):.2f},{int(res['first_alarm'])},{removed}")
