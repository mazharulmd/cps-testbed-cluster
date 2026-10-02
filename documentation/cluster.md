# CPS testbed on a cluster

The testbed runs on one server or as a cluster: GridPACK runs as an MPI job spread over
several machines, the HELICS federates (grid, NS-3 network, control center) can sit on
different nodes, and users upload grid models and scenario files and look at the results
in the Node-RED dashboard from their browser.

```
                     browser (remote user)
                            │  Node-RED dashboard :1880  ·  experiment API :8080
┌───────────────────────────▼────────────────────────── head ─┐
│ Node-RED: Experiments / Live / Results / IEEE 14 console    │
│ experiment API: queue, grid + scenario uploads, results     │
│ HELICS broker (one per experiment, own port), observer      │
│ grid federate ──stdin/stdout──► mpirun ─┐                   │
└─────────────────────────────────────────┼───────────────────┘
          HELICS (ZMQ/TCP)                │ MPI (ssh launch, TCP)
┌──────────────── node1 ──────┐  ┌────────▼──── node1 … nodeN ──┐
│ NS-3 network federate       │  │ pf_server ranks: GridPACK     │
│ (PMUs, links, PDC, attacks) │  │ power flow on a partitioned   │
├──────────────── node2 ──────┤  │ network (ParMETIS, PETSc)     │
│ control-center federate     │  └───────────────────────────────┘
└─────────────────────────────┘        /srv/cps: runs, grids, keys (NFS / volume)
```

## What runs where

| Part | Code | Notes |
|---|---|---|
| MPI dynamic simulation | `gridpack/dsf_server/dsf_server.cpp`, `gridpack/patches/` | Used with `mode: dynamic`. Started once per experiment like `pf_server`; GridPACK solves the initial power flow, initialises the machines from the `.dyr` data and integrates in steps of about 5 ms. Every PMU frame the grid federate sends the exciter reference changes (`DVREF`) and the time to reach (`STEP`); bus voltages and frequencies and every machine's speed, rotor angle, P and Q are gathered to rank 0. Faults, line and generator trips are scheduled in GridPACK's input file. The patch adds exciter reference changes at run time, access to the network for the gathering, and fixes a line trip crash on more than one rank. |
| MPI power flow | `gridpack/pf_server/pf_server.cpp` | Started once per experiment with `mpirun -np N`. GridPACK reads and partitions the network once; every grid step only the changed loads and generator setpoints are sent to rank 0, broadcast, applied and solved. Voltages are gathered back to rank 0. |
| Grid federate | `federates/grid_fed.py`, `cpslib/gridpack.py` (`GridPackMPISolver`, `GridPackDynamicSolver`), `cpslib/dynamics.py` (machine data) | Drives `pf_server` or `dsf_server` over its stdin/stdout. Logs the whole step time and the MPI solve time of every step (`grid_steps.csv`). |
| Placement of federates | `federates/cpslib/cluster.py`, `run_experiment.py` | Reads `/srv/cps/cluster.json` (written by `install/configure.py`); starts the broker and each federate on its node over ssh; each experiment gets its own HELICS port so several can run at once. |
| Scheduling | `webapp/app.py` | Up to `CPS_MAX_JOBS` experiments at once, but a run starts only when its GridPACK ranks fit in the free MPI slots; the others wait in the queue ("waiting for N MPI slots"). MPI ranks busy-wait, so oversubscribing the slots made two parallel 4-rank runs about ten times slower (150 s instead of 13 s each). |
| Uploads | `federates/cpslib/grids.py`, `webapp/scenario.py` | MATPOWER `.m` (or testbed `topology.json`) grid models; YAML/JSON scenario files (`webapp/scenario_template.yaml`). |
| Live view | `federates/observer_fed.py` | A fourth HELICS federate on the head that only subscribes: true grid state (`grid/status`), what the control center sees (`cc/status`), commands issued and delivered. No federate waits for it. It writes `live.json` in the run directory about twice a second; the API serves it at `/api/live`. |
| Dashboard | `node-red/flows.json` (tab *CPS Cluster*) | Experiments page: cluster nodes, uploads, grid list, queue. Live page: the running experiment, updated every second (progress, highest true and estimated voltage, alarms, chi-square, PDC completeness, any bus, commands as they are issued, delivered and applied). Results page: runs, summary, charts (voltages, chi-square, GridPACK time per step, latency, PDC completeness, per-PMU delivery), commands. |
| Build | `install/steps/`, `docker/Dockerfile`, `install/install.sh` | The same build scripts for the container and a native Ubuntu 24.04 installation, from source: OpenMPI 4.1, PETSc 3.19 (MUMPS), ParMETIS, Global Arrays 5.9, GridPACK 3.5, HELICS 3.6.1, NS-3.48, Node-RED 4.1 + Dashboard 2. One image (or installation) for every node. |

