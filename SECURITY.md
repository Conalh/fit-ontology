# Security

This document is the load-bearing security posture for FitOntology:
the threat model, what's defended and how, what's deliberately
out-of-scope, and how to report a vulnerability.

Companion to [ARCHITECTURE.md](ARCHITECTURE.md) (the *what*) — this
is the *adversarial what-if*.

---

## TL;DR

- **Cookie-session auth** (bcrypt + itsdangerous), HttpOnly +
  SameSite=Lax + Secure-gated, 14-day TTL.
- **Multi-tenant isolation** anchored on a db-layer chokepoint:
  every read helper filters on `trainer_id`, every write helper
  calls `_assert_clients_owned`. The upload and threshold routes add
  an early `_ensure_client` guard on top.
- **Append-only audit log** for every sensitive mutation, scoped
  per trainer, with action / target / IP / details JSON.
- **In-process rate limiting** on login (10/min per IP+email),
  Anthropic-quota-burning endpoints (30/min per trainer for /ask,
  20/hour each for share mint + intake mint + coach draft, and
  10/hour per IP on the public intake submit).
- **Defense-in-depth security headers** (X-Frame-Options,
  X-Content-Type-Options, Referrer-Policy, HSTS, CSP).
- **Public read-only demo mode** that returns 403 on every mutation,
  not 200-silent-no-op.
- **No DOS, supply-chain, or host-compromise defenses** — explicit
  out-of-scope, see below.

**To report a vulnerability:** see [Reporting](#reporting) at the
bottom.

---

## Threat model

### Actors

| Actor | Capabilities | Goal |
| --- | --- | --- |
| **Honest trainer** | Has a valid session cookie. | Read + mutate their own data. |
| **Honest visitor** | No cookie, visiting the hosted demo. | Read the demo trainer's pre-seeded data. |
| **Curious trainer** | Has a valid session cookie. Tries to read or mutate another trainer's data by guessing IDs or replaying URLs. | Read another trainer's data. |
| **Web attacker** | Can serve arbitrary HTML/JS at an external origin. Can craft links + forms. Cannot intercept TLS. | Steal a trainer's session via XSS / CSRF / clickjacking. |
| **Network attacker (off-path)** | Can observe TLS-encrypted traffic but not decrypt. | Replay attacks, traffic analysis. |
| **Malicious file upload** | Uploads a crafted wearable export expecting parser RCE / path traversal / zip-slip. | RCE on the server, exfiltrate other trainers' data. |
| **Compromised dependency** | A pip/npm package gets a malicious release. | RCE via the supply chain. |

### Trust boundaries

```
┌─────────────────────────────────────────────────────────────┐
│ untrusted                                                   │
│  ├─ public internet (TLS terminated at Fly's edge)          │
│  ├─ uploaded files (multipart bodies)                       │
│  └─ session cookies in flight                               │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTPS
┌────────────────────▼────────────────────────────────────────┐
│ semi-trusted                                                │
│  └─ session cookie (signed but client-held)                 │
│       trusted to ASSERT trainer_id; verified on every       │
│       request via itsdangerous signature check              │
└────────────────────┬────────────────────────────────────────┘
                     │ current_trainer_id resolves
┌────────────────────▼────────────────────────────────────────┐
│ trusted                                                     │
│  ├─ FastAPI process (single uvicorn, single user "app")     │
│  ├─ DuckDB file on the Fly volume                           │
│  └─ secrets in Fly's encrypted store (SESSION_SECRET,       │
│     ANTHROPIC_API_KEY, DEFAULT_TRAINER_PASSWORD)            │
└─────────────────────────────────────────────────────────────┘
```

The cookie crossing the semi-trusted boundary is the security-
critical seam. Every other piece of state is either signed
(cookies) or scoped to a trainer (DB rows).

### Attack surface

The exposed surface of a running deployment:

| Surface | Path | Public? | Auth? |
| --- | --- | --- | --- |
| Static HTML/JS/CSS | `/`, `/login`, `/clients?id=...`, etc. | Yes | No |
| Session login | `POST /api/auth/login` | Yes | Issues |
| Session logout | `POST /api/auth/logout` | Yes | Optional |
| Profile lookup | `GET /api/auth/me` | Yes | Yes (or demo) |
| Trainer API | `GET/POST/PATCH /api/clients/*`, etc. | Yes (trainer-scoped) | Yes (or demo for reads) |
| Public share view | `GET /api/share/{token}` | Yes | Token-only |
| Public intake preflight | `GET /api/intake/{token}` | Yes | Token-only |
| Public intake submit | `POST /api/intake/{token}` | Yes | Token-only |
| Conversational LLM | `POST /api/ask` | Yes | Yes |
| Coach Assistant draft | `POST /api/clients/{id}/coach-message/draft` | Yes | Yes |
| Health check | `GET /api/health` | Yes | No |

Anything else (Garmin sync, admin trainer CLI, `scripts/build_db.py`)
runs out-of-band over SSH — no HTTP surface.

---

## Defended classes

### Cross-tenant data access (read + write)

**Class:** Trainer A learns trainer B's `client_id` (a leaked URL,
shared PDF link, screenshot). Trainer A tries to read or mutate
trainer B's data.

