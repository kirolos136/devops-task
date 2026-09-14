<img src="assets/barq-logo.svg" alt="BARQ Systems" width="180">

# BARQ DevOps Internship Task — repaired environment

A Flask API behind NGINX, backed by PostgreSQL and Redis, running on Docker Compose.

The environment was supplied deliberately broken. **27 faults were found and fixed**, each one
recorded with a symptom, a hypothesis, a test and evidence in
[troubleshooting.md](troubleshooting.md).

**Final state:** three application instances behind NGINX on host port **8090**, two isolated
networks, persistent storage, and CI that builds and validates the stack on every push.

![Architecture](architecture.png)

---

## Setup

Requires Linux or WSL2, Docker with Compose v2, and Python 3.

```bash
git clone https://github.com/kirolos136/devops-task.git
cd devops-task
cp .env.example .env
```

Then edit `.env` and set a real `POSTGRES_PASSWORD`. `.env` is gitignored and never committed.

```
PUBLIC_PORT=8090
POSTGRES_USER=barq_app
POSTGRES_DB=barq_tasks
POSTGRES_PASSWORD=<choose one>
DATABASE_URL=postgresql://barq_app:<same password>@postgres:5432/barq_tasks
REDIS_URL=redis://redis:6379/0
```

## Build and start

```bash
docker compose build
docker compose up -d
docker compose ps
```

Startup is ordered by health, not by container creation: PostgreSQL and Redis become healthy
first, then the application instances, then NGINX. Expect roughly 15 seconds.

## Stop

```bash
docker compose down          # keeps the volumes and the data
```

## Test

```bash
curl -s localhost:8090/                                        # app response
curl -s localhost:8090/health                                  # liveness, touches no dependency
curl -s localhost:8090/ready                                   # readiness, opens real connections
curl -s localhost:8090/instance                                # which backend served this
curl -s localhost:8090/counter                                 # Redis-backed counter
curl -s localhost:8090/records                                 # list records
curl -s -X POST localhost:8090/records \
  -H 'Content-Type: application/json' -d '{"title":"example"}'  # create a record
```

Load balancing across all three instances:

```bash
for i in $(seq 12); do curl -s localhost:8090/instance | grep -o '"instance_id":"[^"]*"'; done
```

## Validate

```bash
PUBLIC_PORT=8090 python3 validate.py ; echo "exit code: $?"
```

Twelve checks: public access, all six endpoints, dependency readiness, load balancing across
backends, network isolation, and that only NGINX publishes a host port. Bounded waits, PASS or
FAIL on every line, and a non-zero exit code on any failure.

## Failure test

```bash
PUBLIC_PORT=8090 python3 failure_test.py ; echo "exit code: $?"
```

Measures 20 requests per phase: a baseline, then with one backend stopped, then after recovery.
Reports how many succeeded, how many failed, and which instance served each request.

## Backup and restore

```bash
./backup.sh                                  # writes backups/barq-<timestamp>.sql
./restore.sh backups/barq-<timestamp>.sql    # restores that file
```

To prove a restore actually works, create a record after taking the backup and confirm it
disappears when the backup is restored:

```bash
./backup.sh
curl -s -X POST localhost:8090/records -H 'Content-Type: application/json' -d '{"title":"after backup"}'
./restore.sh backups/barq-<timestamp>.sql
curl -s localhost:8090/records        # "after backup" is gone, the earlier records are back
```

## Prove persistence

```bash
curl -s -X POST localhost:8090/records -H 'Content-Type: application/json' -d '{"title":"persists"}'
docker compose down
docker compose up -d
curl -s localhost:8090/records        # still there
```

Note the absence of `-v`. That flag deletes the volumes, which is the thing being proven.

## Cleanup

```bash
docker compose down                   # stop, keep data
docker compose down -v                # stop and DELETE all data. Not reversible.
docker image prune -f
```

---

# Answers to the brief's questions

## What failed first? What proved the cause? Which failed attempt taught you something?

