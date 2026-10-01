"""False data injection attack planning.

The attacker wants the control center to see |V_b| = v_fake at a target bus b.
If it controls the PMU at b, the change is recomputed from each intercepted frame
(adaptive); otherwise a fixed offset planned from the expected operating point is used.
In the linear PMU model this is a state change c = (v_fake - |V_b|) e^{j theta_b}
at bus b, which shifts every measurement row h by h_b * c.

  simple   : falsify only the one channel that most directly measures bus b
             (its voltage if a PMU sits at b, otherwise one incident current).
             Inconsistent with the other measurements unless that channel is critical.
  stealthy : falsify every channel with h_b != 0 (a = H c). The residual is unchanged,
             so the chi-square test cannot see it; it needs more compromised PMUs.
"""
import numpy as np


def plan_fdi(layout, V_base, target_bus, v_fake, mode="simple"):
    net = layout.net
    b = net.idx[target_bus]
    Vb = V_base[b]
    c = (v_fake - abs(Vb)) * np.exp(1j * np.angle(Vb))
    col = layout.column(b)
    rows = np.where(np.abs(col) > 1e-9)[0]
    inv = {r: k for k, r in layout.row.items()}
    if mode == "simple":
        # prefer the voltage channel at the target, otherwise the largest current sensitivity
        vrow = [r for r in rows if layout.pmus[inv[r][0]]["bus"] == target_bus and inv[r][1] == 0]
        rows = vrow if vrow else [rows[np.argmax(np.abs(col[rows]))]]
    deltas = {}
    for r in rows:
        p, ch = inv[r]
        d = col[r] * c
        deltas.setdefault(layout.pmus[p]["bus"], []).append(
            {"ch": int(ch), "dre": float(d.real), "dim": float(d.imag),
             "hre": float(col[r].real), "him": float(col[r].imag)})
    # if the attacker holds the target bus's own PMU it reads the true voltage every
    # frame and recomputes c, so the falsification tracks the changing grid state
    ref = {"bus": target_bus, "ch": 0} if target_bus in deltas else None
    return {"target_bus": target_bus, "v_fake": v_fake, "mode": mode, "ref": ref,
            "true_v_at_plan": float(abs(Vb)), "compromised_pmus": sorted(deltas), "deltas": deltas}
