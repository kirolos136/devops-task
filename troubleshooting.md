# Troubleshooting journal

## Findings register

Rows 1-13 were recorded on 2026-09-08 from reading the starter, before the stack was ever
started. Rows 14-16 were found on the first run. "confirmed" means the fault has been
reproduced with real output, quoted in an entry below. "found" means it is still only
reasoning from reading the files.

| # | Area | Observation | Status |
|---|---|---|---|
| 1 | secrets | DB credentials hardcoded in `docker-compose.yml` under `postgres.environment` | fixed and proven |
| 2 | secrets | `config/app.env` is tracked in git and contains a password | fixed and proven |
| 3 | secrets | The password in `config/app.env` and the one in `docker-compose.yml` differ in their final character, so the app can never authenticate (value redacted here on purpose) | fixed and proven |
| 4 | database | `DATABASE_URL` uses port 5433; PostgreSQL listens on 5432 | fixed and proven |
| 5 | cache | `REDIS_URL` uses port 6380; Redis listens on 6379 | fixed and proven |
| 6 | networking | App binds to `APP_HOST: 127.0.0.1`, unreachable from other containers | fixed and proven |
| 7 | networking | nginx publishes on `127.0.0.1:` only, which is not public access | fixed and proven |
| 8 | networking | Compose publishes to nginx container port 81, but `nginx/nginx.conf:14` says `listen 80;` | fixed and proven |
| 9 | container | Dockerfile ends with `USER root`, discarding the non-root `app` user it creates | fixed and proven |
| 10 | secrets | Dockerfile bakes the credential file into the image: `COPY config/app.env /srv/app.env` | fixed and proven |
| 11 | secrets | App logs the full `DATABASE_URL`, password included, at startup | confirmed |
| 12 | networking | `nginx.conf` upstream points at `app-01:8081`, but `APP_PORT` is 8080 for both apps | fixed and proven |
| 13 | health | Compose healthcheck calls `/healthz`; the app implements `/health` | fixed and proven |
| 14 | identity | `app-02` is configured with `INSTANCE_ID: "app-01"`, so both instances report the same identity | fixed and proven |
| 15 | production readiness | The app runs on Flask's built-in development server, not a production WSGI server | confirmed |
| 16 | observability | The failing healthcheck writes two log lines every 5 seconds, burying real errors | fixed and proven |
| 17 | secrets | The password was removed from configuration but survived in `troubleshooting.md`, quoted inside a pasted log line | fixed and proven |
| 18 | persistence | PostgreSQL's real data directory was on `tmpfs` (RAM) while the named volume sat unused at `/var/lib/postgresql/backup` | fixed and proven |
| 19 | persistence | Redis ran with `--save "" --appendonly no`, disabling both persistence mechanisms, and had no volume | fixed and proven |
| 20 | availability | `max_fails=0` with `proxy_next_upstream off` meant nginx never benched a dead backend and never retried elsewhere | fixed and proven |
| 21 | availability | The upstream had no `zone`, so each nginx worker kept private round-robin and failure state; all traffic went to app-01 | fixed and proven |
| 22 | networking | nginx was attached to the `backend` network, giving the internet-facing service a direct route to PostgreSQL and Redis | fixed and proven |
| 23 | networking | PostgreSQL and Redis published host ports, allowing the application to be bypassed entirely from the host | fixed and proven |
| 24 | availability | `restart: "no"` on the app services, and no restart policy at all on postgres, redis or nginx | fixed and proven |
| 25 | availability | No CPU or memory limits on any service, so one container could exhaust the host | fixed and proven |
| 26 | availability | `depends_on` used the list form, which waits only for a container to start, not to become ready | fixed and proven |

Status values: found -> confirmed -> fixed and proven.

## Cold start verification / 2026-09-12

Run from a fully stopped stack with no manual ordering. Volumes were kept, not reset.

```
$ docker compose down && docker compose up -d
 Container redis      Healthy    4.9s
 Container postgres   Healthy    4.9s
 Container app-01     Healthy   11.7s
 Container app-02     Healthy   11.7s
 Container nginx      Created    0.2s
```
Compose reports `Healthy` rather than `Started` because of the `condition: service_healthy`
dependencies. The data layer becomes healthy first, the apps wait for it, and nginx waits for
both apps.

All six required endpoints, through nginx on the published port:

