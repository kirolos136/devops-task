#!/usr/bin/env python3
"""Answer every question in log_analysis.md from the three supplied log files.

Usage:  python3 scripts/analyze_logs.py
Reads logs/access.log, logs/application.log and logs/error.log. Never writes to them.
"""

import collections
import json
import os
import re

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


def load_json_log(name):
    """Return (valid_records, malformed_line_numbers)."""
    valid, malformed = [], []
    with open(os.path.join(LOG_DIR, name), encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                valid.append(json.loads(line))
            except ValueError:
                malformed.append(number)
    return valid, malformed


def percentile(values, fraction):
    """Nearest-rank percentile on a sorted copy. Returns a value from the data itself."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, int(round(fraction * len(ordered) + 0.5)) - 1)
    return ordered[min(rank, len(ordered) - 1)]


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


access, access_bad = load_json_log("access.log")
app, app_bad = load_json_log("application.log")
error_lines = open(os.path.join(LOG_DIR, "error.log"), encoding="utf-8").read().splitlines()

# ---------------------------------------------------------------- Q1
section("Q1  Coverage, and valid / malformed / duplicate line counts")

access_ids = collections.Counter(r.get("request_id") for r in access)
app_ids = collections.Counter(r.get("request_id") for r in app)
access_dupes = {k: v for k, v in access_ids.items() if v > 1}
app_repeats = {k: v for k, v in app_ids.items() if v > 1}

stamps = sorted(r["timestamp"] for r in access if "timestamp" in r)
print("UTC interval (access.log) : %s  ->  %s" % (stamps[0], stamps[-1]))
print("error.log last line       : %s" % error_lines[-1][:19])
print()
print("access.log      : %d lines, %d valid, %d malformed %s"
      % (len(access) + len(access_bad), len(access), len(access_bad), access_bad))
print("                  %d distinct request_id, %d duplicated"
      % (len(access_ids), len(access_dupes)))
print("application.log : %d lines, %d valid, %d malformed %s"
      % (len(app) + len(app_bad), len(app), len(app_bad), app_bad))
print("                  %d distinct request_id, %d appearing more than once"
      % (len(app_ids), len(app_repeats)))
print("error.log       : %d lines, %d carrying a request_id"
      % (len(error_lines), sum(1 for l in error_lines if "request_id=" in l)))

# ---------------------------------------------------------------- Q2
section("Q2  Distinct client requests, and how retries are not double counted")

# One access.log record = one client request. Duplicated request_ids are duplicate
# log records, so keep the first occurrence of each id.
seen = set()
client_requests = []
for record in access:
    rid = record.get("request_id")
    if rid in seen:
        continue
    seen.add(rid)
    client_requests.append(record)

retried = [r for r in client_requests if "," in str(r.get("upstream", ""))]
attempts = sum(len(str(r.get("upstream", "")).split(",")) for r in client_requests)

print("distinct client requests (denominator) : %d" % len(client_requests))
print("duplicate access.log records dropped   : %d" % len(access_dupes))
print("malformed access.log lines excluded    : %d" % len(access_bad))
print("client requests that were retried      : %d" % len(retried))
print("total upstream attempts behind them    : %d" % attempts)
print("application.log records                : %d  (one per ATTEMPT, not per client request)"
      % len(app))

# ---------------------------------------------------------------- Q3
section("Q3  Client-facing status counts and error rate")

status_counts = collections.Counter(r.get("status") for r in client_requests)
errors_5xx = sum(v for k, v in status_counts.items() if k and k >= 500)
print("denominator = %d distinct client requests from access.log" % len(client_requests))
for code in sorted(status_counts):
    print("  %s : %d" % (code, status_counts[code]))
print()
print("5xx errors  : %d" % errors_5xx)
print("error rate  : %.2f%%  (%d / %d)"
      % (100.0 * errors_5xx / len(client_requests), errors_5xx, len(client_requests)))

# ---------------------------------------------------------------- Q4
section("Q4  Which paths, time windows and backends account for the failures")

failed = [r for r in client_requests if r.get("status", 200) >= 500]
by_path = collections.Counter(r["path"] for r in failed)
by_minute = collections.defaultdict(collections.Counter)
for r in failed:
    by_minute[r["timestamp"][11:16]][r["status"]] += 1

print("failures by path:")
for path, count in by_path.most_common():
    print("  %-10s %d" % (path, count))
print()
print("failures by minute:      502  503  504")
for minute in sorted(by_minute):
    c = by_minute[minute]
    print("  %s              %3d  %3d  %3d" % (minute, c[502], c[503], c[504]))
print()
upstream_errors = collections.Counter(re.findall(r'upstream: "http://([0-9.]+:[0-9]+)', "\n".join(error_lines)))
print("error.log entries by upstream address:")
for address, count in upstream_errors.most_common():
    print("  %-20s %d" % (address, count))

# ---------------------------------------------------------------- Q5
section("Q5  Client latency, median and p95")

latencies = [float(r["request_time"]) for r in client_requests if "request_time" in r]
print("units  : seconds (access.log request_time). application.log duration_ms is milliseconds.")
print("method : nearest-rank percentile over %d client requests, sorted ascending." % len(latencies))
print("count  : %d" % len(latencies))
print("min    : %.3f s" % min(latencies))
print("median : %.3f s" % percentile(latencies, 0.50))
print("p95    : %.3f s" % percentile(latencies, 0.95))
print("max    : %.3f s" % max(latencies))

# ---------------------------------------------------------------- Q6
section("Q6  Retries, and how many succeeded after retrying")

recovered = [r for r in retried if r.get("status") == 200]
print("client requests with more than one upstream attempt : %d" % len(retried))
print("of those, final client status 200                   : %d" % len(recovered))
print("of those, still failed                              : %d" % (len(retried) - len(recovered)))
print()
print("examples:")
for r in retried[:3]:
    print("  %s  %-9s upstream=%s  upstream_status=%s  client_status=%s"
          % (r["request_id"], r["path"], r["upstream"], r["upstream_status"], r["status"]))

# ---------------------------------------------------------------- Q7
section("Q7  Incident timeline, correlated across all three logs")

dep_errors = [r for r in app if r.get("event") == "dependency_error"]
dep_counts = collections.Counter(r.get("dependency") for r in dep_errors)
dep_first = {}
dep_last = {}
for r in dep_errors:
    name = r.get("dependency")
    dep_first.setdefault(name, r["timestamp"])
    dep_last[name] = r["timestamp"]

refused = [l for l in error_lines if "Connection refused" in l]
timedout = [l for l in error_lines if "timed out" in l]

print("nginx connection refused : %d, from %s to %s"
      % (len(refused), refused[0][:19], refused[-1][:19]))
print("nginx upstream timeouts  : %d, from %s to %s"
      % (len(timedout), timedout[0][:19], timedout[-1][:19]))
print()
print("application dependency_error events: %d" % len(dep_errors))
for name in dep_counts:
    print("  %-9s %d events, %s -> %s" % (name, dep_counts[name], dep_first[name], dep_last[name]))

# ---------------------------------------------------------------- Q8
section("Q8  One correlated failed request and one successful request")

app_by_id = {}
for r in app:
    app_by_id.setdefault(r.get("request_id"), []).append(r)

sample_failed = next(r for r in client_requests if r.get("status") == 502)
sample_ok = retried[0] if retried else client_requests[0]

for label, record in (("FAILED", sample_failed), ("SUCCEEDED AFTER RETRY", sample_ok)):
    rid = record["request_id"]
    print("%s  request_id=%s" % (label, rid))
    print("  access.log      : %s" % json.dumps(record))
    for entry in app_by_id.get(rid, []):
        print("  application.log : %s" % json.dumps(entry))
    for line in error_lines:
        if "request_id=" + rid in line:
            print("  error.log       : %s" % line)
    print()

# ---------------------------------------------------------------- Q9
section("Q9  Proxy / connectivity errors versus dependency / application errors")

ids_in_error_log = set(re.findall(r"request_id=(\S+?)[,\s]", "\n".join(error_lines)))
for code in (502, 503, 504):
    ids = {r["request_id"] for r in client_requests if r.get("status") == code}
    overlap = len(ids & ids_in_error_log)
    print("status %d : %3d client requests, %3d of them appear in error.log  (%.0f%%)"
          % (code, len(ids), overlap, 100.0 * overlap / len(ids) if ids else 0))

# ---------------------------------------------------------------- Q10
section("Q10  Coverage limits")

print("distinct client IP addresses in access.log : %d"
      % len({r.get("client") for r in client_requests if r.get("client")}))
print("upstream addresses seen                    : %s"
      % sorted({u.strip() for r in client_requests for u in str(r.get("upstream", "")).split(",") if u.strip()}))
print("instance_id values seen in application.log : %s"
      % sorted({r.get("instance_id") for r in app if r.get("instance_id")}))
print()
print("No log here records container lifecycle, resource usage, database or Redis server")
print("state, or configuration at the time. Those would have to come from the running system.")
