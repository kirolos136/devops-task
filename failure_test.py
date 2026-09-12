#!/usr/bin/env python3
"""Stop one backend, measure availability, restore it, and prove recovery.

Exits 0 if the service stayed available and the backend recovered, 1 otherwise.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = os.environ.get("PUBLIC_PORT", "8080")
BASE = "http://localhost:" + PORT
VICTIM = "app-02"
REQUESTS_PER_PHASE = 20

failures = []

def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        failures.append(name)

def sh(command):
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout

def measure(label, count):
    """Send `count` GETs through nginx. Returns (ok_count, error_count, instances_seen)."""
    ok = 0
    errors = 0
    seen = {}
    for _ in range(count):
        try:
            request = urllib.request.Request(BASE + "/instance")
            with urllib.request.urlopen(request, timeout=5) as response:
                body = json.loads(response.read().decode())
                instance = body.get("instance_id")
                seen[instance] = seen.get(instance, 0) + 1
                ok += 1
        except Exception:
            errors += 1
    print("  " + label + ": " + str(ok) + " ok, " + str(errors) + " errors, served by " + str(seen))
    return ok, errors, seen

# baseline -> Both backends should be serving.
print("Phase 1: baseline")
ok, errors, seen = measure("baseline", REQUESTS_PER_PHASE)
check("baseline has no errors", errors == 0, str(errors) + " errors")
check("baseline uses both backends", len(seen) == 2, str(sorted(seen)))

# stop one backend and keep sending traffic.
print("Phase 2: " + VICTIM + " stopped")
sh("docker compose stop " + VICTIM)
time.sleep(2)
ok, errors, seen = measure("during failure", REQUESTS_PER_PHASE)
check("service stayed available with one backend down", ok > 0, str(ok) + " succeeded")
check(VICTIM + " served nothing while stopped", VICTIM not in seen, str(sorted(seen)))

# bring it back and wait for it to become healthy.
print("Phase 3: restoring " + VICTIM)
sh("docker compose start " + VICTIM)
deadline = time.time() + 60
healthy = False
while time.time() < deadline:
    status = sh("docker inspect --format '{{.State.Health.Status}}' " + VICTIM).strip()
    if status == "healthy":
        healthy = True
        break
    time.sleep(2)
check(VICTIM + " became healthy again", healthy)

# prove the recovered backend actually serves traffic.
print("Phase 4: after recovery")
time.sleep(12)
ok, errors, seen = measure("after recovery", REQUESTS_PER_PHASE)
check("no errors after recovery", errors == 0, str(errors) + " errors")
check(VICTIM + " serves requests again", VICTIM in seen, str(sorted(seen)))

print("-" * 60)
if failures:
    print("FAILED: " + str(len(failures)) + " check(s) failed")
    for name in failures:
        print("  - " + name)
    sys.exit(1)

print("All checks passed")
sys.exit(0)