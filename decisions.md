# Technical decisions

Decisions are appended as they are made. Anything still open is listed at the bottom rather
than guessed at.

---

## Decision 1 - Fix the supplied files in place rather than rewrite them

- **Choice:** Make small, targeted edits to `docker-compose.yml`, the `Dockerfile` and
  `nginx/nginx.conf`, one fault at a time, instead of rewriting them from scratch.
- **Why:** The brief states that commit diffs, timing and progress are reviewed, not just the
  end result. A one-line diff that corrects a port shows exactly what was wrong and what I did
  about it. A rewritten file shows nothing, and quietly discards the evidence of what the
  planted faults actually were.
- **Alternative:** Rewrite each file cleanly from the requirements. Faster in principle, and
  tempting once I had a list of faults.
- **Trade-off:** Working inside someone else's structure is slower and I inherit their style,
  including the YAML anchor pattern for the two app services. In exchange every fault stays
  individually visible, testable and revertible.
- **Evidence / commit:** The commit sequence from `investigate: capture first-run failure
  output` onwards, each one scoped to a single area.
- **Production improvement:** The same discipline is what makes a change reviewable and a
  rollback surgical. In production I would additionally require each fix to reference the
  incident or ticket that justified it.

---

## Decision 2 - All configuration in a single `.env` at the repository root

- **Choice:** Consolidate every configuration value into one gitignored `.env` at the project
  root, referenced from Compose as `${VAR}`, with `.env.example` as the committed template.
  The starter's `config/app.env` was removed.
- **Why:** Docker Compose automatically loads only the root `.env` when substituting `${VAR}`
  inside the Compose file itself. A file at `config/app.env` can be handed to a container with
  `env_file:`, but it can never fill in `${PUBLIC_PORT}` in the Compose file. Two files also
  meant two copies of the same password, which is exactly how they drifted apart in the
  starter: the two values differed in their final character, so authentication could never have
  succeeded. The brief asks for a single safe `.env.example`.
- **Alternative:** Keep per-service env files under `config/`. Reasonable on a large stack
  where different teams own different services and no single file should hold everything.
- **Trade-off:** One file means one blast radius; anyone with `.env` has every credential.
  For a five-service stack with one operator that is an acceptable simplification, and it
  removes a whole class of drift bug.
- **Evidence / commit:** `fix: move credentials to gitignored .env and correct service ports`.
  Verified with `grep -rn "BarqLabOnly" . --exclude-dir=.git`, which now matches only the
  gitignored `.env`.
- **Production improvement:** Environment files are the wrong home for secrets at scale. I
  would move to a secret manager (Docker or Kubernetes secrets, Vault, or the cloud provider's
  equivalent) with per-service scoping, short-lived credentials and automatic rotation, so no
  human ever holds the production password and no file on disk contains it.

---

## Decision 3 - Delete `config/app.env` rather than keep it as an empty template

- **Choice:** Remove the file from the repository with `git rm`, rather than emptying it and
  leaving a placeholder behind.
- **Why:** Once `env_file:` was repointed and the Dockerfile's `COPY config/app.env` line was
  deleted, nothing reads the file. A leftover file that once held credentials is a trap: the
  next person to open the repository has to work out whether it is live configuration, and may
  helpfully refill it. `.env.example` already documents every key, so the template role is
  covered.
- **Alternative:** Keep it as an empty stub to preserve the starter's layout.
- **Trade-off:** Deleting a file the assessors supplied could look like I misread the intent.
  I judged that the risk of a stale credentials file outweighs the risk of an unusual-looking
  deletion, and the reasoning is recorded here and in `troubleshooting.md`.
- **Evidence / commit:** `fix: move credentials to gitignored .env and correct service ports`.
  The original file is preserved unchanged in the baseline commit, so nothing is lost.
- **Production improvement:** Deleting a file does not remove it from git history. The full
  handling for a real credential is recorded in `security_review.md`: rotate first, then purge
  history, on the principle that anything ever pushed is compromised.

