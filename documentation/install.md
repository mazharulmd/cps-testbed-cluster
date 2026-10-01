# Installing the testbed on Ubuntu 24.04

This guide installs the testbed directly on Ubuntu 24.04 servers, without containers. The
Docker image (`docker/Dockerfile`) runs the same build scripts, so both installations contain
the same software in the same places.

| Where | What |
|---|---|
| `/opt/cps/` | Global Arrays, GridPACK (+ `pf_server`, `dsf_server`), HELICS, NS-3 (+ the network federate), Python environment `venv`, Node-RED user directory `node-red`, the testbed code `testbed` |
| `/srv/cps/` | data: `runs/` (one directory per experiment), `grids/` (uploaded grids), `legacy/`, `cluster.json`, `hostfile` |
| `/etc/cps/cps.env` | settings read by the services |
| `cps-api`, `cps-nodered` | systemd services on the head (single server): experiment API on port 8080, Node-RED on 1880 |
| `cps-node` | systemd service on a compute node |
| `cps` | the system user the services run as |

## Requirements

- Ubuntu 24.04 (server or desktop), x86-64.
- 4 or more cores, 8 GB RAM, 15 GB free disk.
- Internet access during the installation (packages, and the GridPACK, HELICS and NS-3 sources).

## Single server

```bash
git clone https://github.com/mazharulmd/cps-testbed-cluster.git
cd cps-testbed-cluster
sudo ./install/install.sh
```

The first run takes about an hour, mostly compiling GridPACK, HELICS and NS-3 (`--jobs N`
limits the parallel compile jobs). At the end the script prints the addresses:

- Dashboard: `http://<server>:1880/dashboard/experiments`
- Node-RED editor: `http://<server>:1880`
- Experiment API and its documentation: `http://<server>:8080/docs`

Everything runs on this server; GridPACK uses up to as many MPI ranks as the server has cores
(`mpi_np` in a scenario file, default `CPS_MPI_NP`).

### Logins

Without passwords anyone who can reach ports 1880 and 8080 can run experiments. Set them in
`/etc/cps/cps.env`:

```bash
# experiment API (user CPS_WEB_USER, default admin)
sudo sed -i 's/^CPS_WEB_PASSWORD=.*/CPS_WEB_PASSWORD=choose-a-password/' /etc/cps/cps.env

# Node-RED: a bcrypt hash of the password
HASH=$(node -e 'console.log(require("/usr/local/lib/node_modules/node-red/node_modules/bcryptjs").hashSync(process.argv[1], 8))' 'choose-a-password')
sudo sed -i "s|^NODERED_ADMIN_HASH=.*|NODERED_ADMIN_HASH=$HASH|" /etc/cps/cps.env

sudo systemctl restart cps-api cps-nodered
```

The dashboard talks to the API with `CPS_WEB_PASSWORD`, so both keep working together.

### Remote access

Keep the ports closed to the internet and reach the server through the institution's VPN or an
SSH tunnel, for example from Windows with MobaXterm (*Tunneling → New SSH tunnel → Local port
forwarding*, local 1880 → `localhost:1880` on the server) or from any terminal:

```bash
ssh -L 1880:localhost:1880 -L 8080:localhost:8080 user@server
# then open http://localhost:1880/dashboard/experiments
```

### Services

```bash
systemctl status cps-api cps-nodered          # state
journalctl -u cps-api -f                      # API and experiment queue log
journalctl -u cps-nodered -f                  # Node-RED log
sudo systemctl restart cps-api cps-nodered    # after changing /etc/cps/cps.env
```

Experiments started from the dashboard, the API or `cps-run` write to
`/srv/cps/runs/<date>_<time>_<name>/` (summary, configurations, federate logs, CSV files).

### Command line

```bash
sudo -u cps cps-run --case 118 --duration 10 --mpi-np 4 \
    --event avr:49:1.12:4 --attack fdi-simple --target 49 --fake 1.02 --attack-start 4 --attack-end 9
sudo -u cps cps-run --help
```

### Updating

```bash
cd cps-testbed-cluster && git pull
sudo ./install/install.sh
```

