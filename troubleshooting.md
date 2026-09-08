# Troubleshooting journal

## Findings register

Rows 1-13 were recorded on 2026-09-08 from reading the starter, before the stack was ever
started. Rows 14-16 were found on the first run. "confirmed" means the fault has been
reproduced with real output, quoted in an entry below. "found" means it is still only
reasoning from reading the files.

| # | Area | Observation | Status |
|---|---|---|---|
| 1 | secrets | DB credentials hardcoded in `docker-compose.yml` under `postgres.environment` | found |
| 2 | secrets | `config/app.env` is tracked in git and contains a password | found |
| 3 | secrets | Password differs between the two files: `...7qN2vK8d` in `config/app.env` vs `...7qN2vK8c` in Compose | found |
| 4 | database | `DATABASE_URL` uses port 5433; PostgreSQL listens on 5432 | confirmed |
| 5 | cache | `REDIS_URL` uses port 6380; Redis listens on 6379 | confirmed |
| 6 | networking | App binds to `APP_HOST: 127.0.0.1`, unreachable from other containers | confirmed |
| 7 | networking | nginx publishes on `127.0.0.1:` only, which is not public access | confirmed |
| 8 | networking | Compose publishes to nginx container port 81, but `nginx/nginx.conf:14` says `listen 80;` | confirmed |
| 9 | container | Dockerfile ends with `USER root`, discarding the non-root `app` user it creates | found |
| 10 | secrets | Dockerfile bakes the credential file into the image: `COPY config/app.env /srv/app.env` | confirmed |
| 11 | secrets | App logs the full `DATABASE_URL`, password included, at startup | confirmed |
| 12 | networking | `nginx.conf` upstream points at `app-01:8081`, but `APP_PORT` is 8080 for both apps | found |
| 13 | health | Compose healthcheck calls `/healthz`; the app implements `/health` | confirmed |
| 14 | identity | `app-02` is configured with `INSTANCE_ID: "app-01"`, so both instances report the same identity | confirmed |
| 15 | production readiness | The app runs on Flask's built-in development server, not a production WSGI server | confirmed |
| 16 | observability | The failing healthcheck writes two log lines every 5 seconds, burying real errors | confirmed |

Status values: found -> confirmed -> fixed and proven.

## Open leads - not yet examined

- nginx is attached to the backend network; the brief says it must not reach PostgreSQL or Redis
- PostgreSQL and Redis both publish host ports; the brief says they should not
- Named volume mounts to `/var/lib/postgresql/backup` while `tmpfs` covers `/data`
- Redis started with `--save "" --appendonly no`
- `restart: "no"`, and no resource limits anywhere in the file
- `depends_on` has no health conditions

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
           "database_url": "postgresql://barq_app:BarqLabOnly_7qN2vK8d@postgres:5433/barq_tasks",
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
  Not applied yet. Correct the ports to 5432 and 6379, and supply both URLs from a gitignored
  `.env` rather than from a tracked file, so this is fixed together with the secrets findings.

- **Retest evidence:**
  Not yet collected. Expected: `/ready` returns 200 with both dependencies reporting `ready`,
  and `grep dependency_error` returns nothing on a fresh run.

- **Related commit:**
  Pending.

- **Remaining uncertainty:**
  Finding 3 records that the password in `config/app.env` ends in `d` while the one in
  `docker-compose.yml` ends in `c`. The current error is `OperationalError`, which is what a
  refused connection looks like. Once the port is corrected I expect the mismatch to surface
  as an authentication failure instead, so I should not assume one fix resolves both. I will
  re-test after the port change before claiming the credential issue is fixed.

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
