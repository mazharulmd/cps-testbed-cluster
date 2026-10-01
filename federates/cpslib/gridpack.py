"""GridPACK power flow for the grid federate: pf_server (gridpack/pf_server), a long-lived
MPI job that the federate drives over stdin/stdout."""
import os, shutil, subprocess
import numpy as np

from .rawio import write_raw


# ---------------------------------------------------------------- persistent MPI server
PF_SERVER = os.environ.get("CPS_PF_SERVER", "/opt/cps/gridpack/bin/pf_server")
SERVER_XML = """<?xml version="1.0" encoding="utf-8"?>
<Configuration>
  <Powerflow>
    <networkConfiguration> {raw} </networkConfiguration>
    <maxIteration>50</maxIteration>
    <tolerance>1.0e-6</tolerance>
    <qlim>false</qlim>
    <LinearSolver>
      <PETScOptions>
        -ksp_type preonly
        -pc_type lu
        -pc_factor_mat_solver_type mumps
      </PETScOptions>
    </LinearSolver>
  </Powerflow>
</Configuration>
"""


def server_available():
    return os.path.exists(PF_SERVER) and shutil.which("mpirun") is not None


class GridPackMPISolver:
    """Runs GridPACK as one long-lived MPI job (pf_server) spread over `np` ranks, which may
    sit on other cluster nodes (`hostfile`). The network is read and partitioned once; each
    solve() only sends the changed loads and generator setpoints to rank 0's stdin."""

    def __init__(self, net, topo, workdir, np_=1, hostfile=None, log=None):
        self.net, self.topo, self.dir = net, topo, os.path.abspath(workdir)
        os.makedirs(self.dir, exist_ok=True)
        raw = os.path.join(self.dir, "case.raw")
        write_raw(raw, topo)
        xml = os.path.join(self.dir, "input.xml")
        with open(xml, "w") as fh:
            fh.write(SERVER_XML.format(raw=raw))
        # GridPACK only creates load records for buses with a non-zero load in the .raw file
        self.load_buses = [i for i, b in enumerate(topo["buses"]) if b["pd"] != 0 or b["qd"] != 0]
        # generator ids are numbered per bus in file order, as rawio writes them
        self.gens, count = [], {}
        for g in topo["gens"]:
            count[g["bus"]] = count.get(g["bus"], 0) + 1
            if g["status"]:
                self.gens.append((g["bus"], count[g["bus"]], g["vg"]))
        cmd = ["mpirun", "-np", str(int(np_)), "--wdir", self.dir,
               "-x", "LD_LIBRARY_PATH", "-x", "PATH"]
        if hostfile:
            cmd += ["--hostfile", hostfile]
        cmd += [PF_SERVER, xml]
        self.np, self.hostfile = int(np_), hostfile
        self.log = open(log or os.path.join(self.dir, "pf_server.log"), "w")
        self.log.write(" ".join(cmd) + "\n"); self.log.flush()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1)
        self.ready = self._read_until("@@READY")
        self.setup_s = float(self.ready.get("t_setup", 0))
        self.last = {}

    def _read_until(self, tag, collect=None):
        for line in self.proc.stdout:
            if not line.startswith("@@"):
                self.log.write(line); self.log.flush()
                continue
            parts = line.split()
            if parts[0] == "@@V" and collect is not None:
                collect.append((int(parts[1]), float(parts[2]), float(parts[3])))
            elif parts[0] == tag:
                return dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        self.log.flush()
        raise RuntimeError(f"pf_server exited (code {self.proc.wait()}); see {self.log.name}")

    def solve(self, pd, qd, vset):
        lines = [f"LOAD {self.topo['buses'][i]['id']} {pd[i]:.6f} {qd[i]:.6f}" for i in self.load_buses]
        lines += [f"VSET {bus} {gid} {vset.get(bus, vg):.6f}" for bus, gid, vg in self.gens]
        self.proc.stdin.write("\n".join(lines + ["SOLVE"]) + "\n")
        self.proc.stdin.flush()
        # the server answers with @@RESULT, one @@V line per bus, then @@END
        self.last = head = self._read_until("@@RESULT")
        rows = []
        self._read_until("@@END", collect=rows)
        V = np.zeros(self.net.n, complex)
        for bus, vm, va in rows:
            V[self.net.idx[bus]] = vm * np.exp(1j * np.deg2rad(va))
        ok = head.get("ok") == "1" and len(rows) == self.net.n
        return V, 0, ok

    def close(self):
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write("QUIT\n"); self.proc.stdin.flush()
                self.proc.wait(timeout=30)
            except Exception:
                self.proc.kill()
        self.log.close()