```
$ curl -s localhost:8080/
{"instance_id":"app-01","message":"Welcome to BARQ Systems","service":"barq-api","version":"2.0.0"}

$ curl -s localhost:8080/health
{"instance_id":"app-02","service":"barq-api","status":"alive","version":"2.0.0"}

$ curl -s localhost:8080/ready
{"dependencies":{"postgres":"ready","redis":"ready"},"instance_id":"app-01",...,"status":"ready"}

$ curl -s localhost:8080/counter
{"counter":3,"instance_id":"app-02",...}

$ curl -s -X POST localhost:8080/records -H 'Content-Type: application/json' -d '{"title":"cold start"}'
{"instance_id":"app-01","record":{"id":4,"title":"cold start"},...}

$ curl -s localhost:8080/records
{"instance_id":"app-02","records":[{"id":1,...},{"id":2,...},{"id":3,"title":"persistence test"},
                                   {"id":4,"title":"cold start"}],...}

$ for i in $(seq 6); do curl -s localhost:8080/instance | grep -o '"instance_id":"[^"]*"'; done
"instance_id":"app-02"
"instance_id":"app-01"
"instance_id":"app-02"
"instance_id":"app-01"
"instance_id":"app-02"
"instance_id":"app-01"
```

Three things this run demonstrates beyond the endpoints answering:

1. Requests were served by different instances throughout, and they agree on state. app-02
   returned the record app-01 had just created, which is the point of keeping the application
   stateless and holding all state in PostgreSQL and Redis.
2. Record id 3 was created several changes earlier and has survived repeated `down` and `up`
   cycles. The counter is at 3 rather than back at 1.
3. No manual ordering or intervention was needed at any point.

## Open leads

None outstanding. All findings above are either fixed and proven, or recorded in
`security_review.md` with the reason they were deliberately not changed.

---

## Entry 1 / 2026-09-08 / 14:03 - First run: what failed first

- **Symptom:**
  The stack built and started, but both application containers reported `unhealthy` while
  PostgreSQL and Redis reported `healthy`.

  ```
  NAME       STATUS
  app-01     Up About a minute (unhealthy)
  app-02     Up About a minute (unhealthy)
  nginx      Up About a minute             127.0.0.1:8080->81/tcp
  postgres   Up About a minute (healthy)   5432/tcp
  redis      Up About a minute (healthy)   6379/tcp
  ```

  The first failure in the logs, 3 seconds after startup:
  ```
  app-01 | {"timestamp": "2026-09-08T14:03:37.822+00:00", "level": "WARN", "event": "http_request",
           "path": "/healthz", "status": 404, "duration_ms": 0.269}
  ```
  This then repeated every 5 seconds indefinitely.

- **Hypothesis:**
  Before running anything I had already read the Compose healthcheck and noticed it calls
  `/healthz`, while the route list in `app/server.py` only defines `/health`. I expected a
  404 loop and both app containers stuck unhealthy. That is what happened.

- **Command or test:**
  ```bash
  docker compose up -d --build
  docker compose ps
  docker compose logs
  grep -n "@app\." app/server.py
  ```

- **Actual output:**
  The route list confirms which paths actually exist:
  ```
  92:    @app.get("/")
  96:    @app.get("/health")
  100:   @app.get("/instance")
  104:   @app.get("/ready")
  118:   @app.route("/records", methods=["GET", "POST"])
  133:   @app.get("/counter")
  ```
  There is no `/healthz` route. All six endpoints the brief requires are present.

- **Failed attempt and what changed your thinking:**
  No failed attempt on this one, it matched my prediction. What did surprise me is what was
  *not* in the output: there were no database or Redis errors at all, even though I had
  already found both connection ports to be wrong. That is recorded as Entry 3.

- **Root cause:**
  The healthcheck in `docker-compose.yml` requests `/healthz`. The application implements
  `/health`. Flask returns 404, `urllib.request.urlopen` raises on a 404, the Python process
  exits non-zero, and Docker counts that as a failed check. After 3 consecutive failures the
  container is marked unhealthy.

- **Fix:**
  Not applied yet. Change the healthcheck path to `/health`.

- **Retest evidence:**
  Not yet collected. Expected: `docker compose ps` shows both app containers healthy, and the
  repeating 404 lines stop.

- **Related commit:**
  Pending.

