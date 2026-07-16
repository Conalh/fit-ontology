# FitOntology — Roadmap

**Current goal:** Prove that one working trainer can use the weekly brief → client evidence → plan → override → calibration loop for a real roster without losing trust in the recommendation.

**Current truth:** v0.6.0 runs locally or on an operator-managed host. The evergreen synthetic demo is local-first; no public service is currently maintained. CI covers **377 Python + 40 frontend tests** on Python 3.12/3.13 and Node 24.

Phases below are **sequenced, not scheduled**. Each ships something usable before the next starts.

---

## Shipped foundations

These were roadmap items; they are done. Kept here so the forward phases don't repeat solved problems.

| Area | What landed | Where |
| --- | --- | --- |
| **Multi-tenant data model** | `trainers` table; `trainer_id` on all client data; idempotent migrations + backfill | `ontology.py`, `db.py` |
| **Isolation** | Scoped db helpers + `test_trainer_isolation.py` (10 regression tests) | `db.py`, `tests/` |
| **App auth** | bcrypt passwords; signed HttpOnly session cookie (`itsdangerous`); login / logout / me | `auth.py`, `routes/auth.py`, `web/app/login/` |
| **Demo mode** | Unauthenticated visitors → `t_demo` read-only; mutating routes → 403 | `demo.py`, `forbid_demo_trainer` |
| **Trainer admin CLI** | Create / list / rotate passwords (interim until self-serve sign-up) | `scripts/trainer.py` |
| **Self-hosting path** | Multi-stage Docker; optional Fly.io + persistent DuckDB volume | `Dockerfile`, `fly.toml`, `docs/deploy.md` |
| **Client share (Stage A)** | Mint token → `/share?t=…`; 14-day TTL; rate-limited; minimal public payload | `routes/share.py`, `web/app/share/` |
| **Client intake (Stage A)** | Trainer mints one-shot URL → client fills form at `/intake?t=…`; atomic insert-then-consume; per-IP submit rate-limit | `routes/intake.py`, `web/app/intake/`, `web/components/intake-link-modal.tsx` |
| **Planning loop** | Weekly plan from verdict; in-place slot edit; plan-vs-execution matcher | `planning.py`, `routes/planning.py` |
| **Security pass (v1)** | Rate limits; append-only audit log; CSP + hardening headers | `rate_limit.py`, `api.py`, `SECURITY.md` |
| **Coach Assistant (v0)** | LLM-drafted client message for trainer review before PDF / share | `coach_draft.py`, `routes/coach.py` |
| **Engine depth** | Trend detectors, recovery gauge, citation-backed signal chips, calibration + adherence telemetry, per-client thresholds | `reasoning.py`, calibration UI |
| **Engine v2 — dual-window trend** | Acute 7d OLS + chronic 28d EWMA combiner, level-dominates-trend safety rule (recovery ≥90 demotes trend signals), per-trend `7d` / `28d` / `7d + 28d` chip badges, popover surfaces both slope numbers | `reasoning.py` (combine_acute_chronic, compute_trend_diagnostics), `recommendation-card.tsx` |

**Supported operating paths:**

- **Local** — recommended evaluation and single-trainer path.
- **Operator-managed Fly.io** — reference deployment only; the project makes no uptime claim.
- **Local + private tunnel** — optional remote access; app auth remains independent of the perimeter.

---

## Next up (recommended order)

Short horizon before chasing new surface area:

1. **Friend test** — one real trainer, end-to-end (see Phase 1)
2. **First-run onboarding** — zero-client state → add client → upload → first useful brief
3. **Import reliability** — test real Apple Health/Strava exports and make failures actionable
4. **Password reset** — only before inviting trainers who cannot use the admin CLI
5. **Operational durability** — backups and monitoring only when a maintained host exists

---

## Phase 1 — Friend test

**Goal:** One real human (not the maintainer) uses the dashboard for a full week.

**How to invite today:**

```bash
python scripts/trainer.py create --email friend@example.com --name "Their Name" --prompt-password
# → they sign in at /login on the local or operator-managed app
```

**Ships:**

- Watch what they actually do (roster → client → override → calibration → share link)
- Triage feedback into a punch list before public sign-up

