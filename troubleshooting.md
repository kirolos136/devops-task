# Troubleshooting journal

Keep chronological entries. Copy this block for each meaningful investigation.

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
# Troubleshooting journal

## Findings register

Recorded 2026-09-08 from reading the starter, before the stack was ever started.
Nothing below is runtime-verified yet. Full entries follow once each is reproduced.

| # | Area | Observation | Status |
|---|---|---|---|
| 1 | secrets | DB credentials hardcoded in `docker-compose.yml` under `postgres.environment` | found |
| 2 | secrets | `config/app.env` is tracked in git and contains a password | found |
| 3 | secrets | Password differs between the two files: `...7qN2vK8d` in `config/app.env` vs `...7qN2vK8c` in Compose | found |
| 4 | database | `DATABASE_URL` uses port 5433; PostgreSQL listens on 5432 inside the container | found |
| 5 | cache | `REDIS_URL` uses port 6380; Redis listens on 6379 inside the container | found |
| 6 | networking | App binds to `APP_HOST: 127.0.0.1`, so nothing outside the container can reach it | found |
| 7 | networking | nginx publishes on `127.0.0.1:` only, which is not public access | found |
| 8 | networking | Compose publishes to nginx container port 81, but `nginx/nginx.conf:14` says `listen 80;` (`grep -n listen nginx/nginx.conf`) | found |

Status values: found -> testing -> fixed and proven.

## Open leads — not yet examined

- nginx is attached to the backend network; brief says it must not reach PostgreSQL or Redis
- PostgreSQL and Redis both publish host ports; brief says they should not
- Named volume mounts to `/var/lib/postgresql/backup` while `tmpfs` covers `/data`
- Redis started with `--save "" --appendonly no`
- `INSTANCE_ID` value on the `app-02` service
- `restart: "no"`, and no resource limits anywhere in the file
- `depends_on` has no health conditions
- App healthcheck calls `/healthz`; brief requires `/health`

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