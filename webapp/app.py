#!/usr/bin/env python3
"""CPS testbed web application: configure, queue and inspect co-simulation experiments.

Runs one experiment at a time (federates share one HELICS broker) through
federates/run_experiment.py and serves the results as JSON for the browser UI.

Environment:
  CPS_WEB_USER / CPS_WEB_PASSWORD  HTTP basic auth (login disabled if no password is set)
  CPS_RESULTS                      results directory (default <repo>/results/runs)

Start: uvicorn app:app --host 0.0.0.0 --port 8080   (from this directory)
"""
import csv, json, os, queue, re, secrets, subprocess, sys, threading, time
from typing import Optional

import base64
import numpy as np
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

import scenario as scen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
FED = os.path.join(ROOT, "federates")
CASES = os.environ.get("CPS_CASES", os.path.join(ROOT, "cases"))
RESULTS = os.environ.get("CPS_RESULTS", os.path.join(ROOT, "results", "runs"))
os.makedirs(RESULTS, exist_ok=True)
sys.path.insert(0, FED)
from cpslib.network import Network  # noqa: E402
from cpslib.placement import optimal_placement  # noqa: E402
from cpslib import cluster, grids  # noqa: E402

app = FastAPI(title="CPS Testbed")
security = HTTPBasic(auto_error=False)
USER = os.environ.get("CPS_WEB_USER", "admin")
PASSWORD = os.environ.get("CPS_WEB_PASSWORD", "")


def auth(creds: Optional[HTTPBasicCredentials] = Depends(security)):
    if not PASSWORD:
        return
    ok = creds and secrets.compare_digest(creds.username, USER) and secrets.compare_digest(creds.password, PASSWORD)
    if not ok:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": "Basic"})


# ------------------------------------------------------------------ experiment queue
class RunRequest(BaseModel):
    case: str = Field("14", pattern=r"^[A-Za-z0-9_-]{1,48}$")   # 14..300, ieee14..ieee300 or an uploaded grid id
    name: str = Field("web", pattern=r"^[A-Za-z0-9_-]{1,40}$")
    duration: float = Field(10, ge=1, le=120)
    mode: str = Field("qss", pattern=r"^(qss|dynamic)$")
    grid_step: Optional[float] = Field(None, ge=0.005, le=5)    # default 0.5 s (qss) or one PMU frame (dynamic)
    rate: float = Field(30, ge=1, le=120)
    solver: str = Field("gridpack", pattern=r"^(gridpack|builtin)$")
    placement: int = Field(1, ge=1, le=2)
    latency: float = Field(10, ge=0.1, le=2000)
    latency_spread: float = Field(0.5, ge=0, le=0.95)
    jitter: float = Field(2, ge=0, le=500)
    loss: float = Field(0, ge=0, le=0.9)
    pdc_wait: float = Field(20, ge=1, le=2000)
    attack: str = Field("none", pattern=r"^(none|fdi-simple|fdi-stealthy|drop|delay)$")
    target: Optional[int] = Field(None, ge=1, le=99999)
    fake: Optional[float] = Field(None, ge=0.5, le=1.5)
    attack_start: float = Field(3, ge=0, le=60)
    attack_end: float = Field(8, ge=0, le=60)
    attack_delay: float = Field(100, ge=0, le=5000)
    bdd: str = Field("on", pattern=r"^(on|off)$")
    control: str = Field("on", pattern=r"^(on|off)$")
    vmin: float = Field(0.94, ge=0.5, le=1.0)
    vmax: float = Field(1.08, ge=1.0, le=1.5)
    event: str = Field("none", pattern=r"^(none|avr:\d+:[0-9.]+:[0-9.]+|load:\d+:-?[0-9.]+:[0-9.]+|"
                                      r"fault:\d+:[0-9.]+:[0-9.]+|line:\d+:\d+:[0-9.]+|gen:\d+:[0-9.]+)$")
    seed: int = Field(1, ge=1, le=10**6)
    mpi_np: int = Field(1, ge=1, le=256)

    def argv(self):
        a = []
        for k, v in self.model_dump().items():
            if v is None or k == "case":
                continue
            a += [f"--{k.replace('_', '-')}", str(v)]
        c = self.case[4:] if self.case.startswith("ieee") else self.case
        if c in grids.BUILTIN:
            return ["--case", c] + a
        return ["--case", self.case, "--grid", grids.grid_dir(self.case)] + a


