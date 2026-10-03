#!/usr/bin/env python3
"""Plot the voltage of every bus at one moment of a run, for reports (as Fig. 8 of the
technical report of the single-server testbed): the true voltage GridPACK computed, the value
each PMU delivered over the network and the control center's estimate.

Usage:
  plot_profile.py <run dir> [--t SECONDS] [--out FILE.png]

  sudo -u cps /opt/cps/venv/bin/python /opt/cps/testbed/tools/plot_profile.py \\
      /srv/cps/runs/20261002_162352_inside-qss --t 9 --out profile.png

Without --t the plot shows one second into the attack, or the moment just after the grid
event. The dashboard's Results page shows the same chart for any moment.
"""
import argparse
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "federates"))
from cpslib import profile  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--t", type=float, help="simulated time in seconds")
    ap.add_argument("--out", help="PNG file (default: profile_<t>s.png in the run directory)")
    args = ap.parse_args()

    p = profile.at(args.run_dir, args.t)
    name = json.load(open(os.path.join(args.run_dir, "meta.json")))["args"]["name"]
    buses, removed = p["buses"], set(p["removed"])
    rx_ok = [(b, v) for b, v in p["rx"] if b not in removed]
    rx_bad = [(b, v) for b, v in p["rx"] if b in removed]

    fig, ax = plt.subplots(figsize=(10, 5.6) if len(buses) <= 60 else (14, 5.6))
    few = len(buses) <= 300
    ax.plot(buses, p["true"], "-o" if few else "-", color="#1565c0", lw=2, ms=5,
            label="GridPACK (true grid state)", zorder=3)
    ax.step(buses, p["est"], where="mid", color="#e53935", lw=1.8,
            label="Control center (state estimate)", zorder=2)
    if rx_ok:
        ax.plot(*zip(*rx_ok), "s", color="#ef6c00", ms=6, label="Received from the PMU (via NS-3)", zorder=4)
    if rx_bad:
        ax.plot(*zip(*rx_bad), "s", color="#8e24aa", ms=7, label="Received, removed as bad data", zorder=5)
    for v in (p["vmin"], p["vmax"]):
        ax.axhline(v, color="#555", ls="--", lw=1)
    if len(buses) <= 40:
        ax.set_xticks(buses)
    ax.set_xlabel("Bus number")
    ax.set_ylabel("Voltage (pu)")
    ax.set_title(f"Actual grid voltage vs voltage at the control center\n{name}, t = {p['t']:.3f} s")
    ax.grid(True, ls="--", alpha=0.5)
    ax.legend(loc="best", fontsize=9)
    fig.tight_layout()
    out = args.out or os.path.join(args.run_dir, f"profile_{p['t']:.3f}s.png")
    fig.savefig(out, dpi=150)
    print(f"{out}: t = {p['t']:.3f} s (true voltages: the grid state at {p['t_true']:.3f} s that the PMUs sampled), "
          f"{len(p['rx'])} PMU values, removed as bad data: {sorted(removed) or 'none'}")


if __name__ == "__main__":
    main()
