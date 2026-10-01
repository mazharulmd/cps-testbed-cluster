"""Cluster layout: which node runs the HELICS broker and each federate, and where
GridPACK's MPI ranks go.

The layout comes from the JSON file named by CPS_CLUSTER_CONFIG (on the virtual cluster
$CPS_SHARED/cluster.json, written by install/configure.py). Without it everything runs on
this machine, as on a single-server installation:

{
  "head": "head",
  "nodes": [{"host": "node1", "slots": 4}, {"host": "node2", "slots": 4}],
  "placement": {"broker": "head", "grid": "head", "ns3": "node1", "cc": "node2"},
  "mpi": {"hostfile": "/srv/cps/hostfile", "default_np": 4},
  "helics_port_base": 23500,
  "max_parallel_jobs": 2
}

Remote processes are started over ssh. All nodes share the data directory (/srv/cps), so
logs and results are written straight into it.
"""
import json, os, shlex, shutil, socket, subprocess

LOCAL = {"localhost", "127.0.0.1", "", None}


def load():
    path = os.environ.get("CPS_CLUSTER_CONFIG", "")
    if path and os.path.exists(path):
        with open(path) as fh:
            cfg = json.load(fh)
    else:
        cfg = {}
    cfg.setdefault("head", "localhost")
    cfg.setdefault("nodes", [])
    cfg.setdefault("placement", {})
    cfg.setdefault("mpi", {})
    cfg.setdefault("helics_port_base", 23500)
    cfg.setdefault("max_parallel_jobs", 1)
    return cfg


def is_local(host):
    return host in LOCAL or host in (socket.gethostname(), socket.getfqdn())


def mpi_slots(cfg):
    """Total MPI slots in the hostfile (or the local core count)."""
    if cfg["nodes"]:
        return sum(int(n.get("slots", 1)) for n in cfg["nodes"])
    return os.cpu_count() or 1


def core_init(cfg, host, port):
    """HELICS core init string for a federate on `host` talking to this run's broker."""
    broker = cfg["placement"].get("broker", cfg["head"])
    if is_local(broker) and is_local(host):
        return f"--federates=1 --broker_address=tcp://127.0.0.1:{port}"
    return f"--federates=1 --broker_address=tcp://{broker}:{port} --local_interface=tcp://{host}"


HELICS_BROKER = os.environ.get("CPS_HELICS_BROKER") or shutil.which("helics_broker") or "/opt/cps/helics/bin/helics_broker"


def broker_args(port, federates=4):
    return [HELICS_BROKER, "-f", str(federates), "--loglevel=warning", f"--port={port}",
            "--local_interface=tcp://0.0.0.0"]


def launch(host, argv, log, cwd):
    """Start argv on host (directly if it is this machine, else over ssh)."""
    if is_local(host):
        return subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, cwd=cwd)
    remote = f"cd {shlex.quote(cwd)} && exec " + " ".join(shlex.quote(a) for a in argv)
    return subprocess.Popen(["ssh", "-o", "BatchMode=yes", host, remote], stdout=log,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)


def kill_remote(host, pattern):
    """Stop leftover processes of a run on a remote node (killing ssh does not)."""
    if not is_local(host):
        subprocess.run(["ssh", "-o", "BatchMode=yes", host, "pkill", "-f", pattern],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def status(cfg):
    """Reachability and core count of every node (for the dashboard)."""
    out = []
    hosts = [cfg["head"]] + [n["host"] for n in cfg["nodes"] if n["host"] != cfg["head"]]
    slots = {n["host"]: n.get("slots") for n in cfg["nodes"]}
    for host in hosts:
        roles = [r for r, h in cfg["placement"].items() if h == host]
        if slots.get(host):
            roles.append("mpi")
        try:
            if is_local(host):
                cores, up = os.cpu_count(), True
            else:
                p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", host, "nproc"],
                                   capture_output=True, text=True, timeout=8)
                up = p.returncode == 0
                cores = int(p.stdout.strip()) if up else None
        except Exception:
            up, cores = False, None
        out.append({"host": host, "up": up, "cores": cores, "mpi_slots": slots.get(host), "roles": roles})
    return out