---

## Decision 4 - The PostgreSQL healthcheck reads the same variables as the credentials

- **Choice:** Change the healthcheck from `pg_isready -U barq_app -d barq_tasks` to
  `pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}`.
- **Why:** Once the user and database name became variables, leaving the healthcheck hardcoded
  reintroduced the same class of bug I had just fixed. Two places holding the same value drift
  apart, and this one drifts silently: the check would fail against a user that no longer
  exists, the container would be marked unhealthy, and nothing would say why.
- **Alternative:** Leave it hardcoded, on the grounds that these values rarely change.
- **Trade-off:** None worth the name. The variables are already in Compose's scope, so the
  change costs nothing and removes a coupling.
- **Evidence / commit:** `fix: move credentials to gitignored .env and correct service ports`.
- **Production improvement:** The broader rule is that a value should have exactly one
  authoritative definition. Where duplication is unavoidable, a check should assert the copies
  agree rather than trusting them to.

---

## Decision 5 - Keep the starter's base image, and keep a Python-based healthcheck

- **Choice:** Stay on `python:3.12-slim-bookworm`, pinned by digest, and keep the healthcheck
  implemented as `python -c "import urllib.request; urllib.request.urlopen(...)"` rather than
  installing `curl` into the image.
- **Why:** The brief requires health-check tools that are installed in the image. A slim image
  ships no `curl` and no `wget`, so a naive `CMD curl ...` healthcheck would fail for a reason
  that has nothing to do with the application's health. Python is guaranteed present because it
  is what runs the app, so using it costs nothing. Installing `curl` would add packages, image
  size and patching surface purely to perform a check the runtime can already do. The digest
  pin means the base image cannot change under me between builds.
- **Alternative:** `RUN apt-get install -y curl` and use a conventional `curl -f` healthcheck,
  which is more readable and more familiar to most reviewers.
- **Trade-off:** The Python one-liner is harder to read than `curl -f http://localhost:8080/health`,
  and it raises on any non-2xx status rather than needing an explicit flag. I accept the
  readability cost for a smaller image with fewer packages to patch.
- **Evidence / commit:** The healthcheck block in `docker-compose.yml`; the base image is
  unchanged from the baseline commit.
- **Production improvement:** A distroless or Alpine-based image plus a small static health
  binary would shrink the attack surface further. I would also scan the image on every build
  and fail the pipeline on new high-severity findings.

---

## Decision 6 - Repository public, no licence

- **Choice:** Publish the GitHub repository publicly, with no licence file.
- **Why:** The brief requires a submitted repository URL and a matching CI run, and lists
  missing or inaccessible evidence as a hard fail. A private repository a reviewer cannot open
  fails on that ground alone. No licence, because the starter is BARQ's code and not mine to
  grant rights over.
- **Alternative:** Keep it private and add the reviewer as a collaborator. This was my first
  instinct, since the starter is another organisation's material.
- **Trade-off:** A public repository means the planted-fault design and my working notes are
  visible to anyone. I accepted that because the assessors published the starter themselves,
  and because accessible evidence is an explicit submission requirement.
- **Evidence / commit:** The repository itself.
- **Production improvement:** Not applicable to a production system, where the default is the
  opposite: private by default, access granted per person and reviewed periodically.

---

## Decision 7 - Redis persists with the append-only file, not snapshots

- **Choice:** `--appendonly yes`, with a named `redis-data` volume mounted at `/data`.
- **Why:** The only thing in Redis is the `barq:requests` counter, and nothing else in the
  system knows that number. It cannot be recomputed, so losing it loses information. AOF logs
  every write and bounds the loss to about a second; snapshots would lose everything since the
  last one.
- **Alternative:** RDB snapshots (`--save "60 1000"`), or both together.
- **Trade-off:** AOF writes a larger file and restarts more slowly because it replays the log.
  At this data size neither cost is measurable.
