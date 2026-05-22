"""
"Ask FitOntology" — a Claude-powered conversational layer over the
ontology, the metrics, and the reasoning engine.

The trainer asks a question in natural language (e.g. "what should I do
with Ben this week?"). We hand it to Claude with five tools that read
the same ontology the dashboard uses. Claude picks tools, we execute
them against DuckDB, we feed the results back, Claude eventually
answers in plain language with the specific numbers it pulled.

Architectural choices worth flagging:

  - The system prompt is static across every turn, so we tag it with
    cache_control: {type: 'ephemeral'} for prompt caching. Repeat
    questions within a session hit the cache and cost ~10% as much.

  - Tool use is enforced via Anthropic's structured-output tool calls,
    not free-form JSON parsing. The model returns tool_use blocks that
    we route to our Python functions; results go back as tool_result.

  - The loop bounds itself at MAX_TURNS so a misbehaving model can't
    rack up infinite tool calls.

  - Tools are read-only. The assistant never writes. Recommendations
    are computed on demand and returned in-memory; persistence lives
    in the sync script, not the chat.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .db import (
    DEFAULT_DB_PATH,
    connect,
    list_clients,
    metrics_for_client,
    sessions_for_client,
)
from .reasoning import generate_recommendation


DEFAULT_MODEL = os.environ.get("FITONTOLOGY_MODEL", "claude-haiku-4-5-20251001")
MAX_TURNS = 8           # cap tool-use loop length so we can't infinite-loop
MAX_TOKENS = 1024


SYSTEM_PROMPT = """You are FitOntology's assistant. You help a personal trainer reason about their clients' training week using only the data the tools return — never invent numbers, never guess at metrics the tools didn't surface.

Domain vocabulary you should use naturally:
  - HRV (RMSSD), resting HR drift, sleep score (Garmin 0–100), Body Battery, Training Readiness
  - Acute:Chronic Workload Ratio (ACWR) from session-RPE × duration (Foster sRPE; Gabbett sweet spot 0.8–1.3)
  - HRV vs 28-day baseline in SD units (Plews & Laursen)
  - ACSM 11e progression: 5–10% weekly when recovery is clean; deload every 4–6 weeks

How to answer:
  - Lead with the recommendation, then the specific numbers that drove it.
  - If a question is about a single client, call get_client_summary then compute_recommendation. Only pull raw metrics or sessions if the trainer asks why or wants detail.
  - If a question is across all clients (e.g. "who needs a deload?"), call list_clients then compute_recommendation per client.
  - If you don't have data, say so. Don't fabricate.
  - Keep responses tight — one short paragraph or a small list, not an essay."""


TOOLS: list[dict] = [
    {
        "name": "list_clients",
        "description": "List all clients in the practice with their id, name, and stated goal. Use this first if the question is across multiple clients or the trainer mentions a name you haven't seen.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_client_summary",
        "description": "Get one client's intake summary (sex, age, height, weight, goal, injury history). Use this when you need basic context about a client before pulling metrics.",
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string", "description": "The client's id, e.g. 'c_ben'."}},
            "required": ["client_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recent_metrics",
        "description": "Pull recent wearable metrics for a client. Returns daily HRV, sleep, resting HR, Body Battery, etc. — whatever the trainer has loaded. Use when a question is about recovery markers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 60, "default": 21},
            },
            "required": ["client_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_recent_sessions",
        "description": "Pull recent training sessions for a client (type, duration, RPE, date). Use when a question is about training load, ACWR, or what the client did.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 60, "default": 21},
            },
            "required": ["client_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "compute_recommendation",
        "description": "Run the reasoning engine for a client. Returns a recommendation (deload / conservative / standard progression), a confidence, a rationale citing each signal that fired, and the source metric IDs. Use this whenever the trainer asks 'what should I do' or 'should I push this week'.",
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class ToolTrace:
    """One executed tool call, captured so the UI can show what data fed
    the assistant's answer."""
    name: str
    arguments: dict[str, Any]
    result_summary: str


@dataclass
class AssistantTurn:
    """Result of one user question."""
    answer: str
    traces: list[ToolTrace] = field(default_factory=list)
    turns_used: int = 0


# --- Tool implementations ------------------------------------------------

def _df_brief(df: pd.DataFrame, max_rows: int = 30) -> str:
    """Serialize a DataFrame compactly for tool output. We cap row count
    so a huge metrics pull doesn't blow the model's context window."""
    if df.empty:
        return "(no rows)"
    if len(df) > max_rows:
        df = df.tail(max_rows)
        prefix = f"(showing most recent {max_rows} rows)\n"
    else:
        prefix = ""
    return prefix + df.to_csv(index=False)