## Try it on one machine (virtual cluster)

```bash
docker build -f docker/Dockerfile -t cps-testbed-cluster .       # about 1 hour the first time
docker compose -f docker/compose.cluster.yml up -d
```

`docker/compose.cluster.yml` starts a head and two compute nodes (`node1`, `node2`, 2 MPI slots
each). GridPACK runs on 4 MPI ranks across both nodes, NS-3 on `node1` and the control center
on `node2`. Open:

- Dashboard: http://localhost:1880/dashboard/experiments
- API (and its documentation): http://localhost:8080/docs

Set `CPS_WEB_PASSWORD` and `NODERED_ADMIN_HASH` in the compose file's environment (natively:
`sudo cps-passwd`, see [install.md](install.md#logins)) before exposing the ports to anyone
else.

## Using it

1. **Grid model (optional).** On *Experiments*, upload a MATPOWER case (`.m`). The testbed
   checks the power flow, computes the optimal PMU placement and lists the grid with an id
   such as `case_activsg2000-12345`. PSS/E `.raw` files: convert them in MATPOWER first
   (`mpc = psse2mpc('grid.raw'); savecase('grid.m', mpc)`).
2. **Experiment.** In *New experiment*, start from a ready-made scenario or set grid, mode,
   event, attack, network, duration and MPI ranks, then *Run experiment*. For several
   experiments at once, download the *scenario template*, edit it and upload it; a file can
   hold several experiments under `scenarios:`. Each one is validated, queued and run on the
   cluster.
3. **Live.** While an experiment runs, the *Live* page follows it second by second: the
   voltages GridPACK computes next to what the control center estimates, bad data alarms,
   PDC completeness, and each command from the moment it is issued until GridPACK applies it.
   Enter a bus number to follow another bus; the whole history of that bus is shown.
4. **Results.** The *Results* page opens each finished run: summary figures, voltage and
   chi-square charts, GridPACK solve time per step for the chosen number of MPI ranks, network
   latency and delivery, and the commands sent to the grid. Raw files are in
   `/srv/cps/runs/<run id>/`.

5. **Cluster.** The *Cluster* page shows every node and lets you change the cluster without
   editing files: default MPI ranks, experiments at the same time, the compute nodes and
   their MPI slots, and the node of each federate. Changes apply to the next experiments.

The API does the same for scripts (cluster settings: `GET`/`PUT`/`DELETE /api/cluster/settings`):

```bash
curl -F file=@case_ACTIVSg2000.m http://localhost:8080/api/grids/file
curl -F file=@my_scenario.yaml   http://localhost:8080/api/scenarios/file
curl http://localhost:8080/api/runs
```

## Real machines

Install every machine natively with `install/install.sh` (`--role node` on compute nodes) as
described in [install.md](install.md#cluster), or run the image on each machine. Either way the
machines need:

1. **A shared directory** mounted at `/srv/cps` on all nodes (NFS or similar). Runs, uploaded
   grids, the hostfile and the cluster's SSH key live there.
2. **Name resolution and open TCP** between the nodes (ssh, HELICS ports 23500 and up, MPI).
3. **The role settings**: `CPS_ROLE=node` on compute nodes; on the head `CPS_NODES=host1:16,host2:16`,
   `CPS_PLACE_NS3`, `CPS_PLACE_CC`, `CPS_MPI_NP`, `CPS_MAX_JOBS` (`/etc/cps/cps.env` natively,
   container environment variables with Docker). With Docker on several machines use
   `--network host` so that MPI and HELICS see the real interfaces, and set
   `OMPI_MCA_btl_tcp_if_include` / `OMPI_MCA_oob_tcp_if_include` to the cluster interface.

The head writes `/srv/cps/cluster.json` and `/srv/cps/hostfile` at start-up
(`install/configure.py`). Remote users reach the dashboard through the institution's VPN or an
SSH tunnel to the head.

## Tested

On the virtual cluster (head + 2 nodes, all three containers on one 4-core machine):

| Experiment | Result |
|---|---|
| IEEE 118, AVR fault at gen 49 (t = 4 s) + simple FDI on bus 49, GridPACK on 4 ranks (node1 + node2), NS-3 on node1, control center on node2 | Same outcome as the single-server testbed and the user guide example: violation 0.5 s, FDI detected in one frame (0.033 s), PMU 49 removed, command issued at 4.067 s, delivered at 4.107 s, applied at 4.5 s; 9568/9568 frames delivered |
| ACTIVSg2000 (2000-bus Texas grid, uploaded as MATPOWER `.m`), 512 PMUs, AVR fault at gen 1004 + simple FDI | 76 288 frames delivered; violation corrected within one grid step (0.5 s). The FDI falsifies a current channel of PMU 3133 that is a critical measurement, so it is not detected (minimum placement; see the main README) |
| Two ACTIVSg2000 experiments queued from one scenario file | Ran at the same time on HELICS ports 23600 and 23700, both completed correctly |
| IEEE 118, AVR fault + delay attack (100 ms) on the PMUs around bus 49 | Violation 5.5 s, PMUs 45 and 49 delayed, 49.7% complete PDC sets, as in the main README |
| IEEE 118, AVR fault + 5% packet loss | 18.1% complete PDC sets, violation still corrected in 0.5 s, as in the main README |
| IEEE 118, 60% load step at bus 59, GridPACK (4 ranks) and built-in solver | True bus voltages identical to six decimals at every step |
| Legacy IEEE 14 console script | 13/14 delivered, bus 8 over-voltage detected, as before |
| Live page during a 30 s IEEE 118 run (fault at 8 s, FDI 8-20 s) | Updated every second while running; showed the command issued at 8.067 s, delivered at 8.107 s and applied at 8.5 s as they happened. With the observer the 10 s IEEE 118 run took 12.3 and 13.7 s (12.2 s without) |

Dynamic simulation (`mode: dynamic`, IEEE 39 with its published GENROU/IEEET1/TGOV1 data, 15 s):

| Experiment | Result |
|---|---|
| Three-phase fault at bus 16 (t = 3 s, cleared after 0.1 s), from a scenario file on the dashboard | Voltages down to 0.56 pu during the fault, frequency 59.70–60.6 Hz, rotor angle spread 66° → 125° and back; the exciters overshoot to 1.16 pu and the control center sends 24 setpoint commands; final 60.04 Hz. 100% frames delivered |
| Generator 32 trip (650 MW), run at the same time as the fault | Frequency falls to 59.42 Hz at 9.4 s and recovers under governor control (59.54 Hz at 15 s) |
| Line 16–17 trip | Lowest frequency 59.96 Hz, no voltage violation |
| AVR fault at generator 30 (setpoint 1.12 at 3 s), control off / on | Violation 11.0 s / 2.0 s; with control the center lowers the setpoint 3 times and the exciter brings the voltage back |
| Same fault on 1, 2 and 4 ranks | Identical voltages, frequencies and angles |
| ACTIVSg2000 (typical machine data, 432 machines), trip of the largest generator | Lowest frequency 59.81 Hz; 1 and 2 ranks identical |

GridPACK time per PMU frame (1/30 s, seven integration steps of 4.76 ms):

| Grid | 1 rank | 2 ranks (one node) | 4 ranks (node1 + node2) |
|---|---|---|---|
| IEEE 39 | 6.6 ms | 12.9 ms | 274 ms |
| ACTIVSg2000 | 152 ms | 118 ms | |

A small grid runs faster than real time on one rank (15 s simulated in about 7 s). The
dynamic simulation exchanges many small messages per integration step, so ranks on two
containers of the 4-core test machine, which also run NS-3, the control center and the
services, wait on each other; on separate machines with their own cores this cost is far
lower. Large grids gain from more ranks.

`pf_server` against the testbed's Newton-Raphson solver (four operating points with load and
setpoint changes): IEEE 118 and ACTIVSg2000 agree to 5×10⁻¹⁰ pu, ACTIVSg10k to 6×10⁻⁵ pu.
MPI solve time per grid step:

| Grid | 1 rank | 2 ranks | 4 ranks |
|---|---|---|---|
| IEEE 118, ranks in one container | 6–16 ms | 15–27 ms | 15–31 ms |
| IEEE 118, 4 ranks split over node1 and node2 | | | 61–71 ms |
| ACTIVSg2000, one container | 104–120 ms | 78–116 ms | 55–97 ms |
| ACTIVSg10k, one container | 526–638 ms | 452–624 ms | 356–508 ms |

Small grids are fastest on one rank: the work per solve is tiny and every extra rank adds MPI
messages (about 60 ms per solve when the ranks span two containers over TCP). The 10 000-bus
grid gets faster with more ranks even on four shared cores; on separate machines with their
own cores the gain is larger. When several co-simulations run at once on the same few cores,
GridPACK's times rise because MPI ranks, NS-3 and the control center compete for the CPU.

## Limits

- Small grids (IEEE 14 to 300) solve in milliseconds, so more MPI ranks do not make them
  faster; the cluster pays off for large grids, long or many experiments.
- Dynamic mode: constant-impedance loads, typical machine data where a grid has no `.dyr`
  file, bolted three-phase faults.
- Uploaded grids: MATPOWER `.m` and testbed `topology.json`. PSS/E is read through MATPOWER's
  converter.
- The SSH key of the virtual cluster is created at first start and shared through `/srv/cps`;
  on real machines use the site's own key management if it has one.