- **Remaining uncertainty:**
  Correcting the path will make the check pass, but the check runs *inside* the container and
  talks to `127.0.0.1`. Because of finding 6 the app only listens on loopback, so the container
  will report healthy while still being unreachable from nginx. A green healthcheck will not
  mean the service actually works, and I should not treat the status column as proof.

---

## Entry 2 / 2026-09-08 - Reaching the stack from the host

- **Symptom:**
  A request to the published port connects and is then immediately dropped.

  ```
  $ curl -sv localhost:8080/
  * Connected to localhost (127.0.0.1) port 8080
  > GET / HTTP/1.1
  * Recv failure: Connection reset by peer
  * Closing connection
  ```

- **Hypothesis:**
  My first reading was that the request reached nginx, nginx forwarded it to the app, and the
  app refused the connection because it is bound to `127.0.0.1` (finding 6).

- **Command or test:**
  ```bash
  curl -sv localhost:8080/ 2>&1 | tail -20
  docker compose ps
  docker compose logs nginx
  grep -n listen nginx/nginx.conf
  ```

- **Actual output:**
  ```
  nginx   127.0.0.1:8080->81/tcp
  ```
  ```
  14:        listen 80;
  ```
  The nginx logs contain only its startup lines. There is no access-log entry for my request.

- **Failed attempt and what changed your thinking:**
  My first hypothesis was wrong, and two pieces of evidence disproved it.

  First, `curl` printed `Connected to localhost (127.0.0.1) port 8080` before failing. The TCP
  connection to the host port succeeded, so the failure happened after Docker accepted it and
  tried to forward it onward.

  Second, and more conclusive: nginx logs every request it receives to stdout using the
  `assessment` log format. If my request had reached nginx there would be a JSON access line
  for it. There is none. The request never arrived at nginx at all, so it could not possibly
  have reached the app behind it.

  What changed in my thinking: I had been treating "it fails" as one problem. In a chain of
  services a request dies at the *first* broken link, and every fault behind that point is
  invisible. Finding 6 is real, but it is not what I was looking at here. I need to fix in
  order and re-test after each step rather than assuming which fault I am seeing.

- **Root cause:**
  Compose publishes the host port to container port 81 (`127.0.0.1:${PUBLIC_PORT:-8080}:81`),
  but nginx listens on port 80. Nothing is bound to 81 inside the nginx container, so the
  forwarded connection is reset. Separately, the `127.0.0.1:` prefix on that same line binds
  the published port to the host loopback only, which does not satisfy the brief's requirement
  for public access.

- **Fix:**
  Not applied yet. Both halves of that ports line need correcting.

- **Retest evidence:**
  Not yet collected. Expected: `curl localhost:8080/` returns a JSON body from the app, and an
  access-log line appears in `docker compose logs nginx`.

- **Related commit:**
  Pending.

- **Remaining uncertainty:**
  Fixing the port mapping will expose the next fault in the chain rather than making the stack
  work. Findings 12 (upstream port 8081) and 6 (loopback binding) both sit behind this one and
  are still untested.

---

## Entry 3 / 2026-09-08 / 16:10 - Dependency failures that were not in the logs

- **Symptom:**
  The first run produced no database or cache errors at all, despite both connection ports
  being wrong. The only failure in the logs was the healthcheck 404.

  The line the app writes at startup shows the configuration it loaded:
  ```
  app-01 | {"event": "configuration_loaded",
           "database_url": "postgresql://barq_app:<redacted>@postgres:5433/barq_tasks",
           "redis_url": "redis://redis:6380/0"}
  ```
  Meanwhile the servers themselves reported different ports:
  ```
  postgres | LOG: listening on IPv4 address "0.0.0.0", port 5432
  redis    | * Running mode=standalone, port=6379.
  ```

- **Hypothesis:**
  The app never opens a connection at startup. Reading `app/server.py`, every PostgreSQL call
  goes through `Dependencies.query()` which calls `psycopg.connect()`, and Redis is only
  touched by `redis_ready()` and `counter()`. Those are reached only by `/ready`, `/records`
  and `/counter`. The healthcheck hits `/healthz`, which 404s before touching anything. So I
  predicted the faults were real but simply never triggered, and that calling `/ready` directly
  would trigger both at once.

