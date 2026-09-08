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

## Still open - to be decided and recorded

- Redis persistence mode (append-only file vs snapshots) and the volume it writes to
- Restart policy, and why `unless-stopped` rather than `always`
- Specific CPU and memory limits per service, and the reasoning behind the numbers
- nginx upstream timeouts, `max_fails` and `proxy_next_upstream` values
- Two named app services rather than `--scale`, and how a third instance is added live
- Whether to move off Flask's development server for the final submission
