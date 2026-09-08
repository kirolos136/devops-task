# AI usage disclosure

AI was used throughout this task. Each use is logged below, appended on the day it
happened rather than reconstructed at the end.

---

## Entry 1 — Learning and thinking (2026-09-07)

- **Tool/model:** Claude (Opus 5)
- **Purpose:** Learning and reasoning support. Used to explain concepts I had not worked
  with before, to check my understanding, and to think through choices out loud. Not used
  to generate application code.
- **Files or decisions affected:** No files authored by AI. It informed how I read the
  starter files and how I approached the task's setup decisions.
- **What you changed or rejected:** Rejected advice that conflicted with the brief and
  went with the brief in each case. I took my own handwritten notes and restated each
  concept in my own words before acting on it.
- **How you independently verified it:** Checked every claim against the brief, the
  starter files, or the terminal output in front of me. Anything about runtime behaviour
  is confirmed by actually running it and recorded in `troubleshooting.md`, not accepted
  on trust.
- **Related commit:** e43dda7

---

## Entry 2 — Drafting the documentation files (2026-09-07)

- **Tool/model:** Claude (Opus 5)
- **Purpose:** Draft the prose for the markdown deliverables — this file, and later
  `decisions.md`, `troubleshooting.md`, `security_review.md`, `log_analysis.md` and
  `README.md` — rather than writing each from a blank page.
- **Files or decisions affected:** `AI_USAGE.md`, and the remaining documentation files
  as they are written. Entries here are appended as each one is produced.
- **What you changed or rejected:** I decide the content and structure; AI drafts the
  wording.
- **How you independently verified it:** Read every drafted line against my own terminal
  history and commits, corrected anything inaccurate, and removed any claim I could not
  personally demonstrate. Every technical assertion in the reports is backed by a command
  and its output recorded in the repository.
- **Related commit:** e43dda7

---

## Entry 3 — `.gitignore` hardening, rejected (2026-09-07)

- **Tool/model:** Claude (Opus 5)
- **Purpose:** Review whether the starter's `.gitignore` needed strengthening before the
  baseline commit.
- **Files or decisions affected:** `.gitignore` — **left unchanged**.
- **What you changed or rejected:** **Rejected** the suggestion to preemptively add
  `*.env`, `secrets/`, `*.key` and `*.pem`. Ignore rules for files this stack never
  produces are unjustifiable boilerplate, not security.
- **How you independently verified it:** Listed what this task actually creates — a `.env`
  copied from `.env.example`, and PostgreSQL backup output — and confirmed the shipped
  `.gitignore` already covers all of it via `.env`, `.env.*`, `backups/` and `*.dump`.
  Confirmed from the brief that the stack is plain HTTP behind one published port, so no
  key or certificate files exist. Ran `grep -rn "glpat-" .` to confirm no credential from
  the starter clone remained in the repository.
- **Related commit:** e43dda7

  **Update (2026-09-09):** this reasoning turned out to rest on an assumption I had not
  checked. When I later read the whole repository I found `config/app.env`, an existing
  tracked file containing a password, which the rejected `*.env` rule would have matched.
  My argument was internally sound but its premise was wrong, because I had not finished
  reading the repository before ruling on it. The lesson I took from it is to read first
  and decide after, and I am recording the correction here rather than editing the original
  entry.

---

## Entry 4 — Investigation support and documentation drafting (2026-09-08 to 2026-09-09)

- **Tool/model:** Claude (Opus 5) via Claude Code
- **Purpose:** Two distinct uses. First, explanation and review while I investigated the
  broken stack: container networking, health checks, YAML anchors, Docker logging, and how
  to read `nginx.conf`, the `Dockerfile` and the Flask app coming from a JavaScript and
  Express background. Second, drafting the prose for the documentation deliverables, so my
  own time could go into the technical work.
- **Files or decisions affected:** `troubleshooting.md`, `decisions.md`, `security_review.md`
  and this file were drafted by Claude from evidence I produced. The technical changes to
  `docker-compose.yml`, the `Dockerfile`, `.env` and `.env.example` were made by me. No
  application code was AI-generated.
- **What you changed or rejected:** Claude repeatedly withheld answers at my request and
  posed questions instead, so the faults were found by me reading the files. Two corrections
  ran the other way and are worth recording. When `curl` returned a connection reset I read
  it as the application's loopback binding; the evidence showed the request never reached
  nginx at all, and I revised the conclusion. Separately, a log line Claude pasted into
  `troubleshooting.md` as evidence still contained the database password; my own repository
  scan caught it before the commit, and it is now redacted and recorded as finding 17.
- **How you independently verified it:** Every fault in `troubleshooting.md` is backed by
  output from my own terminal, quoted as it appeared. Where a claim could not be reproduced
  it is marked unconfirmed rather than asserted. I ran `grep -rn "BarqLabOnly" .
  --exclude-dir=.git` before committing to confirm no credential remained in a tracked file,
  and I re-read the drafted documents against my command history and removed anything I
  could not demonstrate.
- **Related commit:** `fix: move credentials to gitignored .env and correct service ports`
  and the documentation commits that follow it.