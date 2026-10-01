"""Write a PSS/E v23 network file (the layout GridPACK reads) from topology.json data,
optionally with modified loads and generator voltage setpoints, and with the machine bases
and source reactances a dynamic simulation needs (cpslib.dynamics)."""


def write_raw(path, topo, pd=None, qd=None, vset=None, title="CPS testbed case", machines=None):
    base = topo["baseMVA"]
    L = [f"0  {base:.3f}", f" {title}", " written by cpslib.rawio"]
    for i, b in enumerate(topo["buses"]):
        p = b["pd"] if pd is None else pd[i]
        q = b["qd"] if qd is None else qd[i]
        kv = b["base_kv"] if b["base_kv"] > 0 else 100.0
        L.append(f"{b['id']:7d},{b['type']:2d},{p:10.4f},{q:10.4f},{b['gs']:10.3f},{b['bs']:10.3f},"
                 f"{b['area']:4d},{b.get('vm', 1.0):8.5f},{b.get('va', 0.0):9.4f},'BUS-{b['id']:<8d}',{kv:9.4f},   1")
    L.append("0 / END OF BUS DATA, BEGIN GENERATOR DATA")
    count = {}
    for g in topo["gens"]:
        i = g["bus"]; count[i] = count.get(i, 0) + 1
        vs = vset.get(i, g["vg"]) if vset else g["vg"]
        m = (machines or {}).get((i, str(count[i])), {})
        L.append(f"{i:7d},'{count[i]:<2d}',{g['pg']:10.3f},     0.000,{g['qmax']:10.3f},{g['qmin']:10.3f},"
                 f"{vs:8.5f},     0,{m.get('mbase', base):10.3f},   0.00000,{m.get('xsource', 1.0):10.5f},"
                 f"   0.00000,   0.00000,   1.00000,"
                 f"{g['status']},  100.0,  9999.000, -9999.000")
    L.append("0 / END OF GENERATOR DATA, BEGIN BRANCH DATA")
    ckt = {}
    for r in topo["branches"]:
        key = (min(r["from"], r["to"]), max(r["from"], r["to"])); ckt[key] = ckt.get(key, 0) + 1
        L.append(f"{r['from']:7d},{r['to']:7d},'{ckt[key]:<2d}',{r['r']:10.5f},{r['x']:10.5f},{r['b']:10.5f},"
                 f"     0.00,     0.00,     0.00,{r['tap']:8.5f},{r['shift']:8.3f},"
                 f" 0.00000, 0.00000, 0.00000, 0.00000,{r['status']}")
    slack = next(b["id"] for b in topo["buses"] if b["type"] == 3)
    L.append("0 / END OF BRANCH DATA, BEGIN TRANSFORMER ADJUSTMENT DATA")
    L.append("0 / END OF TRANSFORMER ADJUSTMENT DATA, BEGIN AREA DATA")
    for a in sorted({b["area"] for b in topo["buses"]}):
        L.append(f"{a:4d},{slack:7d},     0.0,  3.000,'AREA_{a:<7d}'")
    L += ["0 / END OF AREA DATA, BEGIN TWO-TERMINAL DC DATA",
          "0 / END OF TWO-TERMINAL DC DATA, BEGIN SWITCHED SHUNT DATA",
          "0 / END OF SWITCHED SHUNT DATA, BEGIN IMPEDANCE CORRECTION DATA",
          "0 / END OF IMPEDANCE CORRECTION DATA, BEGIN MULTI-TERMINAL DC DATA",
          "0 / END OF MULTI-TERMINAL DC DATA, BEGIN MULTI-SECTION LINE DATA",
          "0 / END OF MULTI-SECTION LINE DATA, BEGIN ZONE DATA",
          "    1,'ZONE_1      '",
          "0 / END OF ZONE DATA, BEGIN INTER-AREA TRANSFER DATA",
          "0 / END OF INTER-AREA TRANSFER DATA, BEGIN OWNER DATA",
          "    1,'OWNER_1     '",
          "0 / END OF OWNER DATA, BEGIN FACTS DEVICE DATA",
          "0 / END OF FACTS DEVICE DATA"]
    with open(path, "w") as fh:
        fh.write("\n".join(L) + "\n")