The first failure was 3 seconds after the first `docker compose up`: the health check requested
`/healthz`, which the application does not implement, producing a 404 every 5 seconds and leaving
both application containers permanently unhealthy. The route list in `app/server.py` proved it —
the application implements `/health` and there is no `/healthz`.

The failed attempt that taught me most: `curl localhost:8080/` returned a connection reset, and I
concluded the application was refusing because it was bound to `127.0.0.1`. Two pieces of evidence
disproved that. `curl` reported `Connected` before failing, so the TCP connection to the host port
had succeeded. More conclusively, NGINX logs every request it receives, and there was no access-log
entry — the request never reached NGINX at all. The real cause was that Compose published to
container port 81 while NGINX listens on 80.

What changed in my thinking: in a chain of services a request dies at the *first* broken link, and
every fault behind it is invisible. I stopped treating "it fails" as one problem and started
fixing in order, re-testing after each step. Full write-up in Entry 2 of
[troubleshooting.md](troubleshooting.md).

## What patterns did the logs reveal? How did you avoid double-counting requests?

Three separate incidents in a 30-minute window, not one. One backend refusing connections for five
minutes, then two dependency outages (Redis, then PostgreSQL), then upstream timeouts affecting
both backends. Full detail in [log_analysis.md](log_analysis.md).

Double-counting was avoided by choosing the right file. `access.log` records one line per *client
request*; `application.log` records one line per *backend attempt*, so a retried request appears
twice there. The denominator is 720 distinct `request_id` values from `access.log`, after dropping
5 duplicate records and 1 malformed line. Counting `application.log` would have inflated the total
and counted retried-but-successful requests as failures.

## How do requests flow? Why these ports, networks and readiness checks?

A client reaches host port 8090, which is the only published port in the stack. Docker forwards it
to NGINX on container port 80. NGINX load-balances across the three application instances on the
`frontend` network. The instances reach PostgreSQL and Redis by service name on the `backend`
network, which is declared `internal: true`.

NGINX is on `frontend` only. It is the one component exposed to the outside world and therefore
the most likely to be compromised, so it has no route to the data layer at all. The applications
sit on both networks and are the only bridge. PostgreSQL and Redis publish no host ports, because
nothing outside Docker needs to reach them and every published port is attack surface.

`/health` and `/ready` are deliberately different. `/health` is liveness and touches no dependency.
`/ready` is readiness and opens real connections to PostgreSQL and Redis. If `/health` checked the
database, a database outage would make Docker believe the application had crashed and restart it —
which does not fix a database, and produces a restart loop.

## Why these timeouts, retries, restart settings and resource limits?

`max_fails=3 fail_timeout=10s`: three failures within ten seconds benches a backend for ten
seconds. Tolerates a brief blip without removing a healthy instance, while reacting to a real
failure within seconds. `proxy_next_upstream error timeout` retries a failed request on another
backend. Writes are deliberately *not* retried — NGINX excludes non-idempotent methods by default,
because a retried POST could create a record twice. A visible error is safer than a silent
duplicate.

`zone application_pool 64k` shares upstream state across NGINX worker processes. Without it each
worker keeps a private round-robin position and private failure counters, which broke load
balancing entirely and made `max_fails` far less sensitive than configured.

`restart: unless-stopped` rather than `always`, so a deliberate `docker compose stop` is respected
— which matters when stopping a backend on purpose during the failure test.

Resource limits were measured, not guessed: idle usage was recorded with `docker stats` (NGINX
14 MiB, Redis 8–10 MiB, PostgreSQL 35–38 MiB, each app 48–62 MiB) and limits set at roughly four to
eight times that. PostgreSQL gets the most because its idle figure understates it — `shared_buffers`
alone defaults to 128 MB. Full reasoning in [decisions.md](decisions.md).

## When should validation fail? What does green CI prove, or not prove?