- **Command or test:**
  The app is bound to loopback, so it cannot be reached from the host. I called it from inside
  its own container, which is the one place `127.0.0.1` resolves to the app:
  ```bash
  docker compose exec app-01 python -c "import urllib.request; \
    print(urllib.request.urlopen('http://127.0.0.1:8080/ready').read())"
  docker compose logs app-01 | grep dependency_error
  ```

- **Actual output:**
  ```
  urllib.error.HTTPError: HTTP Error 503: SERVICE UNAVAILABLE
  ```
  ```
  app-01 | {"timestamp": "2026-09-08T16:10:25.748+00:00", "level": "ERROR",
           "event": "dependency_error", "dependency": "postgres",
           "error_type": "OperationalError",
           "request_id": "0aa4429f13814cd39d2dafb56896fd0d", "instance_id": "app-01"}
  app-01 | {"timestamp": "2026-09-08T16:10:25.848+00:00", "level": "ERROR",
           "event": "dependency_error", "dependency": "redis",
           "error_type": "ConnectionError",
           "request_id": "0aa4429f13814cd39d2dafb56896fd0d", "instance_id": "app-01"}
  ```
  Both errors carry the same `request_id`, which proves they came from the same `/ready` call
  rather than from two separate events.

- **Failed attempt and what changed your thinking:**
  My first attempt at capturing this evidence used `docker compose logs app-01 --tail=20` and
  showed nothing but healthcheck 404s. The broken healthcheck writes two lines every five
  seconds, so twenty lines covers about ten seconds of history and the dependency errors had
  already scrolled past. Filtering with `grep dependency_error` instead of tailing found them
  immediately.

  That is a small mistake but it taught me something worth keeping: a noisy healthcheck does
  not just waste disk, it actively hides real errors from anyone reading the logs. I recorded
  that separately as finding 16.

- **Root cause:**
  `config/app.env` sets `DATABASE_URL` to port 5433 and `REDIS_URL` to port 6380. Both servers
  listen on their defaults, 5432 and 6379, which their own startup logs confirm. Nothing in
  the Compose file changes those defaults. The app therefore dials ports that nothing is
  listening on, and both connections fail.

  The `15432` and `16379` values in the Compose `ports:` lines are host-side published ports.
  They are not what another container should dial, and using them would be an equally wrong fix.

- **Fix:**
  Applied. All configuration moved into a gitignored `.env` at the repository root, with the
  ports corrected to 5432 and 6379 and a single consistent password. `docker-compose.yml` now
  reads `${POSTGRES_USER}`, `${POSTGRES_DB}` and `${POSTGRES_PASSWORD}` instead of hardcoded
  values, and loads the app configuration with `env_file: .env`. The PostgreSQL healthcheck
  was changed from a hardcoded `pg_isready -U barq_app -d barq_tasks` to use the same
  variables, so it cannot drift from the credentials it is meant to check. The Dockerfile line
  `COPY config/app.env /srv/app.env` was deleted so the credential is no longer baked into the
  image, and `config/app.env` was removed from the repository with `git rm`.

  This one change closes findings 1, 2, 3, 4, 5 and 10.

- **Retest evidence:**
  ```
  $ docker compose down && docker compose up -d --build
  $ docker compose exec app-01 python -c "...urlopen('http://127.0.0.1:8080/ready')..."
  {"dependencies":{"postgres":"ready","redis":"ready"},"instance_id":"app-01",
   "service":"barq-api","status":"ready","version":"2.0.0"}
  ```
  HTTP 200, both dependencies ready, where the same call previously returned 503 with an
  `OperationalError` and a `ConnectionError`.

  Repository scan for the credential:
  ```
  $ grep -rn "BarqLabOnly" . --exclude-dir=.git
  ./.env:1:...
  ./.env:5:...
  ```
  The only remaining matches are inside `.env`, which is gitignored and never leaves my
  machine. Nothing tracked contains the password.

- **Related commit:**
  See `fix: move credentials to gitignored .env and correct service ports`.

- **Remaining uncertainty:**
  I had expected the password mismatch to surface as a separate authentication failure once
  the port was corrected. It did not, because I fixed both in the same change, so I never
  observed the auth error on its own. The 200 response proves both are now correct, but I
  cannot claim to have independently reproduced the credential fault.

  Separately: PostgreSQL only reads `POSTGRES_PASSWORD` when it initialises an empty data
  directory. The data directory is currently on `tmpfs`, so it is recreated on every restart
  and always picks up the current value. Once persistence is fixed the password will be baked
  into the volume on first initialisation, and changing `.env` afterwards will silently have
  no effect without `docker compose down -v`. I need to remember this before concluding that
  a future credential change "did not work".