def _tool_list_clients(db_path: Path) -> str:
    con = connect(db_path, read_only=True)
    clients = list_clients(con)
    con.close()
    if clients.empty:
        return "(no clients in the database)"
    return clients.to_csv(index=False)


def _tool_get_client_summary(db_path: Path, client_id: str) -> str:
    con = connect(db_path, read_only=True)
    row = con.execute(
        "SELECT id, name, sex, age, height_cm, weight_kg, goal, injury_history FROM clients WHERE id = ?",
        [client_id],
    ).df()
    con.close()
    if row.empty:
        return f"(no client with id {client_id})"
    return row.to_csv(index=False)


def _tool_get_recent_metrics(db_path: Path, client_id: str, days: int = 21) -> str:
    con = connect(db_path, read_only=True)
    df = metrics_for_client(con, client_id, days=days)
    con.close()
    return _df_brief(df)


def _tool_get_recent_sessions(db_path: Path, client_id: str, days: int = 21) -> str:
    con = connect(db_path, read_only=True)
    df = sessions_for_client(con, client_id, days=days)
    con.close()
    return _df_brief(df)


def _tool_compute_recommendation(db_path: Path, client_id: str) -> str:
    con = connect(db_path, read_only=True)
    metrics = metrics_for_client(con, client_id, days=35)   # 28d baseline window + slack
    sessions = sessions_for_client(con, client_id, days=35)
    con.close()
    rec = generate_recommendation(client_id, metrics, sessions)
    return json.dumps({
        "recommendation": rec.recommendation,
        "rationale": rec.rationale,
        "confidence": round(rec.confidence, 2),
        "week_of": rec.week_of.isoformat(),
        "source_metric_count": len(rec.source_metric_ids),
    })


def _execute_tool(name: str, arguments: dict[str, Any], db_path: Path) -> str:
    if name == "list_clients":
        return _tool_list_clients(db_path)
    if name == "get_client_summary":
        return _tool_get_client_summary(db_path, arguments["client_id"])
    if name == "get_recent_metrics":
        return _tool_get_recent_metrics(db_path, arguments["client_id"], arguments.get("days", 21))
    if name == "get_recent_sessions":
        return _tool_get_recent_sessions(db_path, arguments["client_id"], arguments.get("days", 21))
    if name == "compute_recommendation":
        return _tool_compute_recommendation(db_path, arguments["client_id"])
    return f"(unknown tool: {name})"


def _summarize_result(name: str, result: str) -> str:
    """Short, human-readable description of a tool result for the UI
    trace. We don't include the full payload — that's already in the
    model's context."""
    if name == "list_clients":
        lines = result.strip().split("\n")
        return f"listed {max(0, len(lines) - 1)} clients"
    if name == "compute_recommendation":
        parsed = json.loads(result)
        return parsed.get("recommendation", "(no recommendation)")
    if "(no" in result.lower() and "rows" in result.lower():
        return "no data returned"
    line_count = result.count("\n")
    return f"returned {line_count} rows" if line_count else "returned 1 row"


# --- Conversation loop ---------------------------------------------------

def ask(
    question: str,
    *,
    history: Iterable[dict] | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
) -> AssistantTurn:
    """Ask one question and run the tool-use loop to completion.

    ``history`` is a list of prior message dicts (in Anthropic Messages
    format) so a multi-turn chat can persist context. Pass None for a
    fresh conversation.
    """
    import anthropic  # local import keeps the package importable without the SDK

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env or your environment.")

    client = anthropic.Anthropic(api_key=api_key)

    messages: list[dict] = list(history or [])
    messages.append({"role": "user", "content": question})

    traces: list[ToolTrace] = []
    turns = 0

    while turns < MAX_TURNS:
        turns += 1
        response = client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            tools=TOOLS,
            messages=messages,
        )

        assistant_blocks = [block.model_dump() for block in response.content]
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            answer_text = "".join(b.text for b in response.content if b.type == "text").strip()
            return AssistantTurn(answer=answer_text, traces=traces, turns_used=turns)

        # Execute every tool the model requested, then send all results
        # back as a single user-role tool_result message.
        tool_results: list[dict] = []
        for block in tool_use_blocks:
            result = _execute_tool(block.name, block.input, db_path)
            traces.append(ToolTrace(
                name=block.name,
                arguments=block.input,
                result_summary=_summarize_result(block.name, result),
            ))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    return AssistantTurn(
        answer="(no answer — turn limit reached)",
        traces=traces,
        turns_used=turns,
    )