The libraries that are already built are kept (GridPACK is rebuilt only when its patches in
`gridpack/patches` changed, which takes most of an hour); the testbed code, the NS-3 federate,
`pf_server` and `dsf_server` are rebuilt, and the services restart. A Node-RED `flows.json`
that was changed in the editor is saved as `flows.json.bak-<date>` before the new one is
installed.

## Cluster

A cluster has one **head** (dashboard, API, HELICS brokers, usually the grid federate) and
one or more **compute nodes** (GridPACK MPI ranks, and the NS-3 or control-center federates
if you place them there).

1. **Install every machine.** On the head `sudo ./install/install.sh`, on each compute node
   `sudo ./install/install.sh --role node`. All machines need the same user `cps` (the
   installer creates it; give it the same UID on every machine if the shared directory is NFS
   without ID mapping).
2. **Share `/srv/cps`.** Export it from the head (or a file server) over NFS and mount it at
   `/srv/cps` on every node, writable for `cps`. For example on the head:
   `sudo apt install nfs-kernel-server`, add `/srv/cps 10.0.0.0/24(rw,sync,no_subtree_check)`
   to `/etc/exports`, `sudo exportfs -ra`; on each node `sudo apt install nfs-common` and add
   `head:/srv/cps /srv/cps nfs defaults 0 0` to `/etc/fstab`.
3. **Names and network.** Every machine must resolve the others' host names (DNS or
   `/etc/hosts`) and reach them on TCP: ssh (22), the HELICS ports (23500 and up) and MPI
   (dynamic ports). If a machine has several network interfaces, set
   `OMPI_MCA_btl_tcp_if_include` and `OMPI_MCA_oob_tcp_if_include` in `/etc/cps/cps.env` to
   the cluster interface.
4. **Describe the cluster on the head** in `/etc/cps/cps.env`:

   ```bash
   CPS_NODES=node1:16,node2:16     # MPI hosts and slots (cores for GridPACK)
   CPS_PLACE_NS3=node1             # NS-3 network federate
   CPS_PLACE_CC=node2              # control-center federate
   CPS_MPI_NP=16                   # default ranks per experiment
   CPS_MAX_JOBS=2                  # experiments at the same time
   ```

   then `sudo systemctl restart cps-api`. At start-up the head creates the cluster's SSH key in
   `/srv/cps/.ssh`, the `cps-node` service on each node installs it, and the head checks that
   every node answers over ssh (`journalctl -u cps-api` shows "node1 reachable").
5. **Check** on the dashboard's *Experiments* page: every node is listed with its cores, MPI
   slots and roles.

An experiment starts only when its MPI ranks fit in the free slots; others wait in the queue.

## Uninstall

```bash
sudo systemctl disable --now cps-api cps-nodered cps-node 2>/dev/null
sudo rm -f /etc/systemd/system/cps-*.service /usr/local/bin/cps-run /etc/ld.so.conf.d/cps-testbed.conf
sudo ldconfig && sudo systemctl daemon-reload
sudo rm -rf /opt/cps /etc/cps          # software and settings
sudo rm -rf /srv/cps                   # results and uploaded grids (keep if you need them)
sudo userdel -r cps
```

## Troubleshooting

| Problem | What to do |
|---|---|
| The dashboard says "Experiment API not reachable" | `systemctl status cps-api`; `journalctl -u cps-api` |
| A job fails | The log under the job on the *Experiments* page; the federate logs (`grid.log`, `ns3.log`, `cc.log`, `broker.log`, `gridpack/pf_server.log`) in the run directory |
| A node is shown as not reachable | `sudo -u cps ssh node1 true` on the head; check that `/srv/cps` is mounted on the node and `systemctl status cps-node` there |
| MPI hangs between nodes | Set `OMPI_MCA_btl_tcp_if_include` / `OMPI_MCA_oob_tcp_if_include` to the interface that connects the nodes; open the firewall between them |
| A grid upload is rejected | The message names the problem (missing `mpc.gen`, no slack bus, power flow does not converge) |