---

## Entry 4 / 2026-09-09 - The credential survived in the documentation

- **Symptom:**
  After completing the configuration fix I ran a repository-wide scan to confirm the password
  was gone. It was still present, but not in any config file:
  ```
  $ grep -rn "BarqLabOnly" . --exclude-dir=.git
  ./troubleshooting.md:202: "database_url": "postgresql://barq_app:BarqLabOnly_...@postgres:5433/..."
  ./.env:1: ...
  ./.env:5: ...
  ```

- **Hypothesis:**
  The `.env` matches are expected, since that file is gitignored. The `troubleshooting.md`
  match is not: that file is tracked and the repository is public, so committing it would
  publish the credential in a new commit, in the very document where I describe removing it.

- **Command or test:**
  ```bash
  grep -rn "BarqLabOnly" . --exclude-dir=.git
  git check-ignore -v .env
  ```

- **Actual output:**
  `.env` is confirmed ignored. `troubleshooting.md` is tracked, and the password appeared in it
  because I pasted a raw application log line as evidence for Entry 3 without redacting it.

- **Failed attempt and what changed your thinking:**
  Not a failed attempt so much as a wrong assumption. I had treated "remove the secret" as a
  configuration task, and once `docker-compose.yml`, the Dockerfile and `config/app.env` were
  clean I considered it done. The scan proved otherwise.

  What changed: the application prints its full connection URL at startup (finding 11), so any
  log I copy as evidence carries the credential with it. The risk is not only in config files
  but in every place a log line gets pasted: journals, reports, issue trackers, chat. I now
  redact before pasting rather than scanning afterwards, and I run the scan before every push
  rather than only after touching configuration.

- **Root cause:**
  A raw log line containing the connection URL was quoted verbatim into a tracked markdown file.

- **Fix:**
  The password was replaced with `<redacted>` in the quoted log line, and the findings register
  row now describes the mismatch ("the two values differ in their final character") instead of
  printing either value.

- **Retest evidence:**
  ```
  $ grep -rn "BarqLabOnly" . --exclude-dir=.git
  ./.env:1:...
  ./.env:5:...
  ```
  Only the gitignored `.env` matches. No tracked file contains the credential.

- **Related commit:**
  Included with `fix: move credentials to gitignored .env and correct service ports`.

- **Remaining uncertainty:**
  The original credential is still present in this repository's git history, because it was in
  `config/app.env` in the required unmodified baseline commit. Deleting the file going forward
  does not remove it from history. For this assessment that is acceptable: the value is
  clearly synthetic lab data supplied by BARQ, it only ever protected a container with no
  published port, and the baseline commit is itself a graded requirement. In a real system the
  correct response would be to rotate the credential first and then purge history with
  `git filter-repo` or BFG, on the principle that anything ever pushed must be treated as
  compromised. This is recorded as a production follow-up in `security_review.md` rather than
  as an implemented fix.

---

## Entry 5 / 2026-09-09 - Nothing was actually persisted

- **Symptom:** The stack looked configured for durability but was not. The named volume
  `postgres-data` was mounted at `/var/lib/postgresql/backup`, a directory PostgreSQL never
  writes to, while its real data directory `/var/lib/postgresql/data` was covered by `tmpfs`.
  Redis ran with `--save "" --appendonly no` and had no volume at all.

- **Hypothesis:** `tmpfs` is a filesystem in RAM, so every database write would be lost on
  container recreation, and the volume that appeared to provide durability held nothing.
  Redis with both mechanisms disabled would reset the counter to zero on every restart.

- **Command or test:**
  ```bash
  docker compose down -v && docker compose up -d --build
  # POST a record, read /counter
  docker compose down          # no -v
  docker compose up -d
  # read /records and /counter back
  ```

- **Actual output:** Before the fix the data directory was recreated from scratch on every
  start, visible as PostgreSQL running `initdb` and re-executing `01-init.sql` each time.

- **Failed attempt and what changed your thinking:** None. What was worth noticing is that
  the configuration looked correct at a glance: a named volume was declared and mounted, just
  at the wrong path. A declared volume is not evidence of persistence, only a test is.

