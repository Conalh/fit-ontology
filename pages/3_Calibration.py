"""Calibration — does the system agree with the trainer?

For each recommendation the trainer marks accept / edit / reject. This
page rolls those decisions up so the trainer can see, across their
whole roster, where the model lines up with practice and where it
doesn't. Three views, in order of usefulness:

  1. Overall acceptance rate + counts.
  2. Calibration matrix — for each recommendation TYPE the system
     produced, how often did the trainer accept / edit / reject? This
     is where systematic miscalibration shows up: e.g. "the system
     always says deload, but I accept it only 40% of the time."
  3. Recent decisions with notes — the qualitative trail. When the
     trainer rejected, what were they seeing that the model wasn't?

Edits are a partial signal: the trainer followed the direction but
chose a different magnitude. For those rows we surface the gap between
the system's prescribed load change and what the trainer actually did.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import streamlit as st

from fit_ontology.db import all_overrides, connect, list_clients


st.set_page_config(page_title="Calibration · FitOntology", page_icon="🧭", layout="wide")
st.title("Calibration")
st.caption("How often the system agrees with the trainer's actual decision.")


@st.cache_resource
def _open_db():
    return connect(read_only=True)


try:
    con = _open_db()
except FileNotFoundError:
    st.warning("No database yet. Seed it via the synthetic or Garmin scripts.")
    st.stop()


# ─── Pull overrides + client names ─────────────────────────────────────

overrides = all_overrides(con, limit=1000)
clients = list_clients(con)

if overrides.empty:
    st.info(
        "No trainer decisions logged yet. Open a client's dashboard and use "
        "**Record trainer decision** under the recommendation card to start "
        "building the calibration record."
    )
    st.stop()


# ─── Derive the recommendation TYPE from its text ──────────────────────
#
# The reasoning aggregator produces three flavors of text, all starting
# with the same word. We classify by that word rather than parsing the
# full string — robust to copy edits and the percentage drift.

def _classify(rec_text: str) -> str:
    low = rec_text.lower()
    if low.startswith("deload"):
        return "Deload"
    if low.startswith("conservative"):
        return "Conservative"
    if low.startswith("standard"):
        return "Standard"
    return "Other"


# The system's prescribed load change, as a signed percent. Hardcoded
# rather than re-imported because we want the value the system actually
# stated at the moment of the override, which lives in the text.
# Falls back to None if the text doesn't carry an obvious pct.
def _system_pct(rec_text: str) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", rec_text)
    if not m:
        return None
    pct = float(m.group(1))
    # The reasoning text uses "reduce ... by 20%" for deload — surface as -20.
    if "reduce" in rec_text.lower() or "deload" in rec_text.lower():
        pct = -abs(pct)
    return pct


overrides = overrides.copy()
overrides["system_type"] = overrides["system_recommendation"].apply(_classify)
overrides["system_pct"] = overrides["system_recommendation"].apply(_system_pct)
overrides = overrides.merge(
    clients[["id", "name"]].rename(columns={"id": "client_id", "name": "client_name"}),
    on="client_id",
    how="left",
)


# ─── Headline numbers ─────────────────────────────────────────────────

total = len(overrides)
accept_n = int((overrides["trainer_action"] == "accept").sum())
edit_n = int((overrides["trainer_action"] == "edit").sum())
reject_n = int((overrides["trainer_action"] == "reject").sum())
accept_rate = accept_n / total if total else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total decisions", total)
c2.metric("Accept rate", f"{accept_rate:.0%}")
c3.metric("Edits", edit_n)
c4.metric("Rejects", reject_n)


# ─── Calibration matrix ───────────────────────────────────────────────

st.subheader("Calibration matrix")
st.caption("Rows: what the system recommended. Columns: what the trainer did. Counts.")

ORDERED_TYPES = ["Deload", "Conservative", "Standard"]
ORDERED_ACTIONS = ["accept", "edit", "reject"]

matrix = pd.pivot_table(
    overrides,
    index="system_type",
    columns="trainer_action",
    values="id",
    aggfunc="count",
    fill_value=0,
)
# Re-index in fixed display order so cells are stable when sample sizes
# differ across categories.
matrix = matrix.reindex(index=[t for t in ORDERED_TYPES if t in matrix.index], fill_value=0)
matrix = matrix.reindex(columns=[a for a in ORDERED_ACTIONS if a in matrix.columns], fill_value=0)
matrix.columns = [c.capitalize() for c in matrix.columns]

if matrix.empty:
    st.info("Not enough data to build a calibration matrix yet.")
else:
    matrix_with_total = matrix.copy()
    matrix_with_total["Total"] = matrix.sum(axis=1)
    st.dataframe(matrix_with_total, use_container_width=True)

    # Per-row acceptance rate so the trainer sees the line "when system
    # said Deload, I accepted X%" directly.
    rates = []
    for rec_type in matrix.index:
        row_total = int(matrix.loc[rec_type].sum())
        accepts = int(matrix.loc[rec_type].get("Accept", 0))
        rates.append(
            {
                "System recommended": rec_type,
                "n": row_total,
                "Accept rate": f"{(accepts / row_total):.0%}" if row_total else "—",
            }
        )
    st.dataframe(pd.DataFrame(rates), use_container_width=True, hide_index=True)


# ─── Edit magnitude — system vs trainer ───────────────────────────────

edits = overrides[overrides["trainer_action"] == "edit"].copy()
edits = edits.dropna(subset=["applied_load_change_pct", "system_pct"])
if not edits.empty:
    st.subheader("Edit magnitude — system vs trainer")
    st.caption(
        "When the trainer edited rather than accepted, the gap between "
        "the system's prescribed load change and what they actually applied."
    )
    edits["delta_pct"] = edits["applied_load_change_pct"] - edits["system_pct"]
    edit_view = edits[
        ["client_name", "week_of", "system_type", "system_pct", "applied_load_change_pct", "delta_pct", "trainer_note"]
    ].rename(
        columns={
            "client_name": "Client",
            "week_of": "Week of",
            "system_type": "System type",
            "system_pct": "System %",
            "applied_load_change_pct": "Applied %",
            "delta_pct": "Δ (trainer − system)",
            "trainer_note": "Note",
        }
    )
    st.dataframe(edit_view, use_container_width=True, hide_index=True)


# ─── Recent decisions ─────────────────────────────────────────────────

st.subheader("Recent decisions")
recent = overrides.head(25).copy()
recent["created_at"] = pd.to_datetime(recent["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
recent_view = recent[
    ["created_at", "client_name", "week_of", "system_type", "trainer_action", "applied_load_change_pct", "trainer_note"]
].rename(
    columns={
        "created_at": "Logged",
        "client_name": "Client",
        "week_of": "Week of",
        "system_type": "System",
        "trainer_action": "Action",
        "applied_load_change_pct": "Applied %",
        "trainer_note": "Note",
    }
)
st.dataframe(recent_view, use_container_width=True, hide_index=True)