**Why its own phase:** Real trainers reshape onboarding, defaults, and what "done" means on Monday morning. Cheap to learn before building billing.

**Effort:** Hours of observation, days of fixes — not weeks of architecture.

---

## Phase 2 — Private beta (3–5 trainers)

**Goal:** Trainers you don't personally know can sign up, pay nothing (yet), and run a real roster without you running CLI commands.

**Ships:**

- **Self-serve registration** — `POST /api/auth/register` (invite-only flag for closed beta) or magic-link sign-up
- **Password reset** — email token flow; retire CLI-only rotation for day-to-day use
- **Onboarding wizard** — account → first client → connect data (upload Apple Health / Strava export as v0; OAuth in Phase 5)
- **Empty states** — roster, calibration, and client detail when `total === 0`
- **Operator runbook** — how to invite, suspend, or delete a trainer account

**Not in scope yet:** Stripe, marketing site, SSO (app-managed auth is the path unless beta feedback says otherwise).

**Risk:** First time strangers can break things. Lean on isolation tests + audit log + rate limits already shipped.

**Effort:** ~2 weeks focused.

---

## Phase 3 — Client portal

**Stage A — shareable link:** ✅ Shipped. Trainer copies link from Send to client (clipboard + PDF). Remaining polish:

- [ ] **SMS / email handoff** — `mailto:` / `sms:` with pre-filled body, or Twilio/Resend when volume justifies it
- [ ] **Optional auto-mint** — fresh share token each Monday (today: manual mint per send)
- [ ] **Share page polish** — mobile layout pass, "link expires in N days" prominence

**Stage A.5 — intake link:** ✅ Shipped. Trainer mints a one-shot URL from the roster, the prospective client fills the form, the row lands in the roster. Inverse of the share link. Remaining polish:

- [ ] **Trainer notification on submission** — today the trainer sees the new client on next roster refresh; later: email/push when volume justifies it
- [ ] **PARQ-style screening fields** — separate `client_intake_responses` table for cardiac history, medications, emergency contact (out-of-scope for v1 to keep the `clients` schema tight)
- [ ] **Reusable / team intake** — one URL onboarding N clients (different token semantics; not needed yet)

**Stage B — client accounts (later):**

- Clients log in (email / SSO); see history, trends, adherence
- Post-session RPE + notes from phone
- Installable PWA ("your plan updated" — push notifications deferred)

**Risk:** Client-facing surface is where privacy expectations are sharpest. Same scoping discipline as trainer isolation; never expose another client's rows.

**Effort:** Stage A polish ~1 week. Stage B ~2–3 weeks.

---

## Phase 4 — Postgres + scale

**Goal:** Support concurrent writers, connection pooling, and a backup story that doesn't depend on a single Fly volume.

**Trigger:** DuckDB write contention, need for multi-worker uvicorn, or >~20 active trainers on one volume.

**Ships:**

- Storage abstraction (`duckdb` + `postgres` backends; routes depend on interface, not driver)
- Alembic (or equivalent) migrations from current schema
- One-time DuckDB → Postgres import script
- Connection pooling; background job runner colocated or separate

**Garmin note:** Hosted Garmin sync requires **Garmin Health API** approval — apply early (weeks of lead time). Until then: upload-first + Strava OAuth (Phase 5).

**Operational glue (partially done / still open):**

- [x] Fly deployment configuration + health check + secret runbook
- [ ] GitHub Actions → `fly deploy` on tag or main
- [ ] Staging Fly app (separate volume, demo mode off)
- [ ] Litestream or scheduled volume snapshots
- [ ] Usage / error monitoring (Sentry, Plausible or similar)

**Effort:** Postgres migration ~2–3 weeks; ops polish ongoing.

---

## Phase 5 — Wearable integrations (hosted-safe)

**Goal:** Data flows without the trainer running local scripts or handing over passwords.

| Source | Approach | Priority |
| --- | --- | --- |
| Apple Health | Upload zip (shipped) | P0 |
| Strava | OAuth + webhook + nightly sync worker | P0 |
| Whoop | Partner API application | P1 |
| Garmin | Health API (not `python-garminconnect` in prod) | P1 — apply now |
| Manual session RPE | Mobile-friendly log form | P0 |