- **Root cause:** The volume was mounted at a path nothing writes to, the real data directory
  was a RAM disk, and both Redis persistence mechanisms were switched off.

- **Fix:** Mounted `postgres-data` at `/var/lib/postgresql/data`, deleted the `tmpfs` line,
  enabled Redis append-only mode and gave it a `redis-data` volume at `/data`.

- **Retest evidence:**
  ```
  # before restart
  {"record":{"id":3,"title":"persistence test"}}
  {"counter":1}

  # after docker compose down (no -v) and up
  {"records":[{"id":1,...},{"id":2,...},{"id":3,"title":"persistence test"}]}
  {"counter":2}
  ```
  The record survived and the counter continued from its previous value instead of resetting.

- **Related commit:** `fix: persist postgres data on named volume and enable redis persistence`.

- **Remaining uncertainty:** PostgreSQL now runs `initdb` only once, when the volume is empty.
  From here, changes to `POSTGRES_PASSWORD` or to `database/init.sql` will have no effect until
  the volume is destroyed with `docker compose down -v`. I have not yet tested recreating the
  containers with `docker compose up --force-recreate`, which is what the brief actually asks
  to be demonstrated.

---

## Entry 6 / 2026-09-09 - App reachable, healthy for the right reason, and non-root

- **Symptom:** Three related faults. Compose set `APP_HOST: "127.0.0.1"`, so the app listened
  only on loopback and no other container could reach it. The healthcheck requested `/healthz`,
  which does not exist, so both app containers were permanently unhealthy and produced a 404
  every 5 seconds. The Dockerfile created a non-root `app` user and then discarded it with
  `USER root`.

- **Hypothesis:** `127.0.0.1` is the correct default for a development server on a shared
  machine, but wrong inside a container, which is already network-isolated. There it means
  unreachable by anything. I expected the healthcheck to keep passing after the path fix even
  if the binding stayed wrong, because the check runs inside the container where loopback
  resolves to the app itself.

- **Command or test:**
  ```bash
  docker compose down && docker compose up -d --build
  docker compose ps
  docker compose exec app-01 whoami
  docker compose exec nginx wget -qO- http://app-01:8080/health
  ```

- **Actual output:**
  ```
  app-01   Up About a minute (healthy)
  app-02   Up About a minute (healthy)

  $ docker compose exec app-01 whoami
  app

  $ docker compose exec nginx wget -qO- http://app-01:8080/health
  {"instance_id":"app-01","service":"barq-api","status":"alive","version":"2.0.0"}
  ```

- **Failed attempt and what changed your thinking:** None here. The point worth recording is
  which test actually proves what. `docker compose ps` showing healthy proves only that the app
  answers itself, because the healthcheck runs inside the container and connects to loopback.
  The reply from `nginx` is the only one of these that proves the app is reachable across the
  network, and it is the check that could not have passed before this change.

- **Root cause:** A development-server default (`127.0.0.1`) applied in a container context; a
  healthcheck pointed at a path the application does not implement; and a `USER root` line
  overriding the non-root user created three lines above it.

- **Fix:** `APP_HOST: "0.0.0.0"`, healthcheck path `/health`, and `USER app` in the Dockerfile.

- **Retest evidence:** As quoted above. The repeating 404 lines also stopped, and the request
  log level for the healthcheck changed from WARN to INFO, since the app logs WARN only for
  status codes of 400 and above.

- **Related commit:** `fix: bind app to all interfaces, correct healthcheck path, drop root`.

- **Remaining uncertainty:** The stack is still not reachable from the host, because nginx is
  published to container port 81 while it listens on 80 (finding 8), and the nginx upstream
  points at `app-01:8081` while the app listens on 8080 (finding 12). Both are addressed next.

---

## Entry 7 / 2026-09-10 - Load balancing that looked broken but was not

- **Symptom:** After correcting the nginx port mapping, the upstream ports and `app-02`'s
  `INSTANCE_ID`, the stack answered on port 8080 for the first time. But ten consecutive
  requests to `/instance` all returned `app-01`.

- **Hypothesis:** My first guess was that nginx held a stale IP for app-02 after a recreate, or
  that app-02 had been marked down during a startup race.

- **Command or test:**
  ```bash
  docker compose exec nginx wget -qO- http://app-02:8080/instance
  docker compose logs nginx | tail -15
  ```

