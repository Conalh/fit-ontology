"""Streamlit chat page for the assistant.

Lives under ``pages/`` so Streamlit picks it up as a multi-page nav item.
The trainer asks questions; we surface every tool call inline so they
can see what data the assistant pulled before they trust the answer.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from fit_ontology.config import load_env  # noqa: E402

load_env(ROOT)

import streamlit as st  # noqa: E402

from fit_ontology.assistant import DEFAULT_MODEL, ask  # noqa: E402

st.set_page_config(page_title="Ask FitOntology", page_icon="💬", layout="wide")
st.title("Ask FitOntology")
st.caption(
    "Conversational layer over the ontology. The assistant calls the same "
    "reasoning engine the dashboard uses — every answer cites the tools it ran."
)


# ─── Sidebar: model + state controls ────────────────────────────────────

with st.sidebar:
    st.subheader("Settings")
    model = st.text_input("Model", value=DEFAULT_MODEL,
                          help="Anthropic model id. Defaults to Haiku for speed and cost; "
                               "set claude-opus-4-7 for harder questions.")
    api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if not api_key_set:
        st.error("ANTHROPIC_API_KEY is not set. Add it to .env and restart Streamlit.")

    if st.button("Clear conversation", use_container_width=True):
        st.session_state.pop("ask_messages", None)
        st.session_state.pop("ask_history", None)
        st.rerun()


# ─── Conversation state ────────────────────────────────────────────────

# `ask_messages` drives the visible chat panel (Streamlit-shaped entries).
# `ask_history` is the full Anthropic-format message stream that fed the
#  most recent assistant turn — text *and* tool_use *and* tool_result
#  blocks. We persist what ask() returns verbatim and pass it back next
#  call. Replacing simplified strings with the real message stream is
#  what makes multi-turn chat actually multi-turn: turn 2 sees the
#  numeric data that backed turn 1's answer instead of an opaque string.
if "ask_messages" not in st.session_state:
    st.session_state.ask_messages = []
if "ask_history" not in st.session_state:
    st.session_state.ask_history = []


# ─── Render prior messages ─────────────────────────────────────────────

for entry in st.session_state.ask_messages:
    with st.chat_message(entry["role"]):
        st.markdown(entry["text"])
        if entry.get("traces"):
            with st.expander(f"Tools used ({len(entry['traces'])})", expanded=False):
                for trace in entry["traces"]:
                    args_str = ", ".join(f"{k}={v!r}" for k, v in trace["arguments"].items()) or "—"
                    st.markdown(f"**{trace['name']}**(`{args_str}`) → {trace['result_summary']}")


# ─── Input ─────────────────────────────────────────────────────────────

prompt = st.chat_input("Ask about a client — e.g. 'what should I do with Ben this week?'")
if prompt:
    if not api_key_set:
        st.error("Can't send the question — no ANTHROPIC_API_KEY in the environment.")
        st.stop()

    st.session_state.ask_messages.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                turn = ask(
                    prompt,
                    history=st.session_state.ask_history,
                    model=model,
                )
            except Exception as e:  # noqa: BLE001 — surface anything to the user
                st.error(f"Assistant error: {e}")
                st.stop()

        st.markdown(turn.answer)
        if turn.traces:
            with st.expander(f"Tools used ({len(turn.traces)})", expanded=False):
                for trace in turn.traces:
                    args_str = ", ".join(f"{k}={v!r}" for k, v in trace.arguments.items()) or "—"
                    st.markdown(f"**{trace.name}**(`{args_str}`) → {trace.result_summary}")

    # Replace history with the full message stream the assistant
    # actually used — text, tool_use, tool_result blocks all preserved.
    st.session_state.ask_history = turn.messages

    st.session_state.ask_messages.append({
        "role": "assistant",
        "text": turn.answer,
        "traces": [
            {"name": t.name, "arguments": t.arguments, "result_summary": t.result_summary}
            for t in turn.traces
        ],
    })
