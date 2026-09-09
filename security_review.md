# Security and production-readiness review

Findings are grouped by whether the fix is already in the repository or still planned. Each
entry states how to verify it, so nothing here has to be taken on trust.

**Status key:** `IMPLEMENTED` - fixed and proven in this repository.
`PENDING` - identified, fix scheduled, not yet applied at the time of writing.
`ACCEPTED` - understood, deliberately not changed, with the reasoning stated.

---

## 1. Database credentials committed in tracked configuration - IMPLEMENTED

- **Risk and evidence:** `config/app.env` was tracked in git and contained a full PostgreSQL
  connection URL including the password. `docker-compose.yml` separately hardcoded
  `POSTGRES_USER`, `POSTGRES_DB` and `POSTGRES_PASSWORD` under the `postgres` service. The
  repository is public, so both were readable by anyone.
- **Impact:** Anyone with the repository URL obtains the database credentials. Because the same
  values were reused across the stack, one disclosure compromises every service that uses them.
- **Implemented fix / commit:** All values moved into a gitignored `.env` at the repository
  root and referenced from Compose as `${VAR}`. `config/app.env` deleted with `git rm`.
  Commit: `fix: move credentials to gitignored .env and correct service ports`.
- **Production follow-up:** Environment files are not a secret store. Move to a managed secret
  system with per-service scoping, short-lived credentials and automated rotation, and add
  automated secret scanning to CI so a future commit cannot reintroduce this.
- **How to verify:** `grep -rn "BarqLabOnly" . --exclude-dir=.git` matches only `.env`.
  `git check-ignore -v .env` confirms it is ignored. `git ls-files | grep app.env` returns
  nothing.

---

## 2. The credential was baked into the application image - IMPLEMENTED

- **Risk and evidence:** The Dockerfile contained `COPY config/app.env /srv/app.env`, placing
  the password inside an image layer. Visible in the build output as step 7/7.
- **Impact:** An image is a distributable artifact. Anyone who can pull it can read the file
  with `docker history` or by unpacking the layers, without ever running a container. Deleting
  the file in a later layer would not help, because earlier layers remain.
- **Implemented fix / commit:** The `COPY` line was removed. Configuration now reaches the
  container at run time through `env_file`, not at build time.
  Commit: `fix: move credentials to gitignored .env and correct service ports`.
- **Production follow-up:** Treat build-time secrets as a class of defect. Enforce it with an
  image scan in CI that fails the build when a credential pattern appears in any layer.
- **How to verify:** `grep -n "app.env" Dockerfile` returns nothing. After a rebuild,
  `docker compose exec app-01 ls /srv` shows no `app.env`.

---

## 3. The application prints its full connection URL, password included, to the logs - PENDING

- **Risk and evidence:** `app/server.py` logs `configuration_loaded` at startup with the raw
  `DATABASE_URL`. Observed directly:
  ```
  app-01 | {"event": "configuration_loaded",
           "database_url": "postgresql://barq_app:<redacted>@postgres:5432/barq_tasks"}
  ```
- **Impact:** This is the most durable form of the leak. Removing the secret from config
  achieves little while every container start writes it to stdout, from where it reaches
  `docker logs`, any log aggregator, CI job output and every screenshot or pasted log. Log
  stores are typically far more widely readable than the repository.
- **Implemented fix / commit:** None yet.
- **Production follow-up:** Never log a credential-bearing value. Log the host, port and
  database name separately, or redact the password before logging. Add a log-scrubbing filter
  at the aggregation layer as a second line of defence, since application code will eventually
  get this wrong again.
- **How to verify:** After the fix, `docker compose logs | grep -i "configuration_loaded"`
  shows the connection target with no credential in it.

---

## 4. The credential survived in project documentation - IMPLEMENTED

- **Risk and evidence:** After the configuration was cleaned, a repository scan still found the
  password, in `troubleshooting.md`, inside a log line that had been pasted verbatim as
  evidence. That file is tracked and was about to be pushed to a public repository.
- **Impact:** The configuration would have looked clean while the secret shipped in the very
  document describing its removal. This is a common real-world leak path: secrets are found in
  READMEs, postmortems, issue comments and chat far more often than in config files.
- **Implemented fix / commit:** The value was replaced with `<redacted>` in the quoted log, and
  the findings register now describes the mismatch without printing either value. Recorded as
  Entry 4 in `troubleshooting.md`.
- **Production follow-up:** Make the scan a control rather than a habit: a pre-commit hook and
  a CI secret-scanning step that fail on credential patterns anywhere in the tree, including
  markdown.
- **How to verify:** `grep -rn "BarqLabOnly" . --exclude-dir=.git` matches only `.env`.

---

## 5. The original credential remains in git history - ACCEPTED for this assessment