jobs = {}           # job id -> dict
job_queue = queue.Queue()
lock = threading.Lock()


CLUSTER = cluster.load()


# MPI slots in use: a run starts only when its GridPACK ranks fit, because MPI ranks
# busy-wait and an oversubscribed node slows every experiment on it many times over
slot_cv = threading.Condition()
slots = {"total": cluster.mpi_slots(CLUSTER), "used": 0}


def ranks_of(job):
    r = job["request"]
    return min(r["mpi_np"], slots["total"]) if r["solver"] == "gridpack" else 1


def worker(slot):
    """One of max_parallel_jobs workers; each owns a HELICS port range so runs can overlap."""
    port = CLUSTER["helics_port_base"] + 100 * (slot + 1)
    while True:
        jid = job_queue.get()
        job = jobs[jid]
        need = ranks_of(job)
        with slot_cv:
            while slots["used"] + need > slots["total"]:
                job["waiting"] = f"for {need} MPI slots"
                slot_cv.wait()
            slots["used"] += need
            job.pop("waiting", None)
        try:
            run_job(job, jid, slot, port)
        finally:
            with slot_cv:
                slots["used"] -= need
                slot_cv.notify_all()


def run_job(job, jid, slot, port):
    job.update(status="running", started=time.time(), worker=slot)
    log_path = os.path.join(RESULTS, f".job_{jid}.log")
    with open(log_path, "w") as log:
        p = subprocess.Popen([sys.executable, os.path.join(FED, "run_experiment.py")] + job["argv"] +
                             ["--helics-port", str(port), "--out", RESULTS],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, cwd=FED)
        for line in p.stdout:
            log.write(line); log.flush()
            m = re.match(r"\[RUN\] (\S+):", line)
            if m:
                job["run_id"] = m.group(1)
        code = p.wait()
    ok = code == 0 and job.get("run_id") and os.path.exists(os.path.join(RESULTS, job["run_id"], "summary.json"))
    job.update(status="done" if ok else "failed", finished=time.time(), log=log_path)


for _slot in range(max(1, int(CLUSTER["max_parallel_jobs"]))):
    threading.Thread(target=worker, args=(_slot,), daemon=True).start()


# ------------------------------------------------------------------ helpers
def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return list(csv.DictReader(fh))


def run_dir(run_id):
    if not re.match(r"^[0-9]{8}_[0-9]{6}_[A-Za-z0-9_-]+$", run_id):
        raise HTTPException(400, "bad run id")
    d = os.path.join(RESULTS, run_id)
    if not os.path.exists(os.path.join(d, "summary.json")):
        raise HTTPException(404, "run not found")
    return d


