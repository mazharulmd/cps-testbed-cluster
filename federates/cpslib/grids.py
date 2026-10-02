"""Grid models: the built-in IEEE cases and grids uploaded by users.

An uploaded grid is a MATPOWER case file (.m, the format MATPOWER, PSS/E converters such as
MATPOWER's psse2mpc and most published test systems use) or a testbed topology.json. It is
converted to the testbed's own files in <CPS_GRIDS>/<grid id>/:

  topology.json   buses, branches and generators used by every federate
  case.raw        PSS/E v23 file for GridPACK (rewritten every run with the current loads)
  reference.csv   power-flow solution of the uploaded operating point (testbed NR solver)
  info.json       summary shown in the dashboard (size, generator buses, PMUs needed)
  <original file>
"""
import json, os, re, shutil, time
import numpy as np

from .network import Network
from .placement import optimal_placement
from .rawio import write_raw

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = os.environ.get("CPS_CASES", os.path.join(HERE, "..", "..", "cases"))
GRIDS = os.environ.get("CPS_GRIDS", os.path.join(HERE, "..", "..", "results", "grids"))
BUILTIN = ("14", "30", "39", "57", "118", "300")
MAX_BUSES = 20000

# MATPOWER column indices
BUS_I, BUS_TYPE, PD, QD, GS, BS, BUS_AREA, VM, VA, BASE_KV, ZONE = range(11)
GEN_BUS, PG, QG, QMAX, QMIN, VG, MBASE, GEN_STATUS = range(8)
F_BUS, T_BUS, BR_R, BR_X, BR_B, RATE_A, RATE_B, RATE_C, TAP, SHIFT, BR_STATUS = range(11)


class GridError(ValueError):
    pass


# ---------------------------------------------------------------- MATPOWER
def _matrix(text, field, mincols):
    m = re.search(r"mpc\." + field + r"\s*=\s*\[(.*?)\]\s*;", text, re.S)
    if not m:
        raise GridError(f"mpc.{field} not found")
    rows = []
    for line in re.split(r"[;\n]", m.group(1)):
        vals = [v for v in re.split(r"[\s,]+", line.strip()) if v]
        if not vals:
            continue
        try:
            rows.append([float(v.replace("Inf", "inf")) for v in vals])
        except ValueError:
            raise GridError(f"mpc.{field}: cannot read row '{line.strip()[:60]}'")
    if not rows:
        raise GridError(f"mpc.{field} is empty")
    width = min(len(r) for r in rows)
    if width < mincols:
        raise GridError(f"mpc.{field} needs at least {mincols} columns, found {width}")
    return np.array([r[:width] for r in rows])


def parse_matpower(text):
    """Read a MATPOWER case (version 2) into a ppc dict of numpy arrays."""
    text = re.sub(r"%[^\n]*", "", text)                       # comments
    text = re.sub(r"mpc\.\w+\s*=\s*\{.*?\}\s*;", "", text, flags=re.S)   # cell arrays (names)
    m = re.search(r"mpc\.baseMVA\s*=\s*([0-9.eE+-]+)", text)
    if not m:
        raise GridError("mpc.baseMVA not found: is this a MATPOWER case file?")
    ppc = {"baseMVA": float(m.group(1)),
           "bus": _matrix(text, "bus", 13), "gen": _matrix(text, "gen", 10), "branch": _matrix(text, "branch", 11)}
    return ppc


def ppc_topology(ppc):
    """Testbed topology from MATPOWER data (isolated buses and their elements removed)."""
    bus, gen, br = ppc["bus"], ppc["gen"], ppc["branch"]
    bus = bus[bus[:, BUS_TYPE] != 4]
    ids = set(int(b) for b in bus[:, BUS_I])
    gen = gen[[int(g) in ids for g in gen[:, GEN_BUS]]]
    br = br[[int(f) in ids and int(t) in ids for f, t in br[:, [F_BUS, T_BUS]]]]
    return {
        "baseMVA": float(ppc["baseMVA"]),
        "buses": [{"id": int(b[BUS_I]), "type": int(b[BUS_TYPE]), "pd": float(b[PD]), "qd": float(b[QD]),
                   "gs": float(b[GS]), "bs": float(b[BS]), "base_kv": float(b[BASE_KV]),
                   "area": int(b[BUS_AREA]), "vm": float(b[VM]), "va": float(b[VA])} for b in bus],
        "gens": [{"bus": int(g[GEN_BUS]), "pg": float(g[PG]), "vg": float(g[VG]), "qmax": float(g[QMAX]),
                  "qmin": float(g[QMIN]), "status": int(g[GEN_STATUS] > 0)} for g in gen],
        "branches": [{"from": int(r[F_BUS]), "to": int(r[T_BUS]), "r": float(r[BR_R]), "x": float(r[BR_X]),
                      "b": float(r[BR_B]), "tap": float(r[TAP]), "shift": float(r[SHIFT]),
                      "status": int(r[BR_STATUS] > 0)} for r in br],
    }


def check_topology(topo):
    buses = topo.get("buses") or []
    if not buses:
        raise GridError("the grid has no buses")
    if len(buses) > MAX_BUSES:
        raise GridError(f"{len(buses)} buses; the limit is {MAX_BUSES}")
    ids = [b["id"] for b in buses]
    if len(set(ids)) != len(ids):
        raise GridError("bus numbers are not unique")
    if sum(1 for b in buses if b["type"] == 3) != 1:
        raise GridError("the grid needs exactly one slack (type 3) bus")
    s = set(ids)
    for g in topo["gens"]:
        if g["bus"] not in s:
            raise GridError(f"generator at unknown bus {g['bus']}")
    for r in topo["branches"]:
        if r["from"] not in s or r["to"] not in s:
            raise GridError(f"branch {r['from']}-{r['to']} connects an unknown bus")
        if r["status"] and abs(complex(r["r"], r["x"])) == 0:
            raise GridError(f"branch {r['from']}-{r['to']} has zero impedance")