- **Risk and evidence:** `config/app.env` containing the password is present in the required
  unmodified baseline commit. Deleting the file going forward does not remove it from history;
  `git log -p -- config/app.env` still shows it.
- **Impact:** In a real system the credential must be considered compromised permanently. Any
  clone taken at any point retains it, and repository history is routinely mirrored and cached.
- **Implemented fix / commit:** None, deliberately. The baseline commit is an explicit graded
  requirement of the brief, the value is clearly synthetic lab data supplied by BARQ, and the
  database it protects has no published port and exists only inside a local Compose network.
- **Production follow-up:** The correct order is rotate first, then purge. Rotate the credential
  everywhere it is used, confirm the old one is rejected, then rewrite history with
  `git filter-repo` or BFG and force-push, coordinating with everyone holding a clone. Purging
  without rotating is theatre, because the secret has already been distributed.
- **How to verify:** `git log --oneline -- config/app.env` shows the file's full history,
  including its introduction in the baseline.

---

## 6. Containers ran as root - IMPLEMENTED

- **Risk and evidence:** The Dockerfile creates a dedicated non-root user
  (`groupadd --gid 10001 app && useradd --uid 10001 --gid app`), then discards it on the
  second-to-last line with `USER root`.
- **Impact:** Any code execution flaw in the application runs with root privileges inside the
  container, which materially improves an attacker's chances of escaping to the host or abusing
  a mounted path. Creating the user and then not using it is worse than not creating it, because
  it reads as hardened when it is not.
- **Implemented fix / commit:** `USER root` changed to `USER app`.
  Commit: `fix: bind app to all interfaces, correct healthcheck path, drop root`.
  Proven with `docker compose exec app-01 whoami`, which returns `app`.
- **Production follow-up:** Enforce this rather than rely on review: add a policy check in CI
  that fails any image whose configured user is root, and drop all Linux capabilities the
  workload does not need.
- **How to verify:** `docker compose exec app-01 whoami` returns `app`, not `root`.

---

## 7. PostgreSQL and Redis publish ports to the host - PENDING

- **Risk and evidence:** `ports: ["127.0.0.1:15432:5432"]` on postgres and
  `["127.0.0.1:16379:6379"]` on redis. The brief requires that only nginx publishes a port.
- **Impact:** Every published port is attack surface that does not need to exist. The
  application reaches both services over the internal Compose network by service name and never
  needs a host mapping. The `127.0.0.1` prefix limits exposure to the host, which reduces but
  does not remove the problem: any local process or user can reach the database directly,
  bypassing the application entirely.
- **Implemented fix / commit:** None yet. Planned: remove both `ports:` entries.
- **Production follow-up:** Data stores should never be directly reachable from outside their
  network segment. Where operator access is genuinely required, provide it through a bastion or
  an authenticated proxy with audit logging, not a permanently open port.
- **How to verify:** `docker ps --format '{{.Names}}\t{{.Ports}}'` shows a host port for nginx
  only.

---

## 8. nginx is attached to the backend network - PENDING

- **Risk and evidence:** The nginx service declares `networks: [frontend, backend]`, giving the
  internet-facing component a direct route to PostgreSQL and Redis. The brief requires that
  direct access be blocked.
- **Impact:** nginx is the only component exposed to the outside world and therefore the most
  likely to be compromised. Placing it on the data network removes the segmentation that would
  otherwise contain such a compromise, so a single nginx vulnerability reaches the database.
- **Implemented fix / commit:** None yet. Planned: attach nginx to `frontend` only. The
  `backend` network is already declared `internal: true`, which blocks outbound access from it
  but does nothing to stop a member of that network reaching its peers.
- **Production follow-up:** Treat network membership as least privilege: a service joins a
  segment only if it must talk to something on it. Verify the isolation with a test rather than
  by reading the config.
- **How to verify:** `docker compose exec nginx getent hosts postgres` returns nothing, while
  `docker compose exec app-01 getent hosts postgres` returns an address.

---

## 9. The application runs on Flask's development server - PENDING decision

- **Risk and evidence:** The container logs the framework's own warning on every start:
  ```
  WARNING: This is a development server. Do not use it in a production deployment.
  ```
- **Impact:** The development server is single-process, has no request queueing or timeout
  handling worth the name, and is not hardened against malformed or slow requests. Under load
  or a slow-client attack it degrades far earlier than a production server would.
- **Implemented fix / commit:** None. The brief does not require a WSGI server and the
  container entrypoint is application code rather than configuration, so changing it is a
  larger change than the faults I was asked to fix.
- **Production follow-up:** Run the app under gunicorn or uvicorn with an explicit worker count,
  request timeouts and graceful shutdown, keeping nginx in front for TLS termination and buffering.
