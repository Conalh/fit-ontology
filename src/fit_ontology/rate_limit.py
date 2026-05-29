"""In-process sliding-window rate limiter (Phase 5a).

Single-file, no dependencies, suitable for a single-uvicorn-worker
deploy. When the app moves to multi-process (Phase 4 / Phase 6), swap
the storage backend for Redis + slowapi — every call site here uses
the same ``enforce`` API, so the swap is one file.

Why not slowapi today: at the current scale (one process) the
decorator-flavored API would buy us very little, and slowapi's
storage abstraction (limits.storage) means picking a backend now
when we don't yet know whether Phase 4 lands on Fly + LiteFS (no
Redis) or on something Postgres-shaped (where slowapi's Postgres
storage is fine). Defer the choice; keep the API call-sites stable.

Why sliding-window not token-bucket: the failure mode we care about
is "burst of 30 login attempts in 5 seconds, then nothing." A token
bucket with refill rate of N/minute permits that burst if it
matches the bucket size. A sliding window over the last minute
counts each attempt against the same limit regardless of when in
the window it landed, which is what an admin reading "10 attempts
per minute" expects.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException


@dataclass
class RateLimit:
    """Config for one named limiter. ``key_extra`` lets a route narrow
    the bucket beyond IP — login uses (ip, email) so a stuffer who
    rotates IPs is still rate-limited per email, and so an office NAT
    doesn't lock out one user when another tries to log in."""
    window_seconds: int
    max_attempts: int
    name: str


# All buckets live in a single module-level dict so monkeypatching for
# tests can clear it in one line; keys are (limiter_name, identity).
_buckets: dict[tuple[str, str], deque] = defaultdict(deque)
_lock = Lock()

# limit.name → window_seconds, recorded on first enforce() so the GC
# sweep can use each bucket's own window. A single global cutoff would
# be wrong: login's window is 60s but the mint limiters are 3600s, so a
# global 60s cutoff would evict live mint buckets.
_windows: dict[str, int] = {}

# Opportunistic GC threshold. The login limiter's identity embeds an
# attacker-controllable email, so a credential-stuffing run mints a
# fresh key per address and _buckets would grow without bound (each
# deque is tiny, but the dict isn't). When the key count crosses this,
# enforce() sweeps out every bucket whose newest entry has already aged
# past its own window — those evict to empty on next touch anyway, so
# dropping them changes no limit decision. Set high enough that normal
# traffic (one key per active trainer + a handful of login pairs) never
# triggers a sweep.
_GC_THRESHOLD = 10_000


def _gc_locked(now: float) -> None:
    """Drop buckets that have aged out of their window. Caller holds
    ``_lock``; invoked opportunistically from ``enforce`` when
    ``_buckets`` crosses ``_GC_THRESHOLD`` keys."""
    stale = [
        key
        for key, bucket in _buckets.items()
        if not bucket or bucket[-1] < now - _windows.get(key[0], 0)
    ]
    for key in stale:
        del _buckets[key]


def enforce(limit: RateLimit, identity: str) -> None:
    """Check + record one attempt against ``limit`` for ``identity``.

    Raises HTTPException(429) if the bucket is full. The "record"
    happens before the raise so a rejected attempt still counts —
    otherwise an attacker could probe right at the boundary forever.

    Lock-protected because uvicorn with --workers 1 still uses an
    event-loop + threadpool, and the deque mutations would race
    without it. The lock is held for microseconds (deque eviction +
    append); no contention in practice.
    """
    now = time.monotonic()
    cutoff = now - limit.window_seconds
    key = (limit.name, identity)
    with _lock:
        _windows[limit.name] = limit.window_seconds
        if len(_buckets) > _GC_THRESHOLD:
            _gc_locked(now)
        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit.max_attempts:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Try again in a moment.",
            )
        bucket.append(now)


def reset() -> None:
    """Test helper — clear every bucket. Production never calls this."""
    with _lock:
        _buckets.clear()


# ─── Named limits ────────────────────────────────────────────────────
#
# Each limit is declared once here and imported by the routes that
# enforce it. Centralized so the admin can see every limit + its
# rationale in one place rather than chasing decorators across files.

LOGIN_LIMIT = RateLimit(
    name="auth.login",
    window_seconds=60,
    max_attempts=10,
)
"""10 login attempts per minute per (IP, email) pair. Both axes
because IP-only locks out shared NAT and email-only lets a
credential stuffer rotate IPs through the same account."""

ASK_LIMIT = RateLimit(
    name="ask",
    window_seconds=60,
    max_attempts=30,
)
"""30 Ask FitOntology requests per minute per trainer. The real
constraint here is the Anthropic API quota + bill, not abuse —
no human types 30 questions in a minute. Trips well before a
runaway loop in the front-end drains the budget."""

SHARE_MINT_LIMIT = RateLimit(
    name="share.mint",
    window_seconds=3600,
    max_attempts=20,
)
"""20 share-token mints per hour per trainer. An accidental
click-loop (double-bound button, etc.) is the main case — a real
trainer mints maybe one link per client per week."""

COACH_DRAFT_LIMIT = RateLimit(
    name="coach.draft",
    window_seconds=3600,
    max_attempts=20,
)
"""20 coach-message drafts per hour per trainer. Separate from
ASK_LIMIT so chatting in /ask doesn't lock the trainer out of
drafting check-ins (or vice versa). At ~$0.001 per Haiku draft
this is also a soft floor on the per-hour API spend."""

INTAKE_MINT_LIMIT = RateLimit(
    name="intake.mint",
    window_seconds=3600,
    max_attempts=20,
)
"""20 intake-link mints per hour per trainer. Same shape as
SHARE_MINT_LIMIT — the case is an accidental click-loop or double-
bound button, not adversarial. A real trainer mints maybe one
intake link per new client per week."""

INTAKE_SUBMIT_LIMIT = RateLimit(
    name="intake.submit",
    window_seconds=3600,
    max_attempts=10,
)
"""10 intake submissions per hour per IP. The other limits in this
file are keyed by trainer_id because the route is authed; intake
submit is the only public-write surface and the trainer isn't
known until the token resolves. Per-IP is the natural bucket: a
legitimate client submits once, full stop. The cap defends against
form-spam against a leaked link before the one-shot consume kicks
in (one valid submission claims the token, but a flood between
"trainer minted" and "client submitted" could DoS the surface)."""
