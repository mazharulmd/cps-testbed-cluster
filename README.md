# CPS Testbed Cluster: Synchrophasor Co-Simulation on MPI

A remotely accessible cyber-physical system testbed for synchrophasor (PMU) monitoring and
control of a power grid, built for the NSU–PGCB project *Remotely Accessible Cyber-Physical
System Testbed and Open Architecture Synchrophasor Systems* (EPRC/58-2018-007-01).

The power grid (**GridPACK**, running in parallel with **MPI**, as a power flow or as a full
dynamic simulation of the generators), the communication network (**NS-3**) and the control
center are co-simulated under **HELICS**. They can run on one
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
| **Grid** | GridPACK as a persistent MPI job partitioned over N ranks: a power flow every grid step (`pf_server`, quasi-steady state) or a dynamic simulation of generators, exciters and governors advanced every PMU frame (`dsf_server`); events, control commands; publishes the true phasors each PMU measures | `gridpack/`, `federates/grid_fed.py` |
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
(port 1880). Set a login with `sudo cps-passwd` (user `admin`) and open
`http://<server>:1880/dashboard/experiments`.

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

1. **Experiments page.** In *New experiment*, pick a ready-made scenario (attack detected,
   stealthy attack, delay attack, packet loss, fault, generator trip, AVR fault with control)
   or set the grid, simulation mode, event, attack, network, duration and MPI ranks in the
   form, and press *Run experiment*. The form offers only the buses, generators and lines of
   the chosen grid, and can save the experiment as a scenario file. For many experiments at
   once, upload scenario files instead; grid models (MATPOWER `.m`) are uploaded here too.
2. **Live page.** Follow the running experiment second by second: the voltage of every bus as
   GridPACK computed it, as the PMUs delivered it and as the control center estimated it; true and
   estimated voltage over time at any bus; bad data alarms, PDC completeness, and every command
   from issue to delivery to application.
3. **Inside page.** What the three engines compute while the experiment runs: the HELICS
   federation (which federate runs on which node, the simulated time the broker granted each
   one, messages and bytes per topic); GridPACK (solver, MPI ranks and how the grid is split
   over them, the Newton-Raphson mismatch of every iteration or the integration steps of the
   dynamic simulation, time per step); NS-3 (frames sent, delivered, late, lost and attacked per
   PMU, latency, PDC sets, commands, simulator events); the control center (measurements,
   observability, chi-square test, removed PMUs, estimation time); and a log in plain words of
   every event, alarm and command.
4. **Results page.** Summary figures; the voltage of every bus at any moment of the run (true,
   received from the PMUs, estimated; step through the run with a slider); charts (voltages,
   chi-square test, GridPACK solve time per step, latency, PDC completeness, per-PMU delivery) and
   the command log of each run. Raw files are in `/srv/cps/runs/<run id>/`; the same voltage chart
   as a PNG for reports: `sudo -u cps /opt/cps/venv/bin/python /opt/cps/testbed/tools/plot_profile.py
   /srv/cps/runs/<run id> --t 9`.
5. **Cluster page.** The nodes and their state, and the cluster settings: default MPI ranks,
   experiments at the same time, compute nodes with their MPI slots, and the node of each
   federate. Saved settings apply to the next experiments, without a restart.

A scenario file:

```yaml
name: gen-fault-fdi
mode: qss                # qss (power flow every grid step) or dynamic
grid: ieee118            # ieee14 ... ieee300 or the id of an uploaded grid
duration: 10
mpi_np: 4                # GridPACK MPI ranks
network: {latency_ms: 20, loss: 0.02}
event:   {type: avr_fault, bus: 49, vset: 1.12, t: 4}
attack:  {type: fdi-stealthy, target: 49, start: 4, end: 9}
control: {bdd: true, voltage_control: true}
```

A dynamic simulation, with the published machine data of the IEEE 39-bus system:

```yaml
name: fault-39
grid: ieee39
mode: dynamic            # GridPACK integrates the machines every 4.8 ms, PMUs report every 1/30 s
event: {type: bus_fault, bus: 16, duration: 0.1, t: 3}     # or line_trip, gen_trip, avr_fault
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
- **Two grid modes:** quasi-steady state (a power flow every grid step) and **dynamic
  simulation** (GridPACK's full-Y dynamic simulation: GENROU/GENSAL/GENCLS machines, IEEET1,
  SEXS, ESST1A, EXDC1 exciters, TGOV1 and other governors). PMUs then see the electromechanical
  transients, and the dashboard shows frequency and rotor angles. IEEE 39 uses its published
  machine data; other grids use typical data, or their own PSS/E `.dyr` file
  (`dynamics.dyr` in the grid directory).
- **Optimal PMU placement** (integer linear program): minimum for full observability, or
  redundant (every bus seen by two PMUs).
- **Network:** per-link latency with spread, jitter, packet loss, PDC wait window, reporting rate.
- **Attacks:** false data injection (simple, or stealthy across all channels of the target
  bus), packet delay and drop.
- **Defenses:** chi-square bad data detection with largest-normalized-residual PMU removal;
  control held while bad data cannot be cleaned; redundant placement.
- **Grid events:** generator AVR setpoint fault, load step (quasi-steady state); three-phase
  bus fault, line trip, generator trip, AVR setpoint fault (dynamic).
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

### Dynamic simulation (IEEE 39-bus, 15 s, published machine data)

| Event at t = 3 s | Lowest frequency | Violation time | What happened |
|---|---|---|---|
| Three-phase fault at bus 16, cleared after 0.1 s | 59.70 Hz | 3.6 s | Voltages fall to 0.56 pu, the machines swing (angle spread 66° → 125°) and settle; exciter overshoot to 1.16 pu brings control commands |
| Generator 32 trip (650 MW) | 59.42 Hz at 9.4 s | 12 s | Governors arrest the decline; under-voltage near bus 32 remains |
| Line 16–17 trip | 59.96 Hz | 0 s | Small swing, no violation |
| AVR fault at generator 30 (setpoint 1.12), control off | 59.86 Hz | 11 s | Exciter raises the voltage over 2 s and it stays high |
| Same, control on | 59.92 Hz | 2.0 s | The control center lowers the setpoint; the exciter brings the voltage back |

GridPACK needs 6.6 ms per PMU frame for IEEE 39 on one rank and 152 ms (one rank) or 118 ms
(two ranks) for the 2000-bus ACTIVSg2000 grid; details in
[documentation/cluster.md](documentation/cluster.md).

## Repository layout

```
cases/           IEEE 14–300 bus inputs, topology and reference solutions
federates/       grid_fed.py, cc_fed.py, observer_fed.py, run_experiment.py
  cpslib/        network model, PMU placement, state estimation, attacks, GridPACK client,
                 uploaded grids, cluster placement
gridpack/        persistent MPI GridPACK servers: pf_server (power flow), dsf_server (dynamic
                 simulation); patches applied to GridPACK 3.5 when it is built
ns3-scratch/     NS-3 network federate (multi-PMU mode and the legacy single-PMU mode)
webapp/          experiment API (FastAPI): queue, uploads, results, live state; scenario template
node-red/        dashboard flows and settings
legacy/          original single-PMU IEEE 14 demo used by the Node-RED console
tools/           make_cases.py (MATPOWER → testbed cases)
install/         native installer, build steps shared with Docker, systemd units, settings
docker/          Dockerfile, entrypoint, compose files (single server, virtual cluster)
documentation/   complete guide (DOCX/PDF), install and cluster guides, earlier user guide and technical report
```

## Documentation

- **[CPS_Testbed_Cluster_Guide.docx](documentation/CPS_Testbed_Cluster_Guide.docx)** ([PDF](documentation/CPS_Testbed_Cluster_Guide.pdf)): the complete guide to this testbed: concepts, architecture, installation, cluster set-up, the dashboard with screenshots, output files, validation results, sizing and troubleshooting
- [documentation/install.md](documentation/install.md): installation on Ubuntu 24.04, settings, logins, services, cluster set-up
- [documentation/cluster.md](documentation/cluster.md): architecture of the cluster, what runs where, tested results and MPI timings
- [CPS_Testbed_User_Guide.pdf](documentation/CPS_Testbed_User_Guide.pdf) and [CPS_Testbed_Technical_Report.pdf](documentation/CPS_Testbed_Technical_Report.pdf): the user guide and technical report of the preceding single-server version (web app, IEEE 14 console, validation and results); the simulation models described there are the ones used here

## Limitations

- Dynamic mode: loads are constant impedances (no load steps or load variation); machines
  without their own data use typical parameters; bus faults are bolted three-phase faults.
  GridPACK's EMT simulation is not used.
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
