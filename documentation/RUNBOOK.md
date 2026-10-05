# CPS Testbed runbook

Step by step: install the testbed, run the first experiment, read the results, and fix the
usual problems. The complete guide is [CPS_Testbed_Cluster_Description_Installation_User_Guide](CPS_Testbed_Cluster_Description_Installation_User_Guide.pdf);
installation details are in [install.md](install.md) and the cluster in [cluster.md](cluster.md).

## 1. Install (one Ubuntu 24.04 server)

Requirements: x86-64, 4+ cores, 8 GB RAM, 15 GB disk, internet access during the build.

```bash
git clone https://github.com/mazharulmd/cps-testbed-cluster.git
cd cps-testbed-cluster
sudo ./install/install.sh        # builds GridPACK, HELICS, NS-3 from source (about an hour the first time)
sudo cps-passwd                  # login for the dashboard, the Node-RED editor and the API (user admin)
```

Before installing, make sure nothing else uses ports **1880** and **8080**
(`sudo ss -ltnp | grep -E ':1880|:8080'`); stop old containers that hold them. The installer
warns when it finds one.

What you get:

| Where | What |
|---|---|
| `/opt/cps` | the software (GridPACK, HELICS, NS-3, Node-RED, Python venv, testbed code) |
| `/srv/cps` | the data: `runs/`, uploaded `grids/`, cluster files |
| `/etc/cps/cps.env` | the settings |
| `cps-api.service` | FastAPI backend, port 8080 |
| `cps-nodered.service` | Node-RED dashboard, port 1880 |

Update later with `git pull && sudo ./install/install.sh` (keeps the data and settings).

Docker instead: `docker build -f docker/Dockerfile -t cps-testbed-cluster .` then
`docker compose -f docker/compose.yml up -d`.

## 2. Open the dashboard

`http://<server>:1880/dashboard/experiments`, log in as `admin`. The pages:

| Page | Use it to |
|---|---|
| Experiments | start an experiment from the form or a preset, upload scenario files and grids, watch the queue |
| Live | follow the running experiment every second |
| Inside | see what HELICS, GridPACK, NS-3 and the control center compute |
| Results | open finished runs: summary, voltage at every bus at any moment, charts, commands |
| Cluster | set compute nodes, MPI slots and where each federate runs |
| Console | the original IEEE 14 prototype |

The Node-RED editor (the flows behind the pages) is at `http://<server>:1880/`, the API
documentation at `http://<server>:8080/docs`.

## 3. Run the first experiment

**From the form:** Experiments → New experiment → pick a preset (for example *Attack detected
(IEEE 118)*) → **Run experiment**.

**From a scenario file:** Experiments → Upload files → **Upload scenario** →
[`scenarios/demo-ieee14.yaml`](../scenarios/demo-ieee14.yaml). It queues three 10-second IEEE 14
runs (about a minute in all):

| Run | Shows | Expected result |
|---|---|---|
| `d14-avr-fault` | closed loop | AVR of generator 6 fails at 3 s; command issued 3.067 s, delivered 3.109 s, applied 3.5 s |
| `d14-fdi-minimum` | hidden attack, 4 PMUs | FDI on bus 8 not detected (J 1.2 < 13.3); bus 8 is 1.080 pu, the control center sees 1.040 |
| `d14-fdi-redundant` | the fix, 9 PMUs | detected at once (J 183 > 76); PMU 8 removed; bus 8 seen at 1.080 |

Write your own file from the template linked in the Upload panel (`/cps/scenario-template.yaml`);
one file holds up to 50 experiments under `scenarios:`.

**From the command line:**

```bash
sudo -u cps cps-run --case 14 --duration 10 --attack fdi-simple --target 8 --attack-start 3 --attack-end 8
sudo -u cps cps-run --help                       # every option
curl -u admin:PASSWORD -F file=@scenarios/demo-ieee14.yaml http://<server>:8080/api/scenarios/file
```

## 4. Read the results

While it runs: **Live** (voltages, alarms, commands) and **Inside** (each engine at work).
Afterwards: **Results** → click the run. The panel *Voltage at every bus* compares the true
voltage (blue), the PMU values received (orange squares, purple = removed as bad data) and the
control center's estimate (red); move through the run with the slider or the event / attack /
end buttons.

Every run is a folder `/srv/cps/runs/<date>_<time>_<name>/`:

| File | Contents |
|---|---|
| `summary.json` | headline figures: violation time, detection, delivery, timings |
| `grid_truth.csv`, `grid_steps.csv` | true voltage of every bus each step; solver, iterations, times, MPI ranks |
| `grid_dynamics.csv` | dynamic mode: frequencies, rotor angles, generator power |
| `frames.csv`, `ns3_summary.json` | every PMU frame: sent, arrived, latency, status; network summary |
| `cc_log.csv`, `cc_estimates.csv`, `cc_received.csv` | every PMU set: chi-square test, removed PMUs; estimated and received voltages |
| `commands_applied.csv` | commands and grid events with their times |
| `meta.json`, `*_config.json`, `*.log` | settings of the run and each federate's log |

A figure of the voltage at every bus for a report:

```bash
sudo -u cps /opt/cps/venv/bin/python /opt/cps/testbed/tools/plot_profile.py /srv/cps/runs/<run id> --t 4 --out fig.png
```

## 5. Add cluster nodes

1. On each node: `sudo ./install/install.sh --role node` (same user `cps`, same UID).
2. Share `/srv/cps` from the head over NFS and mount it at `/srv/cps` on every node
   ([install.md](install.md)).
3. On the head: **Cluster** page → add each node with its MPI slots (cores for GridPACK) →
   choose where NS-3 and the control center run → **Save**. The head sets up SSH to the nodes.
4. Run an experiment with *MPI ranks* > 1. A node that does not answer is left out of that
   run's hostfile.

## 6. When something goes wrong

| Symptom | What to do |
|---|---|
| Login fails | `sudo cps-passwd`; check ports 1880/8080 are not taken by something else |
| Page does not load | `systemctl status cps-api cps-nodered`; `journalctl -u cps-api -n 50` |
| Experiment failed | the queue shows the last log lines; the failing federate's `<name>.log` in the run folder says why |
| Stays "waiting for N MPI slots" | another run holds the cores, or N is larger than the slots: Cluster page |
| Upload rejected | the red message names the field (for example a bus not in the grid) |
| Grid is PSS/E `.raw` | convert in MATPOWER: `mpc = psse2mpc('grid.raw'); savecase('grid.m', mpc)`, upload the `.m` |
