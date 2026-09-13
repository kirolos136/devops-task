# Log analysis

## Commands / scripts

Every number below comes from `scripts/analyze_logs.py`, which reads the three supplied logs and
never writes to them. Reproduce all of it with one command:

```bash
python3 scripts/analyze_logs.py
```

The originals in `logs/` are unchanged.

---

## Results

### 1. Coverage, valid / malformed / duplicate lines

**UTC interval:** `2026-08-20T11:00:00.015Z` to `2026-08-20T11:29:57.578Z` in `access.log`.
`error.log` runs to `2026/08/20 11:30:00`. About a 30 minute window.

| File | Lines | Valid | Malformed | Distinct `request_id` | Repeated ids |
|---|---|---|---|---|---|
| access.log | 726 | 725 | 1 (line 311) | 720 | 5 |
| application.log | 730 | 729 | 1 (line 401) | 680 | 49 |
| error.log | 68 | 67 carry a `request_id` | - | - | - |

Both malformed lines are truncated JSON that stops mid-record. They are excluded from every
count rather than guessed at.

The two kinds of repeated id are **not** the same thing:

- The 5 repeats in `access.log` are genuine duplicate log records: the same client request
  written twice. One copy of each is kept.
- The 49 repeats in `application.log` are **retries**. One client request that nginx retried on a
  second backend produces two application records, one per attempt. They are real separate
  attempts and are counted as attempts, not dropped.

### 2. Distinct client requests, and avoiding double counting

**720 distinct client requests.**

```
distinct client requests (denominator) : 720
duplicate access.log records dropped   : 5
malformed access.log lines excluded    : 1
client requests that were retried      : 19
total upstream attempts behind them    : 739
application.log records                : 729  (one per ATTEMPT)
```

The method is to pick the right file for the question:

- **`access.log` is the client-facing record.** One line is one client request, whatever nginx
  had to do behind it. Deduplicated on `request_id`, this is the only correct denominator.
- **`application.log` is per backend attempt.** 729 records for 720 client requests, because
  retries are logged by both instances that handled them. Counting it would inflate the total
  and, worse, would count a retried-but-successful request as a failure.

Concretely: `lab-000124` appears once in `access.log` with a final status of 200, and its
`upstream_status` is `"502, 200"`. Counting attempts would record a 502 the client never saw.

### 3. Client status counts and error rate

**Denominator: 720 distinct client requests from `access.log`.**

| Status | Count |
|---|---|
| 200 | 615 |
| 404 | 10 |
| 502 | 40 |
| 503 | 47 |
| 504 | 8 |

**5xx total: 95. Client-facing error rate: 13.19% (95 / 720).**

The 404s are excluded from the error rate: they are the client requesting `/missing`, which is a
correct response to a wrong path, not a failure of the system.

### 4. Paths, time windows and backends

**By path:**

| Path | 5xx |
|---|---|
| /records | 26 |
| /counter | 26 |
| /ready | 23 |
| /health | 10 |
| / | 10 |

**By minute** — the shape matters more than the total, because it separates three incidents:

```
minute   502  503  504
11:05      8    0    0     <- incident 1 begins
11:06      8    0    0
11:07      8    0    0
11:08      8    0    0
11:09      8    0    0     <- ends 11:09:57
11:12      0    8    0     <- incident 2 begins
11:13      0    7    0
11:14      0    8    0
11:15      0    8    0
11:20      0    8    0     <- incident 2, second phase
11:21      0    8    0
11:25      0    0    4     <- incident 3
11:26      0    0    4
```

**By backend**, from `error.log`:

| Upstream | nginx errors |
|---|---|
| 172.23.0.12:8080 | 62 |
| 172.23.0.11:8080 | 4 |

One backend, `172.23.0.12`, accounts for 94% of all proxy-level errors.

### 5. Latency

