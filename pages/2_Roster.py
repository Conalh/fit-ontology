"""Roster — Monday-morning triage view across all clients.

For each client we run the same reasoning the per-client dashboard uses,
then rank the table by recommendation urgency. A trainer should be able
to open this page, look at the top, and know who to call first.

Stale clients (no metrics in the last 7 days) are grouped separately so
they don't get a misleading "standard progression" label from absence of
data. A signal absent because the wearable hasn't synced is not the same
as a signal absent because the client is well-recovered.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
import streamlit as st

from fit_ontology.db import (
    connect,
    list_clients,
    metrics_for_client,
    sessions_for_client,
)
from fit_ontology.reasoning import generate_recommendation


STALE_DATA_DAYS = 7


st.set_page_config(page_title="Roster · FitOntology", page_icon="🧭", layout="wide")
st.title("Roster")
st.caption("All clients at a glance — ranked by recommendation urgency.")


try:
    con = connect(read_only=True)
except FileNotFoundError:
    st.warning(
        "No database yet. Run `python scripts/generate_synthetic.py && "
        "python scripts/build_db.py` for demo data, or `python scripts/sync_garmin.py`."
    )
    st.stop()

clients = list_clients(con)
if clients.empty:
    st.info("No clients in the database yet.")
    st.stop()


def _label(rec_text: str) -> str:
    low = rec_text.lower()
    if low.startswith("deload"):
        return "Deload"
    if low.startswith("conservative"):
        return "Conservative"
    return "Standard"


RANK = {"Deload": 0, "Conservative": 1, "Standard": 2, "No recent data": 3}


rows: list[dict] = []
today = pd.Timestamp(date.today())

for _, client in clients.iterrows():
    cid = client["id"]
    metrics = metrics_for_client(con, cid, days=28)
    sessions = sessions_for_client(con, cid, days=28)

    if metrics.empty:
        last_days = None
    else:
        last_days = int((today - pd.to_datetime(metrics["date"]).max()).days)

    # Stale data: don't run reasoning — the absence of signals would
    # otherwise read as "everything is fine."
    if last_days is None or last_days > STALE_DATA_DAYS:
        label = "No recent data"
        flags = "—"
        sources_n = 0
        confidence = None
    else:
        rec = generate_recommendation(cid, metrics, sessions)
        label = _label(rec.recommendation)
        flags = "—"
        if "Flags:" in rec.rationale:
            flags = rec.rationale.split("Flags:", 1)[1].strip().rstrip(".") or "—"
        sources_n = len(rec.source_metric_ids)
        confidence = rec.confidence

    rows.append(
        {
            "Client": client["name"],
            "Goal": client["goal"],
            "Recommendation": label,
            "Flags": flags,
            "Sources": sources_n,
            "Confidence": confidence,
            "Last data": last_days,
            "_rank": RANK[label],
            "_id": cid,
        }
    )

roster = pd.DataFrame(rows).sort_values(
    ["_rank", "Confidence", "Last data"],
    ascending=[True, False, True],
).reset_index(drop=True)


# ─── Counts row ────────────────────────────────────────────────────────

counts = roster["Recommendation"].value_counts().to_dict()
c1, c2, c3, c4 = st.columns(4)
c1.metric("Deload", counts.get("Deload", 0))
c2.metric("Conservative", counts.get("Conservative", 0))
c3.metric("Standard", counts.get("Standard", 0))
c4.metric("No recent data", counts.get("No recent data", 0))


# ─── Table ─────────────────────────────────────────────────────────────

display = roster.drop(columns=["_rank", "_id"]).copy()
display["Confidence"] = display["Confidence"].apply(
    lambda v: "—" if v is None or pd.isna(v) else f"{int(round(v * 100))}%"
)
display["Last data"] = display["Last data"].apply(
    lambda d: "—" if d is None or (isinstance(d, float) and pd.isna(d)) else f"{int(d)}d ago"
)

st.dataframe(display, use_container_width=True, hide_index=True)


# ─── Open a client's detail page ──────────────────────────────────────

st.divider()
nav, btn = st.columns([3, 1])
with nav:
    options = roster["Client"].tolist()
    selected_name = st.selectbox(
        "Open detail",
        options,
        label_visibility="collapsed",
    )
with btn:
    if st.button("Open →", use_container_width=True):
        cid = roster.loc[roster["Client"] == selected_name, "_id"].iloc[0]
        st.query_params["client"] = cid
        st.switch_page("app.py")