**Defense, layer 1 — DB helpers.** Every read helper in `db.py`
takes `trainer_id` as the first data argument and filters on it.
Every write helper calls `_assert_clients_owned(con, trainer_id,
client_ids)` which raises `ValueError` if any `client_id` doesn't
belong to `trainer_id`. The route maps `ValueError → HTTP 404` (same
shape as "client doesn't exist," so the caller can't distinguish
"doesn't exist" from "exists but isn't yours").

**Defense, layer 2 — route-level early exit.** Read routes resolve
the client through a `trainer_id`-scoped query (`WHERE id = ? AND
trainer_id = ?`) and map an empty result to 404, so "another
trainer's client" reads identically to "no such client." The upload
(`metrics.py`) and threshold (`thresholds.py`) routes additionally
call `_ensure_client(con, trainer_id, client_id)` up front — they're
the paths where doing the work first would be wasteful (parsing a
multi-MB export) or would otherwise reach a write, so they bail to
404 before any of it.

**Why two layers:** the db-layer chokepoint is the guarantee — no
client-data write lands without an ownership assertion, even from a
future route that forgets to check. The `trainer_id`-scoped reads
and the `_ensure_client` early exits are the optimization: they turn
a cross-tenant attempt into a cheap 404 rather than letting it
travel all the way down to the chokepoint. The chokepoint alone is
sufficient for safety; the upfront checks make regressions cheaper.

**Tested by:** `tests/test_trainer_isolation.py` (chokepoint level),
`tests/test_api.py` (route level), `tests/test_security.py`
(cross-trainer GET / PATCH on lazy-persist routes).

### Session forgery + replay

**Class:** Attacker steals a session cookie, or forges one against
a guessed-secret.

**Defense.** The cookie is signed by `itsdangerous.URLSafeTimed-
Serializer` with `FIT_ONTOLOGY_SESSION_SECRET` (256+ bits of
entropy from `openssl rand -base64 48`). Signature verification
runs on every request via `decode_session(token)`. Forged or
tampered cookies fail verification → no `trainer_id` decoded → 401.
The signer's embedded timestamp enforces the 14-day TTL.

