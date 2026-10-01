"""Machine data for GridPACK's dynamic simulation (dsf_server).

A grid directory may hold PSS/E dynamic data:

  dynamics.dyr    generator, exciter and governor models (GENCLS, GENROU, GENSAL, IEEET1,
                  SEXS, ESST1A, EXDC1, TGOV1, ... as GridPACK reads them)
  dynamics.json   {"source": "...", "mbase": {"<bus>": MVA, ...}}  machine bases, since the
                  .dyr parameters are per unit on them

Generators without such data get typical parameters (GENROU round-rotor machine, SEXS
exciter, TGOV1 steam governor) on a machine base sized from their output, so every grid can
run dynamically; the run summary says which data were used.
"""
import json, os, re

# typical data, per unit on the machine base
GENROU = [6.0, 0.05, 1.0, 0.05, 4.0, 0.0, 1.8, 1.7, 0.3, 0.55, 0.25, 0.15, 0.0, 0.0]
SEXS = [0.1, 10.0, 100.0, 0.1, 0.0, 5.0]          # TA/TB, TB, K, TE, EMIN, EMAX
TGOV1 = [0.05, 0.5, 1.1, 0.0, 2.1, 7.0, 0.0]      # R, T1, VMAX, VMIN, T2, T3, Dt

# position of the subtransient (or transient) reactance in the generator records, used as the
# source impedance GridPACK takes from the network file, and of the inertia constant H
XSOURCE = {"GENROU": 10, "GENSAL": 8}
INERTIA = {"GENROU": 4, "GENSAL": 3, "GENCLS": 0}


def read_dyr(text):
    """[(bus, model, id, [params])] of a .dyr file; '//' starts a comment."""
    text = re.sub(r"//[^\n]*", "", text)
    out = []
    for rec in text.split("/"):
        f = [x.strip() for x in rec.replace("\n", " ").split(",") if x.strip()]
        if len(f) < 3:
            continue
        try:
            bus = int(float(f[0]))
            params = [float(x) for x in f[3:]]
        except ValueError:
            continue
        out.append((bus, f[1].strip("'\" ").upper(), f[2].strip("'\" "), params))
    return out


def gen_ids(topo):
    """(bus, id, gen) of the in-service generators, ids numbered per bus as rawio writes them."""
    count, out = {}, []
    for g in topo["gens"]:
        count[g["bus"]] = count.get(g["bus"], 0) + 1
        if g["status"]:
            out.append((g["bus"], str(count[g["bus"]]), g))
    return out


def machine_data(topo, grid_dir=None):
    """Dynamic data for every in-service generator of `topo`.

    Returns (dyr_text, machines, info): machines maps (bus, id) to {"mbase", "xsource"} for the
    network file and "h" (inertia constant, s); info says how many machines use the grid's own data and how many typical
    data."""
    records, mbase, source = [], {}, None
    if grid_dir and os.path.exists(os.path.join(grid_dir, "dynamics.dyr")):
        records = read_dyr(open(os.path.join(grid_dir, "dynamics.dyr")).read())
        meta = os.path.join(grid_dir, "dynamics.json")
        if os.path.exists(meta):
            m = json.load(open(meta))
            mbase = {str(k): float(v) for k, v in m.get("mbase", {}).items()}
            source = m.get("source")
        source = source or "dynamics.dyr"
    by_gen = {}
    for bus, model, gid, p in records:
        by_gen.setdefault((bus, gid), []).append((model, p))

    lines, machines, own, typical = [], {}, 0, 0
    for bus, gid, g in gen_ids(topo):
        recs = by_gen.get((bus, gid))
        gens = [r for r in recs or [] if r[0].startswith("GEN")]
        if gens:
            own += 1
            base = mbase.get(str(bus)) or mbase.get(f"{bus}:{gid}") or 100.0
            model, p = gens[0]
            k = XSOURCE.get(model)
            xs = p[k] if k is not None and k < len(p) else 0.3
            k = INERTIA.get(model)
            h = p[k] if k is not None and k < len(p) else GENROU[4]
            for model, p in recs:
                lines.append(f"{bus}, '{model}', '{gid}', " + ", ".join(f"{x:g}" for x in p) + " /")
        else:
            typical += 1
            base = max(100.0, 1.25 * abs(g["pg"]))
            xs, h = GENROU[10], GENROU[4]
            lines.append(f"{bus}, 'GENROU', '{gid}', " + ", ".join(f"{x:g}" for x in GENROU) + " /")
            lines.append(f"{bus}, 'SEXS', '{gid}', " + ", ".join(f"{x:g}" for x in SEXS) + " /")
            if g["pg"] > 0:
                lines.append(f"{bus}, 'TGOV1', '{gid}', " + ", ".join(f"{x:g}" for x in TGOV1) + " /")
        machines[(bus, gid)] = {"mbase": base, "xsource": xs, "h": h}
    info = {"machines": own + typical, "from_data": own, "typical": typical,
            "source": source if own else "typical data"}
    if own and typical:
        info["source"] = f"{source} ({own}) + typical data ({typical})"
    return "\n".join(lines) + "\n", machines, info