Validation fails when any endpoint stops answering, when a dependency is unreachable, when traffic
stops being spread across backends, when NGINX can resolve `postgres` (isolation broken), or when
anything other than NGINX publishes a host port. It also fails if the stack does not become ready
within 90 seconds, so a broken stack fails the pipeline rather than hanging it.

Green CI proves the stack builds from a clean checkout, starts with no manual steps, answers all
six endpoints, load-balances, and holds its isolation and port rules — on a machine I have never
touched.

It does not prove the checks themselves are good ones, that the system survives load or time, that
anything works at real data volume, or that it recovers from failure — the failure test covers that
separately. CI is exactly as good as `validate.py`. A green tick is a statement about the tests,
not about the system.

CI runs on the default port 8080 rather than 8090, because the public port is a configuration
value and not a behaviour; `validate.py` reads it from the environment so the same script covers
both.

## Which single points of failure remain? How would you fix them in production?

Four remain:

1. **NGINX** — one instance, one published port. If it dies the whole system is unreachable.
2. **PostgreSQL** — one instance, no replica. Loss stops all reads and writes.
3. **Redis** — one instance. Loss stops the counter.
4. **A single Docker host** — every service runs on the same machine.

The application tier is *not* a single point of failure: three stateless instances, any one of
which can be lost without an outage, as demonstrated by the failure test.

I have identified these but I have not researched how to remedy them at production scale, and I
would rather say so than write remedies I cannot defend. The general direction in each case is
redundancy across separate machines, but I have not studied the specific mechanisms.

## What would you improve? How did you verify AI-assisted work?

The clearest remaining improvement is the one recorded as finding 3 in
[security_review.md](security_review.md): the application logs its full `DATABASE_URL`, password
included, on every startup. It is found and documented but not fixed. Logs are typically far more
widely readable than a repository, so this is the most durable form of the credential leak and it
should be closed before anything else.

Beyond that: move off Flask's development server, and derive resource limits from load testing
rather than from idle measurements plus headroom.

On verifying AI-assisted work: every fault in `troubleshooting.md` is backed by output from my own
terminal, quoted as it appeared, and anything I could not reproduce is marked unconfirmed rather
than asserted. Two corrections are worth naming. I rejected a suggestion to add speculative
`.gitignore` rules, then later found my own reasoning had rested on an assumption I had not
checked. And a log line pasted into `troubleshooting.md` as evidence still contained the database
password; my own repository scan caught it before the commit. The log analysis script and document
were written entirely by AI, which is stated plainly in [AI_USAGE.md](AI_USAGE.md).

---

# Evidence index

## Video chapters

```
00:00:00 - 00:00:15   intro
00:00:15 - 00:00:47   the repo
00:00:47 - 00:02:00   start the stack
00:02:00 - 00:05:00   the six endpoints
00:05:00 - 00:07:15   both backends
00:07:15 - 00:08:34   failure and recovery
00:08:34 - 00:09:35   data survives
00:09:35 - 00:14:11   validation, failure test and logs
00:14:11 - 00:20:30   find the fault and fix it
00:20:30 - 00:23:01   changing the port to 8090 and ran the validation script
00:23:01 - 00:32:30   adding the third instance
                      (00:25:46 - 00:31:43 forgetting to change the port from 8080 to 8090
                       in the loop that sends requests to /instance)
00:32:30 - 00:35:15   commit, push, apologise for the video length
```

## Requirement to evidence

