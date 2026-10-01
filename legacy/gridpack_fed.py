import csv, os
import helics as h

HERE = os.path.dirname(os.path.abspath(__file__))

rows = []
with open(os.path.join(HERE, 'pf14', 'pf_IEEE14_buses.csv')) as f:
    for row in csv.DictReader(f):
        rows.append((int(row['bus_id']), float(row['voltage_pu']), float(row['angle_deg'])))

fed = h.helicsCreateValueFederateFromConfig(os.path.join(HERE, "gridpack_fed.json"))
pub = h.helicsFederateGetPublication(fed, "gridpack/bus1_voltage")
cmd_sub = h.helicsFederateGetInputByTarget(fed, "ns3/control_command")
h.helicsFederateEnterExecutingMode(fed)
print("[GRIDPACK] federation joined, publishing voltages + listening for control commands")

t = 0.0
for step in range(1, len(rows)+1):
    t = h.helicsFederateRequestTime(fed, step)
    bus_id, v, ang = rows[step-1]
    h.helicsPublicationPublishDouble(pub, v)
    print(f"[GRIDPACK] t={t:.1f}s  bus {bus_id}  V={v:.4f} pu  angle={ang:.2f} deg")

    # check for a control command coming back from NS-3
    if h.helicsInputIsUpdated(cmd_sub):
        cmd = h.helicsInputGetString(cmd_sub)
        if cmd:
            print(f"[GRIDPACK] *** CONTROL COMMAND RECEIVED: {cmd}  -> applying corrective action at this bus ***")

h.helicsFederateDisconnect(fed)
h.helicsFederateFree(fed)
print("[GRIDPACK] finalized")