**Units:** `request_time` in `access.log` is **seconds**. `duration_ms` in `application.log` is
**milliseconds**. The two are not interchangeable and only the access figure is client-facing.

**Method:** nearest-rank percentile over all 720 client requests sorted ascending. The value
returned is an actual observation from the data, not an interpolation between two points.

| | |
|---|---|
| count | 720 |
| min | 0.003 s |
| **median** | **0.054 s** |
| **p95** | **2.001 s** |
| max | 2.025 s |

The gap between the median and p95 is the story: half of all requests finished in 54
milliseconds, while the slowest 5% clustered tightly just above 2.0 seconds. That ceiling is not
a coincidence, it is a timeout cutting requests off, and it matches the 504s in incident 3.

### 6. Retries

```
client requests with more than one upstream attempt : 19
of those, final client status 200                   : 19
of those, still failed                              : 0
```

**Every retried request succeeded.** nginx tried the failed backend, got a 502, retried on the
healthy one, and returned 200 to the client.

```
lab-000124  /ready    upstream=172.23.0.12:8080, 172.23.0.11:8080  upstream_status="502, 200"  client=200
lab-000130  /instance upstream=172.23.0.12:8080, 172.23.0.11:8080  upstream_status="502, 200"  client=200
lab-000136  /ready    upstream=172.23.0.12:8080, 172.23.0.11:8080  upstream_status="502, 200"  client=200
```

Retries are identifiable by the comma in `upstream` and `upstream_status`. nginx populates those
fields with one entry per attempt.

---

## Timeline and correlated examples

### 7. Incident timeline

Three separate incidents, not one. Each has a different signature and a different cause.

**Incident 1 — 11:05:02 to 11:09:57: one backend refusing connections**

- `error.log`: 59 `connect() failed (111: Connection refused)`, almost all to `172.23.0.12:8080`
- `access.log`: 40 client 502s, a steady 8 per minute for five minutes
- 19 further requests hit the same backend, were retried on `172.23.0.11`, and returned 200

Connection refused means nothing was listening on that address. The instance was down, not slow.
The steady rate reflects round-robin sending roughly half of all traffic to a dead backend.

**Incident 2 — 11:12:09 to 11:21:45: dependency outages**

- `application.log`: 47 `dependency_error` events
  - **redis**: 31 events, `11:12:09.524Z` to `11:15:52.024Z`
  - **postgres**: 16 events, `11:20:07.540Z` to `11:21:45.040Z`
- `access.log`: 47 client 503s, matching exactly
- `error.log`: **nothing**

Two separate dependency outages, Redis first and PostgreSQL eight minutes later. The application
was healthy throughout: it accepted every request and answered honestly that a dependency was
unavailable. That is why nginx logged nothing.

**Incident 3 — 11:25:14 to 11:26:47: upstream timeouts**

- `error.log`: 8 `upstream timed out (110: Operation timed out) while reading response header`
- `access.log`: 8 client 504s
- Affects **both** `172.23.0.11` and `172.23.0.12`

Unlike incident 1, the backends accepted the connection and then failed to respond in time. The
p95 latency of 2.001 s and maximum of 2.025 s show where the cutoff sat. Because both instances
are affected, the cause is more likely to be shared and downstream than a single bad instance.

### 8. Correlated examples

**A failed request**

```
access.log
{"timestamp": "2026-08-20T11:05:02.503Z", "request_id": "lab-000122", "method": "GET",
 "path": "/health", "status": 502, "upstream": "172.23.0.12:8080",
 "upstream_status": "502", "request_time": 0.003, "client": "192.0.2.24"}

error.log
2026/08/20 11:05:02 [error] 31#31: *122 connect() failed (111: Connection refused) while
connecting to upstream, request_id=lab-000122, request: "GET /health HTTP/1.1",
upstream: "http://172.23.0.12:8080/health"

application.log
(no record)
```

There is no application record because no application ever received the request. nginx could not
open a connection. A `request_time` of 0.003 s confirms it failed immediately rather than hanging.