| Requirement | Evidence | Video |
|---|---|---|
| AI disclosure stated up front | [AI_USAGE.md](AI_USAGE.md) | 00:00:00 - 00:00:15 |
| Baseline committed before any technical change | first commit in `git log --oneline` | 00:00:15 - 00:00:47 |
| Clean `git status` at the start | `git status` | 00:00:15 - 00:00:47 |
| Stack starts from stopped, health-gated ordering | `docker compose up -d`, `docker compose ps` | 00:00:47 - 00:02:00 |
| Only NGINX publishes a host port | PORTS column in `docker compose ps` | 00:00:47 - 00:02:00 |
| All six endpoints answer through NGINX | `curl` on `/`, `/health`, `/ready`, `/counter`, `/records` (POST and GET) | 00:02:00 - 00:05:00 |
| Distinct instance identities, load balanced | `/instance` loop | 00:05:00 - 00:07:15 |
| Stop one backend, show continued traffic, recover it | `docker compose stop app-02`, traffic, `docker compose start app-02` | 00:07:15 - 00:08:34 |
| A created record survives container recreation | POST, `docker compose down`, `up -d`, read back | 00:08:34 - 00:09:35 |
| Validation script: bounded waits, PASS/FAIL, non-zero exit | `python3 validate.py` | 00:09:35 - 00:14:11 |
| Failure test measuring traffic and errors | `python3 failure_test.py` | 00:09:35 - 00:14:11 |
| Network isolation proven | validation checks NGINX cannot resolve `postgres` while `app-01` can | 00:09:35 - 00:14:11 |
| One historical log finding demonstrated | `grep`/`cut`/`sort`/`uniq` on `logs/error.log`; full analysis in [log_analysis.md](log_analysis.md) | 00:09:35 - 00:14:11 |
| Challenge script run once, first time in this working copy | `./video_challenge.sh` | 00:14:11 - 00:20:30 |
| Fault diagnosed and fixed without a full-stack reset | `docker compose ps`, `/ready`, `/instance`, then `docker network connect` | 00:14:11 - 00:20:30 |
| Public port changed 8080 to 8090 live, NGINX proven on 8090 | `.env` edit, `docker compose up -d`, `curl localhost:8090` | 00:20:30 - 00:23:01 |
| Validation rerun after the port change | `PUBLIC_PORT=8090 python3 validate.py` | 00:20:30 - 00:23:01 |
| Third instance added live, all three respond | `docker-compose.yml` and `nginx/nginx.conf` edits, `docker compose restart nginx`, `/instance` loop | 00:23:01 - 00:32:30 |
| Validation rerun with three instances | `PUBLIC_PORT=8090 python3 validate.py` | 00:23:01 - 00:32:30 |
| `git status` and `git diff` explained, committed on screen, hashes shown | `git status`, `git diff`, `git commit`, `git log --oneline` | 00:32:30 - 00:35:15 |
| Video commits pushed | `git push` | 00:32:30 - 00:35:15 |
| Investigation journal with hypotheses and failed attempts | [troubleshooting.md](troubleshooting.md), 27 findings, 9 full entries | repository |
| Log analysis, all ten questions | [log_analysis.md](log_analysis.md), produced by `scripts/analyze_logs.py` | repository |
| Technical decisions, minimum five | [decisions.md](decisions.md), 14 decisions | repository |
| Security and production review, minimum eight | [security_review.md](security_review.md), 13 findings | repository |
| Backup and proven restore | `backup.sh`, `restore.sh`; a record created after the backup disappears on restore | repository, not filmed |
| CI on push and pull request | [.github/workflows/ci.yml](.github/workflows/ci.yml) | repository |
| Architecture diagram | [architecture.png](architecture.png) | repository |

## Note on the recording

The video runs to 35 minutes rather than the 12 to 18 the brief asks for, and the overrun is
apologised for on camera at the end. Two things caused it. Diagnosing the challenge fault took
around six minutes (00:14:11 - 00:20:30). Then, after changing the public port to 8090, I kept
sending requests to 8080 in the `/instance` loop and spent roughly six minutes
(00:25:46 - 00:31:43) restarting services and editing `nginx.conf` before noticing the port in my
own command was wrong. Both are visible in the recording. Neither was edited out.

## Note on commits after the recording

Every commit dated after the recording is documentation only, with one exception. The exception is
a one-line change to `failure_test.py`: its baseline check required exactly two backends, which CI
failed once the third instance was added. It now accepts two or more. No service configuration,
image or network setting changed after the video.