- **How to verify:** The warning no longer appears in `docker compose logs`, and the process
  list inside the container shows the production server rather than `python -m app.server`.

---

## 10. Application data did not survive a container restart - IMPLEMENTED

- **Risk and evidence:** The named volume `postgres-data` is mounted at
  `/var/lib/postgresql/backup`, which PostgreSQL does not use, while its actual data directory
  `/var/lib/postgresql/data` is covered by `tmpfs`. Redis runs with `--save "" --appendonly no`,
  disabling both of its persistence mechanisms.
- **Impact:** `tmpfs` is a filesystem in RAM. Every database write is lost when the container is
  recreated, and the volume that appears to provide durability holds nothing. The stack looks
  correctly configured for persistence and is not, which is the most dangerous kind of backup
  failure: it is only discovered when the data is needed.
- **Implemented fix / commit:** `postgres-data` now mounts at `/var/lib/postgresql/data`, the
  `tmpfs` line is deleted, and Redis runs with `--appendonly yes` on its own `redis-data`
  volume. Commit: `fix: persist postgres data on named volume and enable redis persistence`.
  Proven: a record created before `docker compose down` was still present after `up`, and the
  counter continued from its previous value.
- **Production follow-up:** Persistence configuration must be proven, not assumed. Run a
  scheduled restore drill that recreates the containers and asserts a known record still exists,
  and alert if the check ever fails.
- **How to verify:** Create a record through `/records`, run `docker compose down` followed by
  `docker compose up -d` without `-v`, and read the record back successfully.

---

## 11. A broken healthcheck flooded the logs and hid real errors - IMPLEMENTED

- **Risk and evidence:** The Compose healthcheck requests `/healthz`, which the application does
  not implement. Every 5 seconds it produces a 404 and two log lines, roughly 34,000 lines a
  day per instance. This actively obstructed the investigation: `docker compose logs app-01
  --tail=20` showed nothing but healthcheck noise, and the real dependency errors were only
  found by filtering with `grep`.
- **Impact:** Noise at this volume buries genuine errors, inflates log storage cost, and trains
  operators to ignore the log stream. It also leaves both application containers permanently
  marked unhealthy, so the health status carries no information.
- **Implemented fix / commit:** The healthcheck now requests `/health`.
  Commit: `fix: bind app to all interfaces, correct healthcheck path, drop root`.
  Both app containers report healthy and the repeating 404 lines have stopped.
- **Production follow-up:** Alert on healthcheck failure rather than letting it fail silently
  forever, and keep noisy diagnostics out of the level operators actually read.
- **How to verify:** `docker compose ps` shows both application containers healthy, and the
  repeating 404 lines stop appearing in `docker compose logs`.

---

## 12. No restart policies and no resource limits - PENDING

- **Risk and evidence:** The shared application configuration sets `restart: "no"`, and no
  service in `docker-compose.yml` declares CPU or memory limits.
- **Impact:** A crashed container stays down until someone notices, so a transient fault becomes
  an outage. Without limits, one service can consume all host memory or CPU and take the rest of
  the stack with it; a memory leak in the application degrades the database instead of failing
  fast and being restarted.
- **Implemented fix / commit:** None yet. Planned: a restart policy on every service and
  explicit CPU and memory limits, with the chosen numbers justified in `decisions.md`.
- **Production follow-up:** Limits should be derived from observed usage rather than guessed,
  and paired with alerting on restart loops so that automatic recovery does not silently mask a
  recurring fault.
- **How to verify:** `docker stats --no-stream` shows the configured limits, and killing a
  container's main process results in it being restarted automatically.

---

## 13. A healthy healthcheck will not prove the service is reachable - ACCEPTED, monitored

- **Risk and evidence:** The healthcheck runs inside the container and connects to
  `127.0.0.1`. The application is currently configured with `APP_HOST: 127.0.0.1`, so it listens
  only on loopback. Once the healthcheck path is corrected, the container will report healthy
  while nginx still cannot reach it.
- **Impact:** A green status that does not correspond to a working service is worse than a red
  one, because it suppresses investigation. Orchestrators route traffic based on this signal.
- **Implemented fix / commit:** The binding was corrected to `0.0.0.0`, and reachability was
  verified from a different container rather than trusting the health status:
  `docker compose exec nginx wget -qO- http://app-01:8080/health` returns 200. The structural
  point remains true afterwards and is recorded here deliberately.
- **Production follow-up:** Keep the liveness check local, but add an external readiness probe
  that traverses the real network path a user's request would take, so binding and network
  faults are detected rather than hidden.
- **How to verify:** `docker compose exec nginx wget -qO- http://app-01:8080/health` succeeds
  from a different container, not just from inside the application container itself.