- **Evidence / commit:** `fix: persist postgres data on named volume and enable redis
  persistence`. Proven by the counter continuing from 1 to 2 across a restart instead of
  resetting.
- **Production improvement:** Run both AOF and RDB, as Redis recommends, and back the snapshot
  up off-host. Prove restores with a scheduled drill rather than assuming they work.

---

## Decision 8 - Shared upstream state with `zone`, and real failover settings

- **Choice:** `zone application_pool 64k;` in the upstream block,
  `max_fails=3 fail_timeout=10s` on each server, and `proxy_next_upstream error timeout`.
- **Why:** nginx runs one worker per CPU core, and without `zone` each worker keeps private
  upstream state. That broke load balancing outright (every worker started at the first server,
  so all traffic went to app-01) and made `max_fails` far less sensitive than configured, since
  failures had to accumulate on one individual worker. `max_fails=0` meant a dead backend was
  never benched; `proxy_next_upstream off` meant a request landing on it was never retried
  elsewhere. Together those two made surviving a backend loss impossible, which the brief
  requires me to demonstrate.
- **Alternative:** `worker_processes 1`, which also gives a single cursor. Simpler, but throws
  away multi-core capacity to fix a state-sharing problem.
- **Trade-off:** `zone` costs a small fixed amount of shared memory. 3 strikes in 10 seconds
  tolerates a brief blip without benching a healthy backend, while still reacting within a few
  seconds to a real failure.
- **Evidence / commit:** `fix: correct nginx port mapping, upstream ports and instance
  identity`. Ten consecutive requests now alternate between app-01 and app-02.
- **Production improvement:** Add active health checks rather than relying only on passive
  failure counting, so a backend is removed before real user requests hit it.

---

## Decision 9 - Writes are deliberately not retried on another backend

- **Choice:** Keep nginx's default of excluding non-idempotent methods from
  `proxy_next_upstream`. POST requests are not retried elsewhere.
- **Why:** If a backend accepts a POST and dies before responding, the record may already have
  been created. Retrying it on another instance would create it twice. A visible 502 the client
  can decide about is safer than a silent duplicate write.
- **Alternative:** Add the `non_idempotent` flag so writes fail over too, which would make the
  failure demonstration look cleaner.
- **Trade-off:** During a backend outage, reads stay seamless but a write that lands on the
  failed instance returns an error. I accept that visible failure rather than risk duplicate data.
- **Evidence / commit:** Same commit. To be confirmed during the failure test.
- **Production improvement:** Make writes idempotent with a client-supplied request key, so a
  retry is provably safe and failover can then cover writes as well.

---

## Decision 10 - `unless-stopped` rather than `always`

- **Choice:** `restart: "unless-stopped"` on every service.
- **Why:** A crashed container should come back without waiting for a human. But `always` also
  restarts a container I stopped deliberately, which would break the failure demonstration the
  brief requires: stop one backend, show traffic continuing, then recover it. `unless-stopped`
  recovers from crashes and respects an intentional stop.
- **Alternative:** `always`, or `on-failure` to restart only on a non-zero exit.
- **Trade-off:** After a host reboot, `unless-stopped` does not restart a container that was
  deliberately stopped beforehand. That is the behaviour I want here.
- **Evidence / commit:** `feat: add restart policies, resource limits and health-gated startup`.
- **Production improvement:** Alert on restart loops. Automatic recovery is useful but it hides
  a recurring fault if nobody is told it is happening.

---

## Decision 11 - Resource limits sized from measurement, not from round numbers

- **Choice:** memory limits of 128M for nginx, 256M for each app and for redis, 512M for
  postgres; CPU quotas of 0.5 everywhere except postgres at 1.0.
- **Why:** I measured idle usage with `docker stats` first: nginx 14.5 MiB, redis 8-10 MiB,
  postgres 35-38 MiB, apps 48-62 MiB. The limits are roughly four to eight times observed, which
  leaves headroom for load while still catching a runaway process. PostgreSQL is deliberately the
  outlier: its idle figure understates it, because `shared_buffers` alone defaults to 128MB and
  each connection takes `work_mem` on top.
