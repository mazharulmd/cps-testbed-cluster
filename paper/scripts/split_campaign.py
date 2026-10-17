"""Split the campaign file into parts of at most 45 experiments (the API accepts 50 per file).

Usage: python split_campaign.py ../campaign/paper118_seeds.yaml
Then upload each part on the dashboard's Experiments page or with
    curl -u admin -F file=@part1.yaml http://<head>:8080/api/scenarios/file
"""
import sys

import yaml

doc = yaml.safe_load(open(sys.argv[1]))
sc = doc["scenarios"]
for i in range(0, len(sc), 45):
    part = dict(doc, scenarios=sc[i:i + 45])
    with open(f"part{i // 45 + 1}.yaml", "w") as f:
        yaml.safe_dump(part, f, sort_keys=False)
print((len(sc) + 44) // 45, "parts")