**Ships:**

- `integration_credentials` table (encrypted tokens per trainer)
- Scheduled sync jobs (Inngest, Trigger.dev, or Fly machine cron)
- "Last synced" surfaced on client header (UI stub exists — wire to real sync metadata)
- Upload pipeline → object storage (R2/S3) for large Apple Health exports, async parse

**Effort:** Strava OAuth ~1 week; full sync platform ~2–3 weeks.

---

## Phase 6 — Growth & billing

**Goal:** A trainer who hears about FitOntology can find it, try it, and pay within 10 minutes.

**Ships:**

- Marketing landing page (product story, demo link, pricing) — separate from the app shell
- Stripe Checkout — Starter (client cap) / Pro (unlimited); 14-day trial, no card required
- Enforce plan limits in `POST /api/clients` and integration connect flows
- Privacy policy + Terms of service linked from footer and sign-up
- Email automation: welcome, weekly digest ("3 clients flagged"), re-engagement
- Turn off public demo mode on the paid app hostname (keep demo on a `/try` subdomain or separate Fly app)

**Effort:** ~2–3 weeks including landing page copy and Stripe wiring.

---

## Phase 7 — Differentiation

**Goal:** Trainers choose FitOntology over TrueCoach / TrainHeroic / recovery-score apps.

**Already in the product:**

- Citation-backed reasoning with clickable signal methodology
- Plan-vs-execution loop + calibration adherence telemetry
- Per-client severity thresholds
- Coach Assistant draft (human-in-the-loop before send)

**Worth building next (pick one or two per quarter):**

- **Calibration → threshold suggestions** — wire `Suggestions` on `/calibration` to one-click threshold proposals
- **Anti-injury mode** — stricter defaults + UI for return-to-play clients (threshold plumbing exists)
- **Bulk Monday triage** — keyboard / swipe through roster accept-edit-reject without opening each client
- **Workout templates library** — push/pull/legs scaffolds as plan starting points
- **Apple sleep stages** — stage-level aggregation (README backlog item)
- **More ACSM rules in the table** — expand contraindication + progression coverage
- **Public read API** — roster + recommendations for trainers integrating booking / billing tools
- **Native client PWA** — Stage B of Phase 3, polished

**Risk:** Don't chase differentiation before Phase 2 beta feedback confirms which loops trainers actually use.

---

## Cross-cutting (ongoing)

- **Tests:** 330 today. Every phase adds regression tests, not just happy paths. Isolation + security tests are non-negotiable for multi-tenant changes.
- **Coverage:** CI uploads `coverage.xml`; aim for high coverage on `reasoning`, `db`, and route auth paths; UI can stay lighter.
- **Migrations:** Schema changes ship with idempotent DDL + data backfill (pattern in `db._run_migrations`).
- **Observability:** Structured logs from day one on Fly; add Sentry before opening public sign-up.
- **Cost discipline:** Track Anthropic usage per trainer (Ask + Coach draft) so pricing covers API burn.
- **Docs:** Keep `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, and this file aligned when shipping — stale roadmap text erodes trust faster than missing features.

---

## Open decisions

1. **Closed beta:** invite-only registration vs open sign-up with manual approval queue?
2. **Postgres timing:** migrate before or after first paying customer? (Recommend: after 5 active trainers if DuckDB stays quiet.)
3. **Pricing:** flat per-trainer vs tiered by client count?
4. **SSO:** add Google sign-in alongside password auth, or replace passwords in Phase 6?
5. **Demo hostname:** keep `DEMO_MODE` on production app vs separate `try.` subdomain when billing launches?
6. **Client portal monetization:** trainers-only billing (likely) vs optional client-paid tier (defer; schema should not block it).

**Resolved:**

- **Auth:** App-managed email/password + signed cookies (Phase 2b). Cloudflare Access is optional perimeter, not the app identity.
- **Host:** Fly.io first; Postgres when scale demands it.
- **Garmin in prod:** Unofficial library is dev/personal-only; Health API for hosted sync.

---

## What this roadmap is NOT

- A timeline — phases ship when ready.
- A spec — each phase gets a short design note when work starts.
- Frozen — friend test and beta feedback should reorder Phase 5–7 items.
