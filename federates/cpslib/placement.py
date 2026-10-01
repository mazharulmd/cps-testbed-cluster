"""Optimal PMU placement (integer linear programming).

A PMU at bus i measures the voltage phasor of i and the current phasors of every
branch incident to i, which makes i and all its neighbours observable. Minimum
placement for full observability:

    minimise  sum(x)   subject to   A x >= k,   x binary

with A the bus connectivity matrix (including self connections) and k the required
number of PMUs observing each bus (k=1 full observability, k=2 every bus seen twice,
which keeps the grid observable if any single PMU is lost or attacked).
"""
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


def optimal_placement(net, redundancy=1):
    A = net.adjacency()
    n = net.n
    k = np.minimum(redundancy, np.asarray(A.sum(axis=1)).ravel())   # a leaf bus cannot be seen more than deg+1 times
    res = milp(c=np.ones(n), constraints=LinearConstraint(A, lb=k, ub=np.inf),
               integrality=np.ones(n), bounds=Bounds(0, 1),
               options={"time_limit": 60})
    if res.x is None:
        raise RuntimeError(f"PMU placement failed: {res.message}")
    chosen = [net.bus_ids[i] for i in np.where(res.x > 0.5)[0]]
    coverage = A @ (res.x > 0.5).astype(int)
    return chosen, int(coverage.min())