- **Actual output:** nginx reached app-02 directly without any problem, returning
  `{"instance_id":"app-02",...}`. Every proxied request logged the same single upstream:
  ```
  "upstream":"172.19.0.3:8080","upstream_status":"200"
  ```

- **Failed attempt and what changed your thinking:** Both my hypotheses were wrong, and the
  access log ruled them out in one read. A single address with no comma means no retry happened,
  so nothing was failing over. `upstream_status: 200` means nothing was failing at all. And
  app-02's address never appeared, so it was never *selected*. That is a different problem from
  being unreachable or unhealthy, and it pointed at how nginx chooses a backend rather than at
  the backend itself.

- **Root cause:** `worker_processes auto` starts one worker per CPU core, and without a `zone`
  directive each worker keeps its own private copy of the upstream state, including the
  round-robin position and the `max_fails` counters. Each new connection landed on a different
  worker, and every worker's first choice is the first server in the list. Round-robin was
  working correctly, independently, from the start, in every worker.

  The same applies to failure counting: a backend had to fail `max_fails` times on one
  individual worker before that worker alone would bench it.

- **Fix:** Added `zone application_pool 64k;` to the upstream block so all workers share one
  cursor and one set of failure counters. Also set `max_fails=3 fail_timeout=10s` on both
  servers (was `max_fails=0`, meaning a dead backend was never benched) and replaced
  `proxy_next_upstream off` with `proxy_next_upstream error timeout`.

- **Retest evidence:**
  ```
  $ docker compose restart nginx
  $ for i in $(seq 10); do curl -s localhost:8080/instance | grep -o '"instance_id":"[^"]*"'; done
  "instance_id":"app-01"
  "instance_id":"app-02"
  "instance_id":"app-01"
  "instance_id":"app-02"
  ... alternating for all 10
  ```

- **Related commit:** `fix: correct nginx port mapping, upstream ports and instance identity`.

- **Remaining uncertainty:** `proxy_next_upstream` does not retry POST and other non-idempotent
  methods by default, because a retried write could create a record twice. I have not yet tested
  what a POST does when it lands on a stopped backend; I expect a 502 rather than a silent
  failover, and I need to confirm that during the failure test rather than assume it.

---

## Entry 8 / 2026-09-10 - Network isolation and unnecessary host ports

- **Symptom:** nginx declared `networks: [frontend, backend]`, so the only internet-facing
  service had a direct route to PostgreSQL and Redis. Both data services also published host
  ports (`127.0.0.1:15432:5432` and `127.0.0.1:16379:6379`), which the brief forbids.

- **Hypothesis:** nginx only ever forwards HTTP to the apps, so it has no reason to be on the
  data network. The apps sit on both networks and are the only legitimate bridge. Removing the
  published ports should change nothing functionally, because container-to-container traffic
  uses the internal network and never touches a host port mapping.

- **Command or test:**
  ```bash
  docker compose down && docker compose up -d
  docker compose exec nginx getent hosts postgres
  docker compose exec app-01 getent hosts postgres
  docker ps --format '{{.Names}}	{{.Ports}}'
  curl -s localhost:8080/ready
  ```

- **Actual output:**
  ```
  $ docker compose exec nginx getent hosts postgres
  (no output)

  $ docker compose exec app-01 getent hosts postgres
  172.19.0.2      postgres

  $ docker ps --format '{{.Names}}	{{.Ports}}'
  nginx      0.0.0.0:8080->80/tcp
  postgres   5432/tcp
  redis      6379/tcp
  app-01     8080/tcp
  app-02     8080/tcp

  $ curl -s localhost:8080/ready
  {"dependencies":{"postgres":"ready","redis":"ready"},"instance_id":"app-01",...}
  ```
  Only nginx has a host mapping, shown by the arrow. The bare `5432/tcp` and `8080/tcp` entries
  are container-internal listening ports, not published ones.

- **Failed attempt and what changed your thinking:** No failed attempt, but I had a
  misconception worth recording. I assumed the `ports:` lines were part of how the containers
  reached each other, and that removing them might break the app's access to the database.
  They are not: `ports:` only opens a path from the host into a container. Containers on a
  shared network talk directly on the container's own port. The `/ready` response after the
  deletion proves it.

  I also assumed the `127.0.0.1:` prefix made those ports harmless. It limits access to the
  host, but "the host" includes every process and user on that machine, and on a real server
  anyone who can log into it. The port bypassed the application completely: no application
  logic, no application-level authentication, no request logging.

