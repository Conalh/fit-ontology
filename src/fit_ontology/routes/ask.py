"""Ask FitOntology — Claude-powered conversational layer."""
from __future__ import annotations

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from ..db import (
    DEFAULT_DB_PATH,
    connect,
    create_ask_session,
    load_ask_session,
    update_ask_session,
)
from ..rate_limit import ASK_LIMIT, enforce
from .deps import forbid_demo_trainer
from .schemas import ASK_SESSION_MAX_MESSAGES, AskRequest, AskResponse, AskTrace

router = APIRouter()


@router.post("/api/ask", response_model=AskResponse)
def post_ask(
    payload: AskRequest,
    trainer_id: str = Depends(forbid_demo_trainer),
) -> AskResponse:
    """Run one turn of the Ask FitOntology tool-use loop.

    Multi-turn context lives server-side: the client passes back only the
    ``session_id`` from the prior turn, and the full Anthropic message
    stream (tool_use + tool_result blocks intact) is loaded from the
    ask_sessions table rather than trusted from the request body. Omit
    session_id to start a fresh conversation; the response carries the id
    to continue it. trainer_id scopes both the tool calls and the session
    lookup, so the assistant can only ever see this trainer's data and a
    session_id is only resolvable by the trainer that owns it.

    Rate-limited per trainer (see rate_limit.ASK_LIMIT) — the real threat
    here is a runaway loop in the front-end burning Anthropic API quota,
    not abusive humans.
    """
    enforce(ASK_LIMIT, trainer_id)
    # Local import keeps the anthropic SDK optional at module-import time —
    # users without an API key can still run the rest of the API.
    from ..assistant import DEFAULT_MODEL, ask

    # Load prior history server-side. We never accept it from the client,
    # so a tampered browser can't inject fake tool_result / assistant
    # context into the model's view of the conversation.
    if payload.session_id:
        try:
            with connect(DEFAULT_DB_PATH, read_only=True) as rcon:
                history = load_ask_session(rcon, trainer_id, payload.session_id)
        except duckdb.IOException as e:
            raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e
        if history is None:
            # Unknown id, or another trainer's id — same 404 either way.
            raise HTTPException(status_code=404, detail="Chat session not found")
        session_id: str | None = payload.session_id
    else:
        history = []
        session_id = None

    if len(history) >= ASK_SESSION_MAX_MESSAGES:
        raise HTTPException(
            status_code=409,
            detail="This conversation is too long; start a new one.",
        )

    try:
        turn = ask(
            payload.question,
            trainer_id=trainer_id,
            history=history or None,
            model=payload.model or DEFAULT_MODEL,
        )
    except RuntimeError as e:
        # ANTHROPIC_API_KEY missing — surface as 412 so the front-end
        # can show a meaningful "set your API key" message instead of
        # a generic 500.
        raise HTTPException(status_code=412, detail=str(e)) from e

    # Persist the updated stream server-side. A new conversation mints its
    # row here (only after the turn succeeds, so a failed turn doesn't
    # leave an empty session behind).
    try:
        with connect(DEFAULT_DB_PATH, read_only=False) as wcon:
            if session_id is None:
                session_id = create_ask_session(wcon, trainer_id, turn.messages)
            else:
                update_ask_session(wcon, trainer_id, session_id, turn.messages)
    except duckdb.IOException as e:
        raise HTTPException(status_code=503, detail=f"DB busy: {e}") from e

    return AskResponse(
        answer=turn.answer,
        traces=[
            AskTrace(name=t.name, arguments=dict(t.arguments), result_summary=t.result_summary)
            for t in turn.traces
        ],
        turns_used=turn.turns_used,
        session_id=session_id,
    )
