"""Compare the true bus voltages of GridPACK (1 and 4 MPI ranks) with the built-in solver.

Usage: python validate_grid.py RUNS_DIR > ../data/validation.txt
Uses the runs s01-ctl and mpi4-s01 (paper118_seeds.yaml) and val-builtin (validation118.yaml).
"""
import csv
import glob
import os
import sys

import numpy as np


def truth(name):
    d = sorted(glob.glob(os.path.join(sys.argv[1], "2*_" + name)))[-1]
    with open(os.path.join(d, "grid_truth.csv")) as f:
        r = list(csv.reader(f))
    return np.array([[float(x) for x in row] for row in r[1:]])


b, g1, g4 = truth("val-builtin"), truth("s01-ctl"), truth("mpi4-s01")
print(f"grid steps compared: {len(b)}, buses: {b.shape[1] - 1}")
print(f"max |V| difference, GridPACK 1 rank vs built-in: {np.abs(g1[:, 1:] - b[:, 1:]).max():.1e} pu")
print(f"max |V| difference, GridPACK 4 ranks vs 1 rank:  {np.abs(g4[:, 1:] - g1[:, 1:]).max():.1e} pu")
print("voltages are logged with six decimals")
