import os
#!/usr/bin/env python3
# Blue = GridPACK true voltages, Red = NS-3 network-delivered (gaps where lost)
import csv, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

csvfile = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("CPS_SHARED", "/srv/cps"), "legacy", "last_compare.csv")

buses, v_true, v_recv = [], [], []
lost_buses = []
with open(csvfile) as f:
    for row in csv.DictReader(f):
        b = int(row['bus'])
        buses.append(b)
        v_true.append(float(row['sent_v']))
        if row['delivered'] == '1' and row['recv_v']:
            v_recv.append(float(row['recv_v']))
        else:
            v_recv.append(None)        # lost -> gap
            lost_buses.append(b)

plt.figure(figsize=(10,6))
# blue: true grid state, continuous
plt.plot(buses, v_true, 'b-o', linewidth=2, label='GridPACK (true grid state)')
# red: network-delivered, stepped, gaps at lost packets
plt.step(buses, v_recv, 'r-s', linewidth=2, where='mid',
         label='NS-3 (delivered to PDC)')
# mark lost packets
for b in lost_buses:
    idx = buses.index(b)
    plt.axvline(b, color='red', linestyle=':', alpha=0.4)
    plt.annotate('LOST', (b, v_true[idx]), textcoords="offset points",
                 xytext=(0,10), ha='center', color='red', fontsize=9, fontweight='bold')

plt.xlabel('Bus Number', fontsize=12)
plt.ylabel('Voltage (pu)', fontsize=12)
plt.title('Actual Grid Voltage vs Voltage Received at Control Center', fontsize=12)
plt.grid(True, linestyle='--', alpha=0.6)
plt.legend(fontsize=11)
plt.ylim(1.0, 1.1)
plt.xticks(buses)

out = os.path.join(os.path.dirname(csvfile), "voltage_compare.png")
plt.savefig(out, dpi=120, bbox_inches='tight')
print("saved:", out)
print("lost buses:", lost_buses)
