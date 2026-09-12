#!/usr/bin/env python3
import json
import os
import subprocess #for runnning shell commands
import sys #for exit codes
import time
import urllib.error
import urllib.request
#urllib for http 

PORT = os.environ.get("PUBLIC_PORT", "8080")
BASE = "http://localhost:" + PORT
READY_TIMEOUT = 90

failures = []

def check(name, ok, detail=""):
    """Print one PASS/FAIL line and remember any failure."""
    print(("PASS  " if ok else "FAIL  ") + name + (("  -> " + detail) if detail else ""))
    if not ok:
        failures.append(name)

def http(path, method="GET", payload=None):
    """Call the stack. Returns (status_code, parsed_body)."""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())

def sh(command):
    """Run a shell command and return its stdout as text."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.stdout

def wait_until_ready(timeout):
    """Poll /ready until it reports ready, or give up after `timeout` seconds."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, body = http("/ready")
            if status == 200 and body.get("status") == "ready":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False

print("Validating " + BASE)
print("-" * 60)

# bounded wait to go through the whole stack till redis and postgres to ensure the stack is up
ready = wait_until_ready(READY_TIMEOUT)
check("stack becomes ready within " + str(READY_TIMEOUT) + "s", ready)
if not ready:
    print("-" * 60)
    print("FAILED: stack never became ready, skipping remaining checks")
    sys.exit(1)

# check simple endpoints
status, body = http("/")
check("GET / returns 200", status == 200, "status=" + str(status))

status, body = http("/health")
check("GET /health reports alive", status == 200 and body.get("status") == "alive")

# Dependency readiness.
status, body = http("/ready")
dependencies = body.get("dependencies", {})
check("postgres is ready", dependencies.get("postgres") == "ready")
check("redis is ready", dependencies.get("redis") == "ready")

# Redis counter increments.
status, first = http("/counter")
status, second = http("/counter")
check(
    "counter increments",
    second.get("counter") == first.get("counter") + 1,
    str(first.get("counter")) + " -> " + str(second.get("counter")),
)

# PostgreSQL write and read back
title = "validate-" + str(int(time.time()))
status, created = http("/records", method="POST", payload={"title": title})
check("POST /records creates a record", status == 201, "status=" + str(status))

status, listed = http("/records")
titles = [record["title"] for record in listed.get("records", [])]
check("created record is readable", title in titles)

# check for Both backends have traffic.
seen = set()
for _ in range(10):
    status, body = http("/instance")
    seen.add(body.get("instance_id"))
check("both backends respond", seen == {"app-01", "app-02"}, "saw " + str(sorted(seen)))

# 7. Network isolation: nginx can't reach the data layer but the app instances can.
resolved = sh("docker compose exec -T nginx getent hosts postgres").strip()
check("nginx cannot resolve postgres", resolved == "", resolved or "no output")

resolved = sh("docker compose exec -T app-01 getent hosts postgres").strip()
check("app-01 can resolve postgres", resolved != "", resolved)

#Only nginx may publish a host port.
lines = sh("docker ps --format '{{.Names}} {{.Ports}}'").splitlines()
published = [line for line in lines if "->" in line]
check(
    "only nginx publishes a host port",
    len(published) == 1 and published[0].startswith("nginx"),
    "; ".join(published) or "none",
)

print("-" * 60)
if failures:
    print("FAILED: " + str(len(failures)) + " check(s) failed")
    for name in failures:
        print("  - " + name)
    sys.exit(1)

print("All checks passed")
sys.exit(0)