**Defense, cookie attributes:** `HttpOnly` (JS can't read it),
`SameSite=Lax` (cross-site form posts don't carry it), `Secure`
gated on `FIT_ONTOLOGY_SESSION_SECURE=1` (HSTS-paired in prod).
`Max-Age=14d`.

**Defense, transport:** TLS terminated at Fly's edge.
`Strict-Transport-Security: max-age=63072000` tells browsers to
refuse downgrade attempts on subsequent visits.

**Not defended:** an attacker who steals the cookie via local
device access. There's no second factor. The cookie is the
session.

**Tested by:** `tests/test_auth.py:test_session_rejects_tampered_-
cookie`, `tests/test_auth.py:test_session_rejects_cookie_signed_-
with_different_secret`.

### Cross-site request forgery (CSRF)

**Class:** Attacker hosts `evil.com` with a form auto-submitting to
`POST /api/clients` (creating an attacker-named client in the
trainer's account) or `/api/auth/logout` (logging them out).

**Defense.** `SameSite=Lax` on the session cookie. Cross-site form
POSTs don't carry the cookie, so the request lands at the API
without a session and 401s (with `REQUIRE_AUTH=1`) or falls into
demo mode (which 403s every mutation).

**Defense, depth:** `CORS allow_origins` is an allowlist, not `*`,
so a malicious origin can't even do a cross-origin fetch with
`credentials: "include"`.

**Not defended:** GET-side CSRF (information disclosure via
`<img src="/api/clients">`). Mitigated by CSP's `connect-src
'self'` blocking the browser from sending the request, plus the
fact that GET endpoints don't mutate state.

### Cross-site scripting (XSS)

**Class:** Attacker injects JavaScript via a trainer's input
(client name, override note, trainer_message on share, plan slot
title) that executes when another viewer renders it.

**Defense, layer 1 — React.** React escapes by default. No
`dangerouslySetInnerHTML` anywhere in the codebase. Every
user-provided string flows through `{value}` JSX expressions
which always escape.

**Defense, layer 2 — CSP.** `default-src 'self'`, `script-src
'self' 'unsafe-inline'` (Next.js static export forces inline; the
React safety + no-dangerously-set-innerHTML floor makes this
acceptable), `style-src 'self' 'unsafe-inline'`. `frame-ancestors
'none'` prevents clickjacking-based XSS variants. `object-src
'none'` removes the Flash/plugin XSS surface entirely. `base-uri
'self'` blocks `<base href="evil">` rewriting.

**Defense, layer 3 — strict report-only.** `FIT_ONTOLOGY_CSP_-
STRICT_REPORT=1` adds a second header
`Content-Security-Policy-Report-Only` with `script-src 'self'`
(no `'unsafe-inline'`). Telemetry for a future hardening pass to
nonce-based CSP.

**Tested by:** `tests/test_security.py:test_csp_*`.

### File-upload abuse (path traversal, zip-slip, parser RCE)

**Class:** Attacker uploads a crafted Apple Health zip with `../`
in entry names to escape the temp directory, or a malformed XML
that triggers parser exploits.

**Defense, path handling.** Uploads go to `tempfile.NamedTemporary-
File(suffix=...)` which generates a random name in the OS temp
dir. The original `file.filename` is never used as a path —
only the suffix is read to dispatch the right parser. The
file is unlinked in a `finally:` block.

**Defense, parser.** Apple Health XML parses via `xml.etree.-
ElementTree.iterparse` (no XXE — Python's stdlib parser doesn't
resolve external entities by default in 3.7+). The zip extractor
in `ingest.from_apple_health_export` uses `zipfile.ZipFile.open()`
with explicit member names from `namelist()` rather than calling
`extractall()` — no zip-slip surface.

**Defense, ownership.** The upload route runs `_ensure_client`
before parsing. An attacker who tricks the parser into producing
rows for a different client_id still hits the
`_assert_clients_owned` chokepoint when `insert_metrics` tries to
write — the cross-tenant defense in the previous section catches
this case.

### Authentication brute force

**Class:** Attacker enumerates passwords against `/api/auth/login`.

**Defense, rate limit.** 10 login attempts per minute per
(IP, email) pair. Both axes — IP-only locks out NAT'd users,
email-only lets stuffers rotate IPs against the same account.
Sliding-window deque in `rate_limit.py`. 429 attempts still count
toward the bucket so an attacker can't probe at the boundary.

**Defense, password storage.** bcrypt with cost factor 12 (~200ms
per verify on a shared-cpu-1x). Passwords trimmed and capped at
72 bytes before hashing (bcrypt's silent truncation made
explicit). Verification path has a uniform timing model — if no
account exists for the email, the helper still runs a dummy
bcrypt verify against a fixed hash to keep the response time
constant. Unknown-email and wrong-password both return identical
401s with no body difference.

**Tested by:** `tests/test_security.py:test_login_rate_limit_-
blocks_after_threshold`, `tests/test_auth.py:test_login_unknown_-
email_returns_401`.

### Anthropic API quota abuse

**Class:** Attacker (or a runaway front-end loop) drives `/api/ask`
or `/api/clients/{id}/coach-message/draft` in a tight loop to
exhaust the API budget.

**Defense.** `ASK_LIMIT` is 30 requests per minute per trainer;
`COACH_DRAFT_LIMIT` is 20 per hour per trainer. Separate buckets
so a chatty trainer doesn't lock themselves out of drafts.
Sliding-window deque, same primitive as login. The Anthropic
client's per-call max_tokens is capped (1024 for /ask, 400 for
coach draft).

### Audit-log tampering

**Class:** Attacker compromises a session, performs an action,
deletes the audit row to erase evidence.

**Defense.** There is no helper to delete from `audit_log`. The
only writer is `record_audit()`. The only reader is
`audit_log_for_trainer()` — which is trainer-scoped, so an
attacker can't even read another trainer's history. The schema
has no DELETE path the codebase exercises; a successful attack
would need direct DB access (host compromise — out of scope, see
below).

### Share-token leakage

**Class:** Attacker obtains a leaked share token and reads a
trainer's client's weekly data.

**Defense, posture.** This is by design — the share token is the
authorization. Leaking the token is equivalent to forwarding the
SMS the trainer sent. The mitigation is to keep tokens short-
lived (14 days default, configurable) and to rotate by re-issuing
new tokens (which doesn't revoke old ones — see
[ARCHITECTURE.md](ARCHITECTURE.md) for that decision).

**Defense, scope.** The public share payload is deliberately
narrow: client's first name, week's verdict, week's plan, trainer
message, expiry. No PII (sex, age, weight, injury history), no
other clients' data, no audit log, no override history. Pinned
by `tests/test_share.py:test_get_share_omits_pii`.

**Defense, transport.** All tokens travel over HTTPS; HSTS forces
the upgrade.

### Intake-token misuse

**Class:** Attacker obtains a leaked intake token and submits a
form, OR floods the public submit endpoint with garbage to spam
a trainer's roster.

**Defense, scope.** Intake tokens don't read any existing data —
the preflight `GET /api/intake/{token}` returns only the trainer's
display name, the optional welcome message, the expiry, and the
consumed flag. No client list, no internal IDs (the response
deliberately omits `trainer_id`), no metrics. Leaking a token only
exposes who minted it, not what they have.

**Defense, one-shot.** A submission flips `consumed_at` from NULL
to a timestamp via `UPDATE ... WHERE consumed_at IS NULL AND
expires_at >= ? RETURNING id`. The first POST wins; every
subsequent POST gets 410 (and the helper-level atomicity is also
pinned by `tests/test_intake_tokens.py:test_consume_is_atomic_-
single_claim`). A leaked link can onboard at most one client; the
trainer mints a fresh URL if they want to onboard another.

**Defense, atomicity.** Insert-client + consume-token run inside
one DuckDB transaction. A race-lost claim (two concurrent submits
on the same token) rolls back the insert so the trainer's roster
doesn't gain a stranded row from the losing request. Tested by
`tests/test_intake_public.py:test_submit_is_one_shot`.

**Defense, rate limit.** `INTAKE_SUBMIT_LIMIT = 10/hour per IP`
caps form-spam between mint and the legitimate submission. Keyed
on IP rather than trainer (the trainer isn't known until the
token resolves, and the threat is one-source flooding, not one-
trainer abuse). Mint itself is `INTAKE_MINT_LIMIT = 20/hour per
trainer`, same shape as `SHARE_MINT_LIMIT`.

**Defense, mint-time check.** `create_intake_token` verifies the
trainer row exists before writing. A typo in trainer_id (or a
race with a trainer-deletion) produces a clear ValueError at the
mint site rather than a dangling token whose submission would FK-
fail far from the cause.

**Defense, transport.** Same posture as share tokens — HTTPS +
HSTS in production.

### Demo-mode write attempts

**Class:** Public visitor (or a confused trainer) tries to mutate
the demo trainer's data.

**Defense, dependency.** Every mutating route uses
`Depends(forbid_demo_trainer)` instead of `Depends(current_-
trainer_id)`. The dependency runs `is_demo_trainer(trainer_id)`
and raises HTTP 403 with `"Demo mode is read-only. Run
FitOntology locally to save changes."`

**Defense, lazy-persist gate.** Routes that "write on first read"
(recommendation GET, plan GET) check `is_demo_trainer(trainer_id)`
before the persist branch and skip it for demo traffic. Demo
visitors still get a real verdict + plan rendered in memory —
the DB just doesn't grow.

**Tested by:** `tests/test_demo.py` (all 20 tests).

### Clickjacking

**Class:** Attacker embeds the trainer dashboard in an iframe on
`evil.com`, overlays a transparent button to trick clicks.

**Defense.** `X-Frame-Options: DENY` on every response, plus
CSP's `frame-ancestors 'none'`. Both are belt-and-suspenders —
X-Frame-Options for ancient browsers, frame-ancestors for
modern.

### Open redirect

**Class:** Attacker crafts `/login?next=https://evil.com` to
bounce a freshly-authenticated trainer off-site.

**Defense.** The login page's `safeNext(raw)` helper rejects
any `?next=` value that doesn't start with `/` or that starts
with `//` (protocol-relative). Default is `/`.

---

## Out of scope

These classes are explicitly *not* defended. A reviewer should
weigh them against your own threat model — most aren't relevant
for a portfolio or friend-test deployment, some would matter for
a real SaaS.

| Class | Why out of scope |
| --- | --- |
| **Denial of service** | Single-machine deployment; saturating it is trivially possible. Fly's edge has connection-rate limits; that's the floor. A real SaaS would add Cloudflare + autoscaling. |
| **Supply chain compromise** | `pyproject.toml` pins major versions, doesn't hash-lock. A future hardening pass could add `pip-tools` or `uv`'s lockfile + `dependency-review-action` in CI. The npm side has `package-lock.json`. |
| **Host / volume compromise** | An attacker with shell access to the Fly machine reads the DuckDB file directly. Encryption-at-rest beyond Fly's volume defaults is left for when the data warrants it (HIPAA-adjacent posture, multi-trainer SaaS). |
| **Side-channel attacks** | Timing channels are bounded by the bcrypt dummy-verify on auth, but data-dependent timing in query paths (e.g., "did this client exist?" via response timing) isn't normalized. Low real-world exploitability on a shared-cpu-1x with network jitter. |
| **Cryptographic agility / key rotation** | Single `FIT_ONTOLOGY_SESSION_SECRET`. No JWK rotation. Rotating invalidates every live session. Acceptable for solo deployment; SaaS would need overlapping secrets. |
| **Account recovery / 2FA** | No email-based reset flow. No TOTP. Admin CLI is the only recovery path (`scripts/trainer.py set-password`). |
| **GDPR data export + delete endpoints** | Not implemented. Phase 5c in [ROADMAP.md](ROADMAP.md). |
| **Pentest report** | None. Phase 5 in the roadmap, deferred until there's a real user base to defend. |

---

## Reporting

If you find something, please **don't** open a public GitHub issue.
Email the maintainer at the address in the repo's
`pyproject.toml` (the `authors` field) with:

1. A description of the vulnerability
2. The steps to reproduce
3. Any proof-of-concept (curl, browser, etc.)
4. Optional: how you think it should be fixed

I'll acknowledge within 48 hours. If it's confirmed, I'll work
on a fix and credit you in the commit message (or anonymously if
you prefer). Public disclosure timeline: 30 days from confirmation,
sooner if a patch is faster.

Out-of-scope reports (DOS findings, missing best-practice hardening,
items from the table above) are still welcome but won't get a
follow-up commit — they'll get a "thanks, here's the rationale"
reply.