**A request that succeeded after retrying**

```
access.log
{"timestamp": "2026-08-20T11:05:07.620Z", "request_id": "lab-000124", "method": "GET",
 "path": "/ready", "status": 200, "upstream": "172.23.0.12:8080, 172.23.0.11:8080",
 "upstream_status": "502, 200", "request_time": 0.12, "client": "192.0.2.24"}

error.log
2026/08/20 11:05:07 [error] ... connect() failed (111: Connection refused) ...
request_id=lab-000124, upstream: "http://172.23.0.12:8080/ready"

application.log
{"timestamp": "2026-08-20T11:05:07.620Z", "level": "INFO", "event": "http_request",
 "request_id": "lab-000124", "instance_id": "app-01", "status": 200, "duration_ms": 120.0}
```

Same five seconds, same dead backend, completely different client outcome. nginx failed on `.12`,
retried on `.11`, and the client saw a 200. The failure is visible only in `error.log` and in the
comma-separated upstream fields.

This pair also maps address to instance: `lab-000124` was finally served by `172.23.0.11`, and
`application.log` records that as `app-01`.

---

## Conclusions and limits

### 9. Proxy errors versus application errors, and what proves it

| Status | Client requests | Appearing in `error.log` |
|---|---|---|
| 502 | 40 | **40 (100%)** |
| 503 | 47 | **0 (0%)** |
| 504 | 8 | **8 (100%)** |

**502 and 504 are proxy and connectivity failures.** Every one has a matching nginx `error.log`
entry naming the upstream address and the reason: connection refused for the 502s, read timeout
for the 504s. In both cases nginx never obtained a response from the application.

**503 is an application and dependency failure.** Not one of the 47 appears in `error.log`,
because nothing went wrong at the proxy layer: nginx connected successfully and the application
answered. It answered 503 because its own dependency check failed, which `application.log`
records as 47 `dependency_error` events naming `redis` or `postgres`.

**What proves it** is the 100% / 0% / 100% split across two independently produced files. The
status code alone would require trusting an interpretation of what 503 means. The correlation
does not: it is a fact anyone can re-run.

### 10. What the logs do not prove, and what to check next

These logs are three views of HTTP traffic. They record what happened at the edge and inside the
application, and nothing else. They do not contain:

- **Why `172.23.0.12` stopped accepting connections.** Connection refused is a symptom. Whether
  the container crashed, was killed for exceeding memory, was restarted, or the process exited is
  not in any of these files.
- **Why Redis and PostgreSQL became unavailable**, or whether the two outages share a cause. The
  application records only that its check failed and the exception type, not the state of the
  server it was talking to.
- **What the 2 second ceiling actually was.** The latency distribution shows a cutoff, but which
  timeout produced it, and what the backend was waiting on, is not recorded here.
- **Resource usage, container lifecycle or configuration at the time.** No memory, CPU, restart or
  deployment information exists in these files.

Coverage limits worth stating: all traffic comes from a single client address, `192.0.2.24`, so
this is a synthetic load source rather than real user traffic, and nothing can be concluded about
geographic or per-client behaviour. Only two upstream addresses appear, so the system was running
two instances throughout.

**What I would check next in a running environment:**

1. `docker compose ps` and `docker inspect` on the failed instance, for exit code, OOM kill flag
   and restart count. That distinguishes a crash from a kill from a deliberate stop.
2. PostgreSQL and Redis server logs across `11:12` to `11:22`, to find out whether they were down,
   overloaded, or simply unreachable from the application.
3. Container resource metrics against the configured limits, to test whether the 2 second timeouts
   in incident 3 came from resource starvation affecting both instances at once.
4. Whether the three incidents share a root cause. Three different failures inside twenty minutes,
   on a system that was otherwise stable, is more likely to be one underlying problem than three
   coincidences, and nothing in these logs can settle that either way.
