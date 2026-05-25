"""Coach Assistant — Claude-drafted client check-in messages (Phase 7a).

The trainer has the reasoning engine's verdict, recovery score, plan
adherence, and override history sitting in the DB. This module hands
all of that to Claude as a structured payload and asks for two or
three sentences a trainer would actually send. The trainer reviews
+ edits + sends; we don't auto-send anything — the value here is
"shape the prose," not "speak for the trainer."

Architectural choices worth flagging:

  - Separate file from assistant.py (the Ask FitOntology tool-use
    surface) on purpose. /ask is a multi-turn tool-using agent with
    its own system prompt + tool catalog; this is single-shot,
    no tools, focused output. Sharing the file would tangle two
    different prompt programs.

  - Payload is built from already-loaded objects (recommendation
    row, recovery score, etc.) rather than re-querying. The route
    layer assembles them once and we just shape the prompt.

  - We default to Haiku (cheap + fast) because the output is a
    two-sentence draft. The model env var FITONTOLOGY_COACH_MODEL
    is honored if the trainer wants to override.

  - max_tokens deliberately tight (400) — a draft that overflows
    that limit is too long for SMS / a check-in anyway, and the
    cap prevents a misbehaving model from burning quota.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = os.environ.get("FITONTOLOGY_COACH_MODEL", "claude-haiku-4-5-20251001")
MAX_TOKENS = 400


SYSTEM_PROMPT = """You are drafting a brief, warm check-in message from a personal trainer to one of their clients.

Voice and length:
- Address the client by their first name.
- 2-3 short sentences. SMS-length, not email-length. No subject line, no signoff.
- Conversational and direct. Trainers don't say "I noticed your HRV..." — they say "you've had a rough week" or "looking strong this stretch."
- Never robotic. Avoid bullet lists, headings, and percent signs unless the trainer's data clearly motivates one.

What to lead with, in priority order:
1. If the data shows an adherence problem (matched_slots < total_slots, or load_delta is negative and large), open with a gentle re-engagement note — no guilt-tripping.
2. If the verdict is "Deload" or "Conservative" — lead with the recovery picture and the suggested adjustment.
3. Otherwise — open positively about how the week is shaping up.

Output rules:
- Plain text. No markdown.
- Don't invent specifics that aren't in the payload (no specific HRV values, no "your sleep was 5.4 hours" — work in qualitative terms unless the payload has the literal figure).
- If you reference a number that IS in the payload (recovery_score, total/matched plan slots), state it as the trainer would in conversation, not as a stat dump.
- If the trainer's recent_overrides show they rejected or edited a similar recommendation before, write in a way that respects that pattern (don't push hard on a call you know they'd push back on)."""


@dataclass
class CoachDraft:
    """Result of one draft request — just the text plus which model
    produced it (so the front-end can show a small "drafted by X"
    affordance if it wants)."""
    draft: str
    model: str


def build_coach_draft_payload(
    client_name: str,
    client_goal: str,
    recommendation: str,
    rationale: str,
    confidence: float,
    recovery_score: dict[str, Any] | None,
    plan_adherence: dict[str, Any] | None,
    recent_overrides: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Shape the structured payload that gets serialized into the user
    prompt. Kept as a pure function so a test can pin the exact shape
    and so a future "show me the prompt" debug surface can render
    the payload without re-running it through Claude.

    Field semantics:
      - first_name        used by the prompt as the addressee
      - goal              the client's stated training goal (e.g.
                          "half marathon Q3"); helps Claude pick a
                          context-appropriate tone
      - verdict           the recommendation's plain-English text
      - rationale         the engine's audit trail (kept short by
                          the reasoning layer)
      - confidence        0..1; lets Claude calibrate hedging
      - recovery          composite + per-component, all 0..100 or
                          null when no signal
      - adherence         plan-vs-execution snapshot for this week:
                          matched_slots / total_slots / load_delta_pct
                          (None when no plan exists yet)
      - recent_overrides  last ~3 trainer decisions (action + note +
                          week) so Claude doesn't pitch something
                          the trainer just rejected
    """
    first_name = (client_name or "").split(" ", 1)[0] or "there"
    return {
        "first_name": first_name,
        "goal": client_goal,
        "verdict": recommendation,
        "rationale": rationale,
        "confidence": round(float(confidence), 2),
        "recovery": recovery_score,
        "adherence": plan_adherence,
        "recent_overrides": (recent_overrides or [])[:3],
    }


def draft_coach_message(
    payload: dict[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> CoachDraft:
    """Hand the payload to Claude and return the draft text.

    Raises ``RuntimeError`` when no API key is configured — same
    contract as ``assistant.ask`` so the route layer maps both to
    HTTP 412 with one ``except RuntimeError`` clause.
    """
    import anthropic  # local import keeps the SDK optional at module load

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or your environment."
        )

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            # The system prompt is identical across every draft, so
            # mark it cacheable — repeat drafts within the cache
            # window cost ~10% as much.
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{
            "role": "user",
            "content": "Here's this week's snapshot. Draft the check-in.\n\n"
                       + json.dumps(payload, indent=2, default=str),
        }],
    )

    # Concatenate every text block — Anthropic occasionally splits a
    # response across multiple text content blocks even without tools.
    text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return CoachDraft(draft=text, model=model)
