"""Streamlit dashboard — one page, one client at a time, full data trail."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import json

import pandas as pd
import streamlit as st

from fit_ontology.db import (
    connect,
    insert_recommendation,
    list_clients,
    metrics_for_client,
    sessions_for_client,
)
from fit_ontology.reasoning import generate_recommendation


st.set_page_config(page_title="FitOntology", layout="wide")
st.title("FitOntology")
st.caption("Client intelligence layer — wearables + intake + ACSM guidelines, unified.")

con = connect()
clients = list_clients(con)

if clients.empty:
    st.warning("No clients loaded. Run `python scripts/generate_synthetic.py` and "
               "`python scripts/build_db.py` first.")
    st.stop()

selected_label = st.sidebar.selectbox(
    "Client",
    options=[f"{r['name']} — {r['goal']}" for _, r in clients.iterrows()],
)
client_id = clients.iloc[
    [f"{r['name']} — {r['goal']}" for _, r in clients.iterrows()].index(selected_label)
]["id"]

st.sidebar.markdown(f"**ID:** `{client_id}`")

metrics = metrics_for_client(con, client_id, days=21)
sessions = sessions_for_client(con, client_id, days=21)

col_rec, col_metrics = st.columns([1, 2])

with col_rec:
    st.subheader("Recommendation")
    rec = generate_recommendation(client_id, metrics, sessions)
    insert_recommendation(con, rec)

    st.markdown(f"### {rec.recommendation}")
    st.progress(rec.confidence, text=f"Confidence: {rec.confidence:.0%}")
    st.markdown("**Rationale**")
    st.write(rec.rationale)
    with st.expander(f"Source metric IDs ({len(rec.source_metric_ids)})"):
        st.code("\n".join(rec.source_metric_ids) or "(none)", language="text")

with col_metrics:
    st.subheader("Last 21 days — wearable metrics")
    if metrics.empty:
        st.info("No metrics for this client.")
    else:
        pivot = metrics.pivot_table(index="date", columns="kind", values="value", aggfunc="mean")
        st.line_chart(pivot)
        with st.expander(f"Raw metrics ({len(metrics)} rows)"):
            st.dataframe(metrics, use_container_width=True)

st.subheader("Recent sessions")
if sessions.empty:
    st.info("No sessions for this client.")
else:
    st.dataframe(sessions, use_container_width=True)

st.divider()
st.caption(
    "Reasoning is explainable & rules-based — every recommendation traces "
    "back to a list of source metric IDs. ACSM 11th ed. progression guidance; "
    "HRV thresholds per Buchheit (2014)."
)