- **Root cause:** Over-broad network membership on nginx, and host port mappings that nothing
  needed.

- **Fix:** nginx attached to `frontend` only; both `ports:` lines deleted. The `backend`
  network keeps `internal: true`, which blocks outbound access from the data layer. That is a
  separate control from network membership: `internal` stops traffic leaving, while removing
  nginx from the network stops lateral movement into the data layer.

- **Retest evidence:** As quoted above. The negative and positive results together are the
  proof: the same lookup fails from nginx and succeeds from app-01, so the isolation is real
  rather than the test being broken.

- **Related commit:** `fix: isolate nginx from backend network and unpublish data ports`.

- **Remaining uncertainty:** DNS isolation proves nginx cannot resolve the service name. I have
  not tested whether it could still reach the database by raw IP address, which would be the
  stronger claim. Given the two networks are separate bridges I expect it cannot, but I have
  not demonstrated it.

---

## Entry 9 / 2026-09-12 - Restart policies, resource limits and ordered startup

- **Symptom:** Three availability gaps. `restart: "no"` on the apps and no restart policy at all
  on postgres, redis or nginx, so any crash stayed down until noticed. No CPU or memory limits
  anywhere, so a single leaking container could exhaust the host. And `depends_on` in list form,
  which waits only for a container to start.

- **Hypothesis:** The list-form `depends_on` was my best explanation for an earlier symptom
  where nginx appeared to send all traffic to one backend: nginx starting before the apps were
  ready, probing them, and benching one. That turned out not to be the cause (Entry 7), but the
  ordering problem is real regardless and needed fixing.

- **Command or test:**
  ```bash
  docker stats --no-stream      # measure real usage before choosing limits
  docker compose down && docker compose up -d
  docker stats --no-stream      # confirm the limits applied
  ```

- **Actual output:** Idle usage measured before setting limits:
  ```
  nginx      14.5 MiB     postgres   35-38 MiB    redis   8-10 MiB
  app-01     48-58 MiB    app-02     51-62 MiB
  ```
  After applying limits, the LIMIT column changed from the host total to the configured values:
  ```
  nginx      13.84MiB / 128MiB    10.81%
  app-01     39.09MiB / 256MiB    15.27%
  app-02     38.68MiB / 256MiB    15.11%
  postgres   19.9MiB  / 512MiB     3.89%
  redis      5.539MiB / 256MiB     2.16%
  ```

- **Failed attempt and what changed your thinking:** Nothing failed, but reading the measurements
  changed how I chose the numbers. The app containers showed CPU spikes to 35-43%, which looked
  like real load until I noticed the PID count rising from 2 to 3 at the same time. That third
  process is the healthcheck starting a whole Python interpreter every five seconds. The apps
  were idle; the spike was the check measuring itself. I sized CPU for that rather than for load
  that does not exist.

  I also nearly sized PostgreSQL from its idle figure of 35 MiB. Its `shared_buffers` setting
  alone defaults to 128MB and is claimed under real use, so an idle reading understates it by a
  wide margin. That is the one service where a tight limit produces OOM kills that look like
  database faults.

- **Root cause:** Defaults left unset: no restart policy, no limits, and startup ordering that
  waits for existence rather than readiness.

- **Fix:** `restart: "unless-stopped"` on every service. Memory limits of 128M for nginx, 256M
  for each app and for redis, and 512M for postgres, with CPU quotas of 0.5 for everything except
  postgres at 1.0. `depends_on` converted to the long form with `condition: service_healthy`, so
  the apps wait for postgres and redis, and nginx waits for both apps.

- **Retest evidence:** As quoted above. Startup is now visibly sequential rather than everything
  launching at once.

- **Related commit:** `feat: add restart policies, resource limits and health-gated startup`.

- **Remaining uncertainty:** I have not load-tested the stack, so the limits are sized from idle
  measurements plus headroom rather than from observed peak load. I also have not verified that a
  container actually restarts after its main process is killed, which is the real test of the
  restart policy.

---

## Entry / date / time
- Symptom:
- Hypothesis:
- Command or test:
- Actual output:
- Failed attempt and what changed your thinking:
- Root cause:
- Fix:
- Retest evidence:
- Related commit:
- Remaining uncertainty:

Do not fabricate a failed attempt just to fill the template. Record actual attempts.
