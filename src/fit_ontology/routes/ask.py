"""Ask FitOntology — Claude-powered conversational layer."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .schemas import AskRequest, AskResponse, AskTrace

router = APIRouter()


@router.post("/api/ask", response_model=AskResponse)
def post_ask(payload: AskRequest) -> AskResponse:
    """Run one turn of the Ask FitOntology tool-use loop.

    Wraps fit_ontology.assistant.ask(); the client passes back the
    prior turn's ``messages`` as ``history`` to keep multi-turn context
    (tool_use + tool_result blocks intact). Same model + system prompt
    + tool set as the Streamlit page used.
    """
    # Local import keeps the anthropic SDK optional at module-import time —
    # users without an API key can still run the rest of the API.
    from ..assistant import DEFAULT_MODEL, ask

    try:
        turn = ask(
            payload.question,
            history=payload.history or None,
            model=payload.model or DEFAULT_MODEL,
        )
    except RuntimeError as e:
        # ANTHROPIC_API_KEY missing — surface as 412 so the front-end
        # can show a meaningful "set your API key" message instead of
        # a generic 500.
        raise HTTPException(status_code=412, detail=str(e)) from e

    return AskResponse(
        answer=turn.answer,
        traces=[
            AskTrace(name=t.name, arguments=dict(t.arguments), result_summary=t.result_summary)
            for t in turn.traces
        ],
        turns_used=turn.turns_used,
        messages=turn.messages,
    )
