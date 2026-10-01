# CPS Testbed Cluster: Synchrophasor Co-Simulation on MPI

A remotely accessible cyber-physical system testbed for synchrophasor (PMU) monitoring and
control of a power grid, built for the NSU–PGCB project *Remotely Accessible Cyber-Physical
System Testbed and Open Architecture Synchrophasor Systems* (EPRC/58-2018-007-01).

The power grid (**GridPACK**, running in parallel with **MPI**), the communication network
(**NS-3**) and the control center are co-simulated under **HELICS**. They can run on one
server or spread over a cluster. Users work in a **Node-RED** dashboard: they upload grid
models and scenario files, follow running experiments live and study the results.

```
 GridPACK (MPI ranks) ──true phasors──▶ NS-3: PMUs ─▶ links ─▶ PDC ──aligned sets──▶ control center
        ▲                                                                              │
        └──── setpoint applied ◀──── NS-3: generator node ◀──── command ───────────────┘

 observer (HELICS) ──▶ live view          experiment API (8080) ◀──▶ Node-RED dashboard (1880)
```

| Part | Role | Code |
|---|---|---|
| **Grid** | GridPACK power flow every grid step as a persistent MPI job (`pf_server`) partitioned over N ranks; load variation, events, control commands; publishes the true phasors each PMU measures | `gridpack/pf_server/`, `federates/grid_fed.py` |
| **Network** | NS-3: PMUs at the optimal buses send 30–60 frames/s over their own links (latency, jitter, loss) to a PDC with a wait window; attacks; commands travel back to the generators | `ns3-scratch/helicstest/` |
| **Control center** | PMU state estimation, chi-square bad data detection with removal of suspicious PMUs, voltage limit checks, generator setpoint control | `federates/cc_fed.py` |
| **Observer** | Listens to the federation without slowing it and feeds the live view | `federates/observer_fed.py` |
| **Orchestration** | Places the HELICS broker and federates on nodes, one port per experiment, MPI slot-aware queue | `federates/run_experiment.py`, `federates/cpslib/cluster.py`, `webapp/app.py` |
| **Dashboard** | Node-RED pages *Experiments*, *Live*, *Results*, and the original IEEE 14 console | `node-red/flows.json` |

## Install

The testbed builds GridPACK 3.5, HELICS 3.6.1 and NS-3.48 from source (about an hour the
first time) and installs them under `/opt/cps`. There are two ways, built by the same scripts
(`install/steps/`):

### A. Directly on Ubuntu 24.04 (no containers)

```bash
git clone https://github.com/mazharulmd/cps-testbed-cluster.git
cd cps-testbed-cluster
sudo ./install/install.sh
```

This installs the software, creates the service user `cps`, writes the settings to
`/etc/cps/cps.env` and starts two systemd services, `cps-api` (port 8080) and `cps-nodered`
(port 1880). Open `http://<server>:1880/dashboard/experiments`.

For a cluster, run `sudo ./install/install.sh --role node` on each compute node, share
`/srv/cps` over NFS and list the nodes in `/etc/cps/cps.env` on the head. Details, logins and
service management: [documentation/install.md](documentation/install.md).

### B. Docker

```bash
docker build -f docker/Dockerfile -t cps-testbed-cluster .
docker compose -f docker/compose.yml up -d            # one container, single server
docker compose -f docker/compose.cluster.yml up -d    # head + 2 compute nodes on one machine
```

Instead of building, a published image can be used once the *Container image* workflow has run
(Actions → Container image → Run workflow, or push a `v*` tag):

```bash
docker pull ghcr.io/mazharulmd/cps-testbed-cluster:latest
CPS_IMAGE=ghcr.io/mazharulmd/cps-testbed-cluster:latest docker compose -f docker/compose.yml up -d
```

The same image runs every role on real machines too: [documentation/cluster.md](documentation/cluster.md).

Requirements: x86-64 machine, 4+ cores, 8 GB RAM, 15 GB disk, internet access during the build.

## Use

1. **Experiments page.** Optionally upload a grid model (MATPOWER `.m`; the power flow is
   checked and the PMU placement computed). Download the scenario template, edit it and upload
   it. Each experiment is validated and queued; one file can hold several.
2. **Live page.** Follow the running experiment second by second: true and estimated voltages
   at any bus, bad data alarms, PDC completeness, and every command from issue to delivery to
   application.
3. **Results page.** Summary figures, charts (voltages, chi-square test, GridPACK solve time per
   step, latency, PDC completeness, per-PMU delivery) and the command log of each run. Raw files
   are in `/srv/cps/runs/<run id>/`.

A scenario file:

```yaml
name: gen-fault-fdi
grid: ieee118            # ieee14 ... ieee300 or the id of an uploaded grid
duration: 10
mpi_np: 4                # GridPACK MPI ranks
network: {latency_ms: 20, loss: 0.02}
event:   {type: avr_fault, bus: 49, vset: 1.12, t: 4}
attack:  {type: fdi-stealthy, target: 49, start: 4, end: 9}
control: {bdd: true, voltage_control: true}
```

