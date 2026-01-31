import sys
import requests

if len(sys.argv) < 2:
    print("Usage: python ci_gate_check.py <run_id>")
    sys.exit(2)

RUN_ID = sys.argv[1]

url = f"http://localhost:8000/ship/decision?run_id={RUN_ID}"
resp = requests.get(url)
resp.raise_for_status()

data = resp.json()

decision = data.get("decision")
reason = data.get("reason")

if decision != "SHIP":
    print(f"❌ CI BLOCKED for run {RUN_ID}: {reason}")
    sys.exit(1)

print(f"✅ CI PASS for run {RUN_ID}: SHIP")