def thin(n, limit=600):
    return list(range(0, n, max(1, n // limit)))


# ------------------------------------------------------------------ API
@app.get("/", include_in_schema=False)
def index(_=Depends(auth)):
    return FileResponse(os.path.join(HERE, "index.html"))


_case_cache = {}


@app.get("/api/cases")
def cases(_=Depends(auth)):
    if not _case_cache:
        for c in ("14", "30", "39", "57", "118", "300"):
            topo = json.load(open(os.path.join(CASES, f"ieee{c}", "topology.json")))
            net = Network(topo)
            V, _, _ = net.solve_pf()
            _case_cache[c] = {
                "case": c, "buses": net.n, "branches": len(net.branches),
                "gens": sorted({g["bus"] for g in topo["gens"] if g["status"]}),
                "bus_ids": net.bus_ids,
                "pmus_min": len(optimal_placement(net, 1)[0]),
                "max_v_bus": net.bus_ids[int(np.argmax(np.abs(V)))], "max_v": round(float(np.abs(V).max()), 4)}
    return list(_case_cache.values())


def queue_run(req: RunRequest, source=None):
    """Validate a run against its grid and the cluster, then queue it."""
    if req.attack_end <= req.attack_start and req.attack != "none":
        raise HTTPException(422, "attack end must be after attack start")
    try:
        info = grids.get_info(req.case)
    except grids.GridError as e:
        raise HTTPException(422, str(e))
    label = info["name"]
    buses, gens = set(info["bus_ids"]), set(info["gens"])
    if req.target is not None and req.target not in buses:
        raise HTTPException(422, f"target bus {req.target} is not in {label} "
                                 f"(buses {min(buses)}-{max(buses)})")
    if req.event != "none":
        kind, bus = req.event.split(":")[:2]
        bus = int(bus)
        if kind == "avr" and bus not in gens:
            shown = sorted(gens)
            more = f" ... ({len(shown)} in all)" if len(shown) > 40 else ""
            raise HTTPException(422, f"bus {bus} is not a generator bus in {label}; "
                                     f"generator buses: {', '.join(map(str, shown[:40]))}{more}")
        if kind == "load" and bus not in buses:
            raise HTTPException(422, f"load bus {bus} is not in {label}")
    slots = cluster.mpi_slots(CLUSTER)
    if req.solver == "gridpack" and req.mpi_np > slots:
        raise HTTPException(422, f"{req.mpi_np} MPI ranks requested; the cluster has {slots} MPI slots")
    with lock:
        jid = secrets.token_hex(4)
        jobs[jid] = {"id": jid, "status": "queued", "request": req.model_dump(), "argv": req.argv(),
                     "grid": label, "source": source, "submitted": time.time()}
    job_queue.put(jid)
    return jobs[jid]


@app.post("/api/runs")
def submit(req: RunRequest, _=Depends(auth)):
    return queue_run(req)


class Upload(BaseModel):
    filename: str = Field(..., max_length=200)
    content: str = Field(..., max_length=40_000_000)
    encoding: str = Field("text", pattern=r"^(text|base64)$")

    def data(self):
        return base64.b64decode(self.content) if self.encoding == "base64" else self.content.encode()


def _scenarios_from(filename, data):
    try:
        items = scen.parse(data.decode("utf-8", errors="replace"))
    except ValueError as e:
        raise HTTPException(422, f"{filename}: {e}")
    reqs = []
    for sc in items:
        try:
            reqs.append(RunRequest(**sc.run_args()))
        except Exception as e:
            raise HTTPException(422, f"{filename} ({sc.name}): {e}")
    # validate all before queueing any, so a bad entry does not leave half a batch queued
    for r in reqs:
        try:
            grids.get_info(r.case)
        except grids.GridError as e:
            raise HTTPException(422, f"{filename} ({r.name}): {e}")
    return [queue_run(r, source=filename) for r in reqs]


@app.post("/api/scenarios")
def upload_scenario(up: Upload, _=Depends(auth)):
    """Queue the experiment(s) in an uploaded scenario file (YAML or JSON)."""
    return _scenarios_from(up.filename, up.data())


@app.post("/api/scenarios/file")
async def upload_scenario_file(file: UploadFile = File(...), _=Depends(auth)):
    return _scenarios_from(file.filename, await file.read())


@app.get("/api/scenario-template", response_class=PlainTextResponse)
def scenario_template(_=Depends(auth)):
    return open(os.path.join(HERE, "scenario_template.yaml")).read()


def _save_grid(filename, data):
    try:
        info = grids.save_upload(filename, data)
    except grids.GridError as e:
        raise HTTPException(422, f"{filename}: {e}")
    return {k: v for k, v in info.items() if k != "bus_ids"}


@app.get("/api/grids")
def list_grids(_=Depends(auth)):
    return [{k: v for k, v in g.items() if k not in ("bus_ids", "gens")} | {"n_gens": len(g["gens"])}
            for g in grids.list_grids()]


@app.get("/api/grids/{grid_id}")
def grid_info(grid_id: str, _=Depends(auth)):
    try:
        return grids.get_info(grid_id)
    except grids.GridError as e:
        raise HTTPException(404, str(e))


@app.post("/api/grids")
def upload_grid(up: Upload, _=Depends(auth)):
    """Register an uploaded grid (MATPOWER .m or testbed topology .json)."""
    return _save_grid(up.filename, up.data())


@app.post("/api/grids/file")
async def upload_grid_file(file: UploadFile = File(...), _=Depends(auth)):
    return _save_grid(file.filename, await file.read())


@app.delete("/api/grids/{grid_id}")
def delete_grid(grid_id: str, _=Depends(auth)):
    try:
        grids.delete(grid_id)
    except grids.GridError as e:
        raise HTTPException(422, str(e))
    return {"deleted": grid_id}


@app.get("/api/cluster")
def cluster_status(_=Depends(auth)):
    running = [j for j in jobs.values() if j["status"] == "running"]
    return {"nodes": cluster.status(CLUSTER), "mpi_slots": cluster.mpi_slots(CLUSTER), "mpi_slots_used": slots["used"],
            "default_np": CLUSTER["mpi"].get("default_np", 1), "max_parallel_jobs": CLUSTER["max_parallel_jobs"],
            "placement": CLUSTER["placement"], "running": len(running),
            "queued": sum(1 for j in jobs.values() if j["status"] == "queued")}


@app.get("/api/jobs")
def list_jobs(_=Depends(auth)):
    out = []
    for j in sorted(jobs.values(), key=lambda x: -x["submitted"])[:20]:
        item = {k: v for k, v in j.items() if k not in ("argv", "log")}
        lp = j.get("log") or os.path.join(RESULTS, f".job_{j['id']}.log")
        if os.path.exists(lp):
            item["log_tail"] = open(lp).read()[-2000:]
        out.append(item)
    return out


@app.get("/api/runs")
def list_runs(_=Depends(auth)):
    runs = []
    for d in sorted(os.listdir(RESULTS), reverse=True):
        p = os.path.join(RESULTS, d, "summary.json")
        if not os.path.exists(p):
            continue
        s = json.load(open(p))
        meta = json.load(open(os.path.join(RESULTS, d, "meta.json")))
        a = meta["args"]
        runs.append({"id": d, "name": s["name"], "case": a["case"], "grid": s.get("case"), "attack": a["attack"],
                     "mode": a.get("mode", "qss"),
                     "loss": a["loss"], "mpi_np": a.get("mpi_np"),
                     "gridpack_ms": (s.get("gridpack") or {}).get("solve_ms_mean"),
                     "wall_s": s.get("wall_time_s"),
                     "latency": a["latency"], "bdd": a["bdd"], "control": a["control"], "placement": a["placement"],
                     "event": a["event"], "violation_s": s["grid"]["true_violation_time_s"],
                     "detection": s["attack"].get("detection_rate_pct"),
                     "delivery": s["network"]["delivery_ratio"]})
    return runs


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, _=Depends(auth)):
    d = run_dir(run_id)
    meta = json.load(open(os.path.join(d, "meta.json")))
    return {"id": run_id, "summary": json.load(open(os.path.join(d, "summary.json"))), "meta": meta,
            "commands": read_csv(os.path.join(d, "commands_applied.csv"))}


@app.get("/api/live")
def live(run: Optional[str] = None, bus: Optional[int] = None, _=Depends(auth)):
    """Live state of a running experiment, written by its observer federate (live.json).
    Without a running experiment, the final state of the most recent one."""
    active = [j["run_id"] for j in sorted(jobs.values(), key=lambda x: x["submitted"])
              if j["status"] == "running" and j.get("run_id")]
    pick = run if run in active else (active[0] if active else None)
    if pick is None:
        done = [d for d in sorted(os.listdir(RESULTS), reverse=True)
                if os.path.exists(os.path.join(RESULTS, d, "live.json"))]
        pick = run if run in done else (done[0] if done else None)
    if pick is None or not re.match(r"^[0-9]{8}_[0-9]{6}_[A-Za-z0-9_-]+$", pick):
        return {"active": active, "live": None}
    d = os.path.join(RESULTS, pick)
    if bus is not None:
        # the observer reads this file and switches the per-bus series (it keeps the whole history)
        tmp = os.path.join(d, ".watch.tmp")
        with open(tmp, "w") as fh:
            json.dump({"bus": bus}, fh)
        os.replace(tmp, os.path.join(d, "watch.json"))
    try:
        state = json.load(open(os.path.join(d, "live.json")))
    except (OSError, ValueError):
        state = {"run_id": pick, "starting": True}
    if state.get("done") and bus is not None and bus != state.get("bus") and \
            os.path.exists(os.path.join(d, "summary.json")):
        # the observer has finished; take the other bus from the saved results
        try:
            ser = series(pick, bus)
            state.update(bus=bus, truth=ser["truth"], estimate=ser["estimate"])
        except HTTPException:
            pass
    return {"active": active, "live": state}


@app.get("/api/runs/{run_id}/series")
def series(run_id: str, bus: Optional[int] = None, _=Depends(auth)):
    d = run_dir(run_id)
    meta = json.load(open(os.path.join(d, "meta.json")))
    truth = read_csv(os.path.join(d, "grid_truth.csv"))
    truth = [truth[i] for i in thin(len(truth))]
    est = read_csv(os.path.join(d, "cc_estimates.csv"))
    cc = read_csv(os.path.join(d, "cc_log.csv"))
    frames = read_csv(os.path.join(d, "frames.csv"))
    bus = bus or meta["target_bus"]
    col = f"v{bus}"
    if truth and col not in truth[0]:
        raise HTTPException(404, "bus not in this case")
    out = {"bus": bus, "mode": meta["args"].get("mode", "qss"), "vmax": meta["args"]["vmax"], "vmin": meta["args"]["vmin"],
           "attack_window": [meta["args"]["attack_start"], meta["args"]["attack_end"]] if meta["args"]["attack"] != "none" else None,
           "truth": [[float(r["t"]), float(r[col])] for r in truth],
           "truth_max": [[float(r["t"]), max(float(v) for k, v in r.items() if k != "t")] for r in truth]}
    idx = thin(len(est))
    out["estimate"] = [[float(est[i]["t"]), float(est[i][col])] for i in idx]
    idx = thin(len(cc))
    out["chi2"] = [[float(cc[i]["t"]), float(cc[i]["first_J"]) if "first_J" in cc[i] else float(cc[i]["J"]),
                    float(cc[i]["threshold"]), int(cc[i]["first_alarm"])] for i in idx]
    out["est_max"] = [[float(cc[i]["t"]), float(cc[i]["max_v_est"])] for i in idx]
    out["completeness"] = [[float(cc[i]["t"]), int(cc[i]["pmus_received"]) / max(int(cc[i]["pmus_expected"]), 1)] for i in idx]
    lat = [float(f["latency_ms"]) for f in frames if f["status"] == "delivered"]
    if lat:
        hist, edges = np.histogram(lat, bins=30)
        out["latency_hist"] = [[round(float((edges[i] + edges[i + 1]) / 2), 2), int(hist[i])] for i in range(len(hist))]
    per = {}
    for f in frames:
        b = f["bus"]; per.setdefault(b, [0, 0, 0])
        per[b][1] += 1
        if f["status"] == "delivered":
            per[b][0] += 1
        if f["attacked"] == "1":
            per[b][2] += 1
    out["pmus"] = [{"bus": int(b), "delivery": round(v[0] / v[1], 3), "attacked_frames": v[2]}
                   for b, v in sorted(per.items(), key=lambda x: int(x[0]))]
    # GridPACK per grid step: whole solve as seen by the grid federate, and the MPI solve alone
    out["gridpack"] = [[float(r["t"]), float(r["solve_ms"]) if r.get("solve_ms") else None,
                        float(r["gridpack_solve_ms"]) if r.get("gridpack_solve_ms") else None, r.get("solver")]
                       for r in read_csv(os.path.join(d, "grid_steps.csv"))]
    # dynamic simulation: system frequency and rotor angle spread per grid step
    dyn_path = os.path.join(d, "grid_dynamics.csv")
    if os.path.exists(dyn_path):
        dyn = read_csv(dyn_path)
        idx = thin(len(dyn))
        out["freq"] = [[float(dyn[i]["t"]), float(dyn[i]["f_coi_hz"]), float(dyn[i]["f_min_hz"]),
                        float(dyn[i]["f_max_hz"])] for i in idx]
        out["angle_spread"] = [[float(dyn[i]["t"]), float(dyn[i]["angle_spread_deg"])] for i in idx]
    return out