All fields: [`webapp/scenario_template.yaml`](webapp/scenario_template.yaml). The same is
possible from scripts (`curl -F file=@scenario.yaml http://<server>:8080/api/scenarios/file`,
API documentation at `/docs`) and from the command line (`sudo -u cps cps-run --case 118
--duration 10 --mpi-np 4 ...`, `--help` lists all options).

## Features

- **Grids:** IEEE 14, 30, 39, 57, 118 and 300 built in; any MATPOWER case uploaded (tested up
  to the 10 000-bus ACTIVSg10k). Sparse network model, state estimation and PMU placement.
- **GridPACK on MPI:** one MPI job per experiment, the network read and partitioned once;
  agrees with the testbed's Newton-Raphson solver to 5×10⁻¹⁰ pu (IEEE 118, ACTIVSg2000).
- **Optimal PMU placement** (integer linear program): minimum for full observability, or
  redundant (every bus seen by two PMUs).
- **Network:** per-link latency with spread, jitter, packet loss, PDC wait window, reporting rate.
- **Attacks:** false data injection (simple, or stealthy across all channels of the target
  bus), packet delay and drop.
- **Defenses:** chi-square bad data detection with largest-normalized-residual PMU removal;
  control held while bad data cannot be cleaned; redundant placement.
- **Grid events:** generator AVR setpoint fault, load step.
- **Cluster:** federates on any node, MPI ranks over a hostfile, parallel experiments on their
  own HELICS ports, queue that waits for free MPI slots.

## Example results (IEEE 118-bus, 10 s, AVR fault at generator 49 → 1.12 pu at t = 4 s)

| Scenario | Violation time | What happened |
|---|---|---|
| No control | 6.5 s | Violation persists to the end |
| Control on | 0.5 s | Control center lowers generator 49 setpoint within one grid step |
| 5% packet loss | 0.5 s | Only 18% of PDC sets complete, but estimation stays usable |
| Simple FDI on bus 49 | 0.5 s | Detected in one frame (0.033 s); falsified PMU removed; control still acts |
| Stealthy FDI on bus 49 | 0.5 s | Not detected (2 PMUs compromised), but neighbour bus 48 still reveals the over-voltage |
| Delay attack (100 ms) on PMUs 45, 49 | 5.5 s | Frames miss the PDC window; bus 49 unobserved; violation missed |

With minimum placement some buses are observed through a single *critical measurement*;
falsifying it is invisible to bad data detection (e.g. IEEE 14 bus 8). Redundant placement
removes that blind spot. Measured cluster results and MPI timings: [documentation/cluster.md](documentation/cluster.md).

## Repository layout

```
cases/           IEEE 14–300 bus inputs, topology and reference solutions
federates/       grid_fed.py, cc_fed.py, observer_fed.py, run_experiment.py
  cpslib/        network model, PMU placement, state estimation, attacks, GridPACK client,
                 uploaded grids, cluster placement
gridpack/        pf_server: persistent MPI GridPACK power-flow server
ns3-scratch/     NS-3 network federate (multi-PMU mode and the legacy single-PMU mode)
webapp/          experiment API (FastAPI): queue, uploads, results, live state; scenario template
node-red/        dashboard flows and settings
legacy/          original single-PMU IEEE 14 demo used by the Node-RED console
tools/           make_cases.py (MATPOWER → testbed cases)
install/         native installer, build steps shared with Docker, systemd units, settings
docker/          Dockerfile, entrypoint, compose files (single server, virtual cluster)
documentation/   install and cluster guides, user guide and technical report (PDF)
```

## Documentation

- [documentation/install.md](documentation/install.md): installation on Ubuntu 24.04, settings, logins, services, cluster set-up
- [documentation/cluster.md](documentation/cluster.md): architecture of the cluster, what runs where, tested results and MPI timings
- [CPS_Testbed_User_Guide.pdf](documentation/CPS_Testbed_User_Guide.pdf) and [CPS_Testbed_Technical_Report.pdf](documentation/CPS_Testbed_Technical_Report.pdf): the user guide and technical report of the preceding single-server version (web app, IEEE 14 console, validation and results); the simulation models described there are the ones used here

## Limitations

- The grid is quasi-steady-state (a power flow every grid step), not a dynamic simulation.
- PMU frames are JSON over the simulated network, not IEEE C37.118; no real PMU devices yet.
- PSS/E `.raw` files are not read directly; convert them with MATPOWER's `psse2mpc`.
- Tested on a virtual cluster (containers on one machine); not yet on separate machines.

## Team

Principal Investigator: Dr. Hafiz Abdur Rahman (North South University). Co-PIs: Dr. Jahangir
Hossain (University of British Columbia), Dr. Athula Kulatunga (Purdue University Northwest).
Research team: Dr. Shohana Rahman Deeba, Ms. Rummana Rahman (North South University).
Development: Md. Mazharul Islam. Funded by the Bangladesh Energy and Power Research Council
(EPRC), grant EPRC/58-2018-007-01.

## Licensing

The testbed builds and links third-party software under its own licenses: NS-3 (GPLv2),
HELICS (BSD-3-Clause), GridPACK (BSD-style), Global Arrays (BSD-style), PETSc (BSD-2-Clause),
OpenMPI (BSD-style) and Node-RED (Apache-2.0).
