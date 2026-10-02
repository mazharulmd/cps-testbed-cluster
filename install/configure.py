#!/usr/bin/env python3
"""Write the cluster layout and set up SSH between the nodes.

Run at start-up on every node: by the systemd services of a native installation
(install/systemd) and by docker/entrypoint.sh in the container. It reads the variables of
/etc/cps/cps.env (or the container's environment):

  CPS_ROLE        head | node                                     [head]
  CPS_HEAD        host name of the head                           [this host]
  CPS_NODES       MPI hosts and slots, "node1:16,node2:16"        [none: single server]
  CPS_PLACE_GRID, CPS_PLACE_NS3, CPS_PLACE_CC   where the federates run   [head]
  CPS_MPI_NP      default GridPACK MPI ranks                      [1]
  CPS_MAX_JOBS    experiments that may run at the same time       [1]
  CPS_SHARED      shared data directory (NFS on a real cluster)   [/srv/cps]

Settings changed on the dashboard (Experiments page, Cluster settings) are kept in
$CPS_SHARED/cluster_settings.json and take precedence over these variables.

head: writes $CPS_SHARED/cluster.json and $CPS_SHARED/hostfile and, on a cluster, creates the
      cluster's SSH key in $CPS_SHARED/.ssh.
node: waits for that key.
Both install the key for the current user, so MPI and the federates can be started over ssh.
"""
import json, os, socket, subprocess, sys, time

env = os.environ.get
SHARED = env("CPS_SHARED", "/srv/cps")
ROLE = env("CPS_ROLE", "head")
HEAD = env("CPS_HEAD") or socket.gethostname()
SETTINGS = os.path.join(SHARED, "cluster_settings.json")


def settings():
    """The cluster settings: environment variables, overridden by the dashboard's file.

    {"nodes": [{"host", "slots"}], "place_grid", "place_ns3", "place_cc", "default_np",
     "max_parallel_jobs"}; empty placements mean the head."""
    nodes = []
    for item in filter(None, (env("CPS_NODES") or "").replace(" ", "").split(",")):
        host, _, slots = item.partition(":")
        nodes.append({"host": host, "slots": int(slots or 1)})
    s = {"nodes": nodes, "place_grid": env("CPS_PLACE_GRID") or "", "place_ns3": env("CPS_PLACE_NS3") or "",
         "place_cc": env("CPS_PLACE_CC") or "", "default_np": int(env("CPS_MPI_NP") or 1),
         "max_parallel_jobs": int(env("CPS_MAX_JOBS") or 1), "source": "settings file"}
    if os.path.exists(SETTINGS):
        try:
            s.update({k: v for k, v in json.load(open(SETTINGS)).items() if k in s})
            s["source"] = "dashboard"
        except (OSError, ValueError):
            print(f"[configure] ignoring unreadable {SETTINGS}", flush=True)
    return s


def layout(s=None):
    s = s or settings()
    nodes = s["nodes"]
    return {
        "head": HEAD,
        "nodes": nodes,
        "placement": {"broker": HEAD,
                      "grid": s["place_grid"] or HEAD,
                      "ns3": s["place_ns3"] or HEAD,
                      "cc": s["place_cc"] or HEAD},
        "mpi": {"hostfile": os.path.join(SHARED, "hostfile") if nodes else None,
                "default_np": int(s["default_np"])},
        "helics_port_base": 23500,
        "max_parallel_jobs": int(s["max_parallel_jobs"]),
    }


def remote_hosts(cfg):
    return sorted(({n["host"] for n in cfg["nodes"]} | set(cfg["placement"].values())) - {cfg["head"]})


def install_key(wait):
    key = os.path.join(SHARED, ".ssh", "id_ed25519")
    if wait:
        print(f"[configure] waiting for {key} from the head ...", flush=True)
        while not os.path.exists(key + ".pub"):
            time.sleep(2)
    elif not os.path.exists(key):
        os.makedirs(os.path.dirname(key), exist_ok=True)
        os.chmod(os.path.dirname(key), 0o700)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "cps-cluster", "-f", key], check=True)
    home = os.path.expanduser("~/.ssh")
    os.makedirs(home, exist_ok=True)
    os.chmod(home, 0o700)
    for src, dst, mode in ((key, "id_ed25519", 0o600), (key + ".pub", "id_ed25519.pub", 0o644)):
        with open(src, "rb") as fh, open(os.path.join(home, dst), "wb") as out:
            out.write(fh.read())
        os.chmod(os.path.join(home, dst), mode)
    pub = open(key + ".pub").read().strip()
    auth = os.path.join(home, "authorized_keys")
    lines = open(auth).read().splitlines() if os.path.exists(auth) else []
    if pub not in lines:
        with open(auth, "a") as fh:
            fh.write(pub + "\n")
    os.chmod(auth, 0o600)
    cfg = os.path.join(home, "config")
    if not os.path.exists(cfg):
        with open(cfg, "w") as fh:
            fh.write("Host *\n  StrictHostKeyChecking accept-new\n  LogLevel ERROR\n")
        os.chmod(cfg, 0o600)


def main():
    for d in ("runs", "grids", "legacy"):
        os.makedirs(os.path.join(SHARED, d), exist_ok=True)
    if ROLE == "node":
        install_key(wait=True)
        print(f"[configure] {socket.gethostname()} ready as a compute node", flush=True)
        return
    apply(wait=int(env("CPS_WAIT_NODES") or 60))


def apply(s=None, wait=0):
    """Write cluster.json and the MPI hostfile, set up the cluster's SSH key when there are
    other hosts, and check that they answer (waiting up to `wait` seconds for each).
    Returns the layout and {host: reachable}."""
    cfg = layout(s)
    for name, text in (("hostfile", "".join(f"{n['host']} slots={n['slots']}\n" for n in cfg["nodes"])),
                       ("cluster.json", json.dumps(cfg, indent=1))):
        tmp = os.path.join(SHARED, f".{name}.tmp")
        with open(tmp, "w") as fh:
            fh.write(text)
        os.replace(tmp, os.path.join(SHARED, name))
    print("[configure] cluster:", json.dumps(cfg), flush=True)
    hosts = remote_hosts(cfg)
    if not hosts:
        print("[configure] single server: everything runs on this host", flush=True)
        return cfg, {}
    install_key(wait=False)
    reach = {}
    for host in hosts:
        ok = False
        for _ in range(max(1, wait)):
            ok = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2", host, "true"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if ok or wait <= 1:
                break
            time.sleep(1)
        reach[host] = ok
        print(f"[configure] {host} {'reachable' if ok else 'NOT reachable over ssh'}", flush=True)
    return cfg, reach


if __name__ == "__main__":
    sys.exit(main())
