"""PMU channel layout and the linear phasor measurement model.

A PMU at bus i reports channel 0 = voltage phasor V_i, then one current phasor for
every in-service branch incident to i (the current leaving bus i on that branch).
With all quantities complex, the measurements are linear in the bus voltages:

    z = H V,   H rows = unit vector (voltage) or a row of Yf / Yt (current)
"""
import numpy as np
import scipy.sparse as sp


class PmuLayout:
    def __init__(self, net, pmu_buses):
        self.net = net
        self.pmus = []          # [{"bus": b, "id": k, "channels": [(kind, branch_idx, end)]}]
        incident = {}
        for br, (f, t) in enumerate(zip(net.f, net.t)):
            incident.setdefault(f, []).append((br, "from"))
            incident.setdefault(t, []).append((br, "to"))
        rows = []
        for k, b in enumerate(pmu_buses):
            i = net.idx[b]
            ch = [("V", -1, "")]
            rows.append(sp.csr_matrix(([1.0 + 0j], ([0], [i])), shape=(1, net.n)))
            for br, end in sorted(incident.get(i, [])):
                ch.append(("I", br, end))
                rows.append(net.Yf[br] if end == "from" else net.Yt[br])
            self.pmus.append({"bus": b, "id": k + 1, "channels": ch})
        self.H = sp.vstack(rows, format="csr")
        self.Hc = self.H.tocsc()
        # (pmu index, channel index) -> row of H
        self.row = {}
        r = 0
        for p, pm in enumerate(self.pmus):
            for c in range(len(pm["channels"])):
                self.row[(p, c)] = r; r += 1
        # buses each PMU makes observable: its own and the far ends of its measured branches
        self.sees = [{net.idx[pm["bus"]]} | {int(net.t[br]) if end == "from" else int(net.f[br])
                                             for kind, br, end in pm["channels"] if kind == "I"}
                     for pm in self.pmus]

    def column(self, bus_index):
        """Dense column of H for one bus: how strongly each channel depends on that bus voltage."""
        return np.asarray(self.Hc[:, bus_index].todense()).ravel()

    def measure(self, V):
        """Noise-free phasors per PMU, as nested lists [[re, im], ...]."""
        z = self.H @ V
        out, r = [], 0
        for pm in self.pmus:
            m = len(pm["channels"])
            out.append([[float(x.real), float(x.imag)] for x in z[r:r + m]])
            r += m
        return out

    def channel_names(self, p):
        pm, net = self.pmus[p], self.net
        names = []
        for kind, br, end in pm["channels"]:
            if kind == "V":
                names.append(f"V{pm['bus']}")
            else:
                f, t = net.bus_ids[net.f[br]], net.bus_ids[net.t[br]]
                names.append(f"I{f}-{t}" if end == "from" else f"I{t}-{f}")
        return names

    def describe(self):
        return [{"bus": pm["bus"], "id": pm["id"], "channels": self.channel_names(p)}
                for p, pm in enumerate(self.pmus)]
