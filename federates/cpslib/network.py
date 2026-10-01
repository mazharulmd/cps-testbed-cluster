"""Network model built from cases/<name>/topology.json (MATPOWER conventions)."""
import json
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve


class Network:
    def __init__(self, topo):
        if isinstance(topo, str):
            with open(topo) as fh:
                topo = json.load(fh)
        self.base = topo["baseMVA"]
        self.buses = topo["buses"]
        self.gens = topo["gens"]
        self.branches = [b for b in topo["branches"] if b["status"]]
        self.bus_ids = [b["id"] for b in self.buses]
        self.idx = {b: i for i, b in enumerate(self.bus_ids)}
        self.n = len(self.bus_ids)
        self._build_admittances()

    def _build_admittances(self):
        """Branch admittances in MATPOWER form: If = Yf V, It = Yt V, Ybus = Cf'Yf + Ct'Yt + diag(Ysh)."""
        nl, n = len(self.branches), self.n
        Ytt = np.zeros(nl, complex); Yff = np.zeros(nl, complex)
        Yft = np.zeros(nl, complex); Ytf = np.zeros(nl, complex)
        f = np.zeros(nl, int); t = np.zeros(nl, int)
        for k, br in enumerate(self.branches):
            ys = 1.0 / complex(br["r"], br["x"])
            bc = br["b"]
            tap = br["tap"] if br["tap"] else 1.0
            tap = tap * np.exp(1j * np.deg2rad(br["shift"]))
            Ytt[k] = ys + 1j * bc / 2
            Yff[k] = Ytt[k] / (tap * np.conj(tap))
            Yft[k] = -ys / np.conj(tap)
            Ytf[k] = -ys / tap
            f[k], t[k] = self.idx[br["from"]], self.idx[br["to"]]
        self.f, self.t = f, t
        # sparse so that grids with thousands of buses fit in memory
        rows = np.arange(nl)
        self.Yf = sp.csr_matrix((np.r_[Yff, Yft], (np.r_[rows, rows], np.r_[f, t])), shape=(nl, n))
        self.Yt = sp.csr_matrix((np.r_[Ytf, Ytt], (np.r_[rows, rows], np.r_[f, t])), shape=(nl, n))
        ysh = np.array([complex(b["gs"], b["bs"]) / self.base for b in self.buses])
        Cf = sp.csr_matrix((np.ones(nl), (rows, f)), shape=(nl, n))
        Ct = sp.csr_matrix((np.ones(nl), (rows, t)), shape=(nl, n))
        self.Ybus = (Cf.T @ self.Yf + Ct.T @ self.Yt + sp.diags(ysh)).tocsr()

    def adjacency(self):
        """Bus-to-bus connectivity matrix including self connections (for PMU placement)."""
        n = self.n
        A = sp.coo_matrix((np.ones(2 * len(self.f) + n), (np.r_[self.f, self.t, np.arange(n)],
                                                           np.r_[self.t, self.f, np.arange(n)])), shape=(n, n))
        A = A.tocsr()
        A.data[:] = 1
        return A

    def solve_pf(self, pd=None, qd=None, vset=None, tol=1e-9, max_it=30, V_init=None):
        """Newton-Raphson power flow (reference solver; loads in MW/MVAr, vset {bus_id: pu}).
        Starts from V_init, else from the voltages stored with the case (vm/va, as MATPOWER
        does), else flat."""
        n, base = self.n, self.base
        pd = np.array([b["pd"] for b in self.buses]) if pd is None else np.asarray(pd, float)
        qd = np.array([b["qd"] for b in self.buses]) if qd is None else np.asarray(qd, float)
        types = np.array([b["type"] for b in self.buses])
        pg = np.zeros(n)
        if V_init is not None:
            V0, A0 = np.abs(V_init).astype(float), np.angle(V_init)
        else:
            V0 = np.array([b.get("vm", 1.0) for b in self.buses])
            A0 = np.deg2rad([b.get("va", 0.0) for b in self.buses])
        for g in self.gens:
            if g["status"]:
                i = self.idx[g["bus"]]
                pg[i] += g["pg"]; V0[i] = g["vg"]
        if vset:
            for b, v in vset.items():
                V0[self.idx[b]] = v
        # buses whose generators are all off become PQ
        has_gen = np.zeros(n, bool)
        for g in self.gens:
            if g["status"]:
                has_gen[self.idx[g["bus"]]] = True
        types = np.where((types == 2) & ~has_gen, 1, types)
        ref = np.where(types == 3)[0]; pv = np.where(types == 2)[0]; pq = np.where(types == 1)[0]
        Sbus = (pg - pd - 1j * qd) / base
        V = V0 * np.exp(1j * A0)
        pvpq = np.r_[pv, pq]
        for it in range(max_it):
            mis = V * np.conj(self.Ybus @ V) - Sbus
            F = np.r_[mis[pvpq].real, mis[pq].imag]
            if np.max(np.abs(F)) < tol:
                return V, it, True
            Ibus = self.Ybus @ V
            # MATPOWER's dSbus_dV with sparse matrices
            dV, dI, dVn = sp.diags(V), sp.diags(Ibus), sp.diags(V / np.abs(V))
            dS_dVm = dV @ (self.Ybus @ dVn).conj() + dI.conj() @ dVn
            dS_dVa = 1j * dV @ (dI - self.Ybus @ dV).conj()
            dS_dVa, dS_dVm = dS_dVa.tocsr(), dS_dVm.tocsr()
            J = sp.bmat([[dS_dVa[pvpq][:, pvpq].real, dS_dVm[pvpq][:, pq].real],
                         [dS_dVa[pq][:, pvpq].imag, dS_dVm[pq][:, pq].imag]], format="csc")
            dx = spsolve(J, -F)
            Va = np.angle(V); Vm = np.abs(V)
            Va[pvpq] += dx[:len(pvpq)]; Vm[pq] += dx[len(pvpq):]
            V = Vm * np.exp(1j * Va)
        return V, max_it, False