- **Alternative:** No limits, or one uniform limit for every service. Both were tempting and both
  ignore what the services actually do.
- **Trade-off:** Limits sized from idle measurements plus headroom, not from load testing. If
  real traffic is much heavier than this assessment's, they would need revisiting.
- **Evidence / commit:** Same commit. `docker stats --no-stream` now shows each container against
  its own limit rather than against the host total.
- **Production improvement:** Derive limits from observed production percentiles, and alert on
  containers approaching their memory ceiling before the kernel kills them.

---

## Decision 12 - Startup gated on health, not on existence

- **Choice:** `depends_on` in long form with `condition: service_healthy`. The apps wait for
  postgres and redis; nginx waits for both apps.
- **Why:** The list form waits only for a container to start, not to be able to serve. PostgreSQL
  takes several seconds to accept connections after its container exists, and nginx resolves its
  upstreams at startup. Gating on the healthcheck removes a whole class of "works on the second
  try" flakiness, and it matters more once CI is starting the stack unattended.
- **Alternative:** Retry loops in the application, or a wait-for-it script in the entrypoint.
  Both put orchestration logic somewhere it does not belong when Compose can express it directly.
- **Trade-off:** Startup is slower and strictly sequential. That is the correct trade for a stack
  that must come up unattended.
- **Evidence / commit:** Same commit. Services now start in dependency order rather than all at
  once.
- **Production improvement:** Health-gated startup handles the first boot. It does not handle a
  dependency failing later, which is what readiness probes and circuit breakers are for.

---

## Decision 13 - Plain SQL dumps, restored with psql

- **Choice:** `pg_dump --clean --if-exists` writing plain SQL to a timestamped file under
  `backups/`, restored with `psql -v ON_ERROR_STOP=1`. Both tools are run inside the postgres
  container with `docker compose exec -T`.
- **Why:** Plain SQL is readable, so a backup can be inspected before trusting it. `--clean`
  makes the dump self-sufficient: it drops and recreates rather than failing on an existing
  table. Both tools already ship in the postgres image, so nothing needs installing. Timestamped
  filenames mean a new backup never silently overwrites the last one.
- **Alternative:** `pg_dump -Fc` custom format with `pg_restore`, which is compressed and allows
  selective restore. Better for large databases; unnecessary here and not human-readable.
- **Trade-off:** Plain SQL is larger and slower to restore at scale. At this size neither matters,
  and readability is worth more.
- **Evidence / commit:** `feat: add postgres backup and restore scripts with proven recovery`.
  Proven by creating a record after the backup, restoring, and confirming that record disappeared
  while the earlier five returned. The restore output also shows `setval 5`, confirming the ID
  sequence is restored and not just the rows.
- **Production improvement:** Schedule backups, store them off-host, and run an automated restore
  drill that asserts a known record exists afterwards. An untested backup is not a backup.

---

## Decision 14 - `-T` on every non-interactive `docker compose exec`

- **Choice:** Always pass `-T` when a script runs a command in a container.
- **Why:** Without it Compose allocates a pseudo-terminal, which rewrites line endings and injects
  control characters. That is helpful for a human at a keyboard and corrupting for piped data. A
  backup taken without `-T` is silently malformed: the file exists, looks plausible, and fails at
  restore time. CI has no terminal at all, so the same flag is required there.
- **Alternative:** Omit it and rely on the default. Works interactively, fails everywhere else.
- **Trade-off:** None. The flag is only needed when a human is not driving the command.
- **Evidence / commit:** Used in `backup.sh`, `restore.sh` and the isolation checks in
  `validate.py`.
- **Production improvement:** Prefer running such commands through a dedicated job or init
  container rather than `exec` into a live service, so a backup cannot be affected by whatever
  else that container is doing.

---

## Still open - to be decided and recorded

- Two named app services rather than `--scale`, and how a third instance is added live
- Whether to move off Flask's development server for the final submission