# ---------------------------------------------------------------- registry
def slug(name):
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower()[:30]
    return s or "grid"


def builtin_dir(case):
    return os.path.join(CASES, f"ieee{case}")


def grid_dir(grid_id):
    """Directory of a grid: '118' or 'ieee118' for built-in cases, else an uploaded grid id."""
    g = str(grid_id)
    if g.startswith("ieee") and g[4:] in BUILTIN:
        g = g[4:]
    if g in BUILTIN:
        return builtin_dir(g)
    if not re.match(r"^[a-z0-9_-]{1,48}$", g):
        raise GridError("bad grid id")
    d = os.path.join(GRIDS, g)
    if not os.path.exists(os.path.join(d, "topology.json")):
        raise GridError(f"unknown grid '{g}'")
    return d


def describe(topo, name, extra=None):
    net = Network(topo)
    t0 = time.time()
    V, it, ok = net.solve_pf()
    if not ok:
        raise GridError("the power flow of the uploaded operating point does not converge "
                        "(check the data, units and the slack bus)")
    t_nr = time.time() - t0
    pmus = optimal_placement(net, 1)[0]
    vm = np.abs(V)
    info = {"name": name, "buses": net.n, "branches": len(net.branches),
            "gens": sorted({g["bus"] for g in topo["gens"] if g["status"]}),
            "bus_ids": net.bus_ids, "pmus_min": len(pmus),
            "load_mw": round(sum(b["pd"] for b in topo["buses"]), 1),
            "max_v": round(float(vm.max()), 4), "max_v_bus": net.bus_ids[int(vm.argmax())],
            "min_v": round(float(vm.min()), 4), "nr_iterations": it, "nr_time_s": round(t_nr, 3)}
    info.update(extra or {})
    return info, V


def save_upload(filename, data):
    """Convert an uploaded grid file and register it. Returns its info dict."""
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    base = os.path.basename(filename or "grid")
    stem, ext = os.path.splitext(base)
    ext = ext.lower()
    if ext == ".m":
        topo = ppc_topology(parse_matpower(text))
    elif ext == ".json":
        try:
            topo = json.loads(text)
        except json.JSONDecodeError as e:
            raise GridError(f"not valid JSON: {e}")
        for k in ("baseMVA", "buses", "gens", "branches"):
            if k not in topo:
                raise GridError(f"topology.json needs '{k}'")
    elif ext == ".raw":
        raise GridError("PSS/E .raw files are not read directly yet; convert with MATPOWER "
                        "(mpc = psse2mpc('file.raw'); savecase('file.m', mpc)) and upload the .m file")
    else:
        raise GridError("upload a MATPOWER case (.m) or a testbed topology (.json)")
    check_topology(topo)
    topo["name"] = stem
    info, V = describe(topo, stem, {"source": base, "uploaded": time.strftime("%Y-%m-%d %H:%M:%S")})
    gid = f"{slug(stem)}-{int(time.time()) % 100000:05d}"
    d = os.path.join(GRIDS, gid)
    os.makedirs(d, exist_ok=True)
    try:
        with open(os.path.join(d, base), "w") as fh:
            fh.write(text)
        with open(os.path.join(d, "topology.json"), "w") as fh:
            json.dump(topo, fh)
        write_raw(os.path.join(d, "case.raw"), topo, title=stem)
        with open(os.path.join(d, "reference.csv"), "w") as fh:
            fh.write("bus_id,vm_pu,va_deg\n")
            for b, v in zip(info["bus_ids"], V):
                fh.write(f"{b},{abs(v):.6f},{np.rad2deg(np.angle(v)):.4f}\n")
        info["id"] = gid
        with open(os.path.join(d, "info.json"), "w") as fh:
            json.dump(info, fh)
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return info


_builtin_info = {}


def list_grids():
    out = []
    for c in BUILTIN:
        if c not in _builtin_info:
            topo = json.load(open(os.path.join(builtin_dir(c), "topology.json")))
            info, _ = describe(topo, f"IEEE {c}-bus")
            info.update(id=f"ieee{c}", builtin=True)
            _builtin_info[c] = info
        out.append(_builtin_info[c])
    if os.path.isdir(GRIDS):
        for g in sorted(os.listdir(GRIDS)):
            p = os.path.join(GRIDS, g, "info.json")
            if os.path.exists(p):
                info = json.load(open(p))
                info["builtin"] = False
                out.append(info)
    return out


def get_info(grid_id):
    for g in list_grids():
        if g["id"] == grid_id or (g.get("builtin") and g["id"] == f"ieee{grid_id}"):
            return g
    raise GridError(f"unknown grid '{grid_id}'")


def lines(grid_id):
    """(from, to) of the in-service branches of a grid, without duplicates."""
    topo = json.load(open(os.path.join(grid_dir(grid_id), "topology.json")))
    return sorted({(r["from"], r["to"]) for r in topo["branches"] if r.get("status", 1)})


def delete(grid_id):
    d = grid_dir(grid_id)
    if os.path.dirname(os.path.abspath(d)) != os.path.abspath(GRIDS):
        raise GridError("built-in grids cannot be deleted")
    shutil.rmtree(d)
