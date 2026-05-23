"""FitOntology — desktop dashboard.

Two-column layout per client:
  - Left: today's status cards (Training Readiness, HRV last night,
    sleep, resting HR, Body Battery) with week-over-week deltas.
  - Right: 14-day trend sparklines and the reasoning recommendation
    with full source-data trail.

Every chart is built from the same long-format metrics table so adding
a new wearable signal means one ingest adapter and no dashboard work.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd
import streamlit as st

from fit_ontology.db import (
    connect,
    list_clients,
    metrics_for_client,
    sessions_for_client,
)
from fit_ontology.ontology import MetricKind
from fit_ontology.reasoning import generate_recommendation


st.set_page_config(
    page_title="FitOntology",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; padding-bottom: 2rem; }
      [data-testid="stMetricValue"] { font-size: 1.6rem; }
      [data-testid="stMetricLabel"] { font-size: 0.85rem; color: #475569; }
      .rec-card {
        border-radius: 10px;
        padding: 18px 20px;
        background: linear-gradient(135deg, #1e3a8a 0%, #1e293b 100%);
        color: #f1f5f9;
        margin-bottom: 12px;
      }
      .rec-card h3 { color: #f1f5f9; margin: 0 0 6px 0; font-weight: 600; }
      .rec-card .rationale { color: #cbd5e1; font-size: 0.92rem; line-height: 1.5; }
      .rec-card .confidence { color: #94a3b8; font-size: 0.78rem; margin-top: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─── Data layer ────────────────────────────────────────────────────────

try:
    con = connect(read_only=True)
except FileNotFoundError:
    st.title("FitOntology")
    st.warning(
        "No database yet. Run `python scripts/generate_synthetic.py && "
        "python scripts/build_db.py` for demo data, or `python scripts/sync_garmin.py` "
        "to pull from your Garmin Connect account."
    )
    st.stop()

clients = list_clients(con)
if clients.empty:
    st.title("FitOntology")
    st.warning("Database opened but contains no clients yet. Seed it with the synthetic or Garmin sync scripts.")
    st.stop()


# ─── Header ────────────────────────────────────────────────────────────

col_title, col_picker = st.columns([3, 2])
with col_title:
    st.title("FitOntology")
    st.caption("Client intelligence — wearables, intake, and ACSM guidelines unified.")
with col_picker:
    options = [f"{r['name']} — {r['goal']}" for _, r in clients.iterrows()]
    # Honor `?client=<id>` from the Roster page so clicking through opens
    # the right client. Falls back to first client when the param is missing
    # or points to an unknown id.
    preselect_id = st.query_params.get("client")
    default_idx = 0
    if preselect_id:
        matches = clients.index[clients["id"] == preselect_id].tolist()
        if matches:
            default_idx = int(matches[0])
    selected = st.selectbox("Client", options, index=default_idx, label_visibility="collapsed")
    client_id = clients.iloc[options.index(selected)]["id"]


# ─── Pull metrics ──────────────────────────────────────────────────────

metrics = metrics_for_client(con, client_id, days=21)
sessions = sessions_for_client(con, client_id, days=21)


def _latest(kind: str) -> float | None:
    sub = metrics[metrics["kind"] == kind].sort_values("date")
    return float(sub["value"].iloc[-1]) if not sub.empty else None


def _week_delta(kind: str) -> float | None:
    """Mean over the most recent 7 days vs the prior 7 days. Returns None
    if either window has no data."""
    sub = metrics[metrics["kind"] == kind].copy()
    if sub.empty:
        return None
    sub["date"] = pd.to_datetime(sub["date"])
    today = pd.Timestamp(date.today())
    last_week = sub[(sub["date"] > today - pd.Timedelta(days=7)) & (sub["date"] <= today)]
    prior = sub[(sub["date"] > today - pd.Timedelta(days=14)) & (sub["date"] <= today - pd.Timedelta(days=7))]
    if last_week.empty or prior.empty:
        return None
    return float(last_week["value"].mean() - prior["value"].mean())


def _trend(kind: str) -> pd.DataFrame:
    sub = metrics[metrics["kind"] == kind].copy()
    if sub.empty:
        return pd.DataFrame(columns=["date", "value"])
    sub["date"] = pd.to_datetime(sub["date"])
    return sub.sort_values("date")[["date", "value"]].set_index("date")


# ─── Recommendation card ──────────────────────────────────────────────

# Recommendations are computed in-memory on every render; the dashboard
# is read-only so it doesn't persist them on every page load (which
# would also conflict with a concurrent sync script writing metrics).
rec = generate_recommendation(client_id, metrics, sessions)

st.markdown(
    f"""
    <div class="rec-card">
      <h3>{rec.recommendation}</h3>
      <div class="rationale">{rec.rationale}</div>
      <div class="confidence">Confidence {rec.confidence:.0%} · {len(rec.source_metric_ids)} source metrics traced</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ─── Status row ───────────────────────────────────────────────────────

STATUS_CARDS = [
    ("Training Readiness", MetricKind.TRAINING_READINESS.value, ""),
    ("HRV last night", MetricKind.HRV_RMSSD.value, " ms"),
    ("Sleep last night", MetricKind.SLEEP_HOURS.value, " h"),
    ("Resting HR", MetricKind.RESTING_HR.value, " bpm"),
    ("Body Battery high", MetricKind.BODY_BATTERY_HIGH.value, ""),
]

cards = st.columns(len(STATUS_CARDS))
for col, (label, kind, unit) in zip(cards, STATUS_CARDS):
    value = _latest(kind)
    delta = _week_delta(kind)
    with col:
        if value is None:
            st.metric(label, "—", help="No data in the last 21 days.")
        else:
            display = f"{value:.0f}{unit}" if kind != MetricKind.SLEEP_HOURS.value else f"{value:.1f}{unit}"
            delta_str = None if delta is None else f"{delta:+.1f}"
            st.metric(label, display, delta=delta_str)


# ─── Trend charts + sessions ──────────────────────────────────────────

left, right = st.columns([3, 2])

with left:
    st.subheader("14-day trends")
    trend_panel = pd.concat(
        {
            "HRV (ms)": _trend(MetricKind.HRV_RMSSD.value)["value"] if not _trend(MetricKind.HRV_RMSSD.value).empty else pd.Series(dtype=float),
            "Sleep (h)": _trend(MetricKind.SLEEP_HOURS.value)["value"] if not _trend(MetricKind.SLEEP_HOURS.value).empty else pd.Series(dtype=float),
            "Resting HR": _trend(MetricKind.RESTING_HR.value)["value"] if not _trend(MetricKind.RESTING_HR.value).empty else pd.Series(dtype=float),
        },
        axis=1,
    )
    if trend_panel.dropna(how="all").empty:
        st.info("No daily trend data yet. Run a Garmin sync or load the synthetic fixtures.")
    else:
        st.line_chart(trend_panel)

    body_battery_trend = _trend(MetricKind.BODY_BATTERY_HIGH.value)
    if not body_battery_trend.empty:
        st.caption("Body Battery (high of day)")
        st.area_chart(body_battery_trend)

with right:
    st.subheader("Recent sessions")
    if sessions.empty:
        st.info("No sessions logged in the last 21 days.")
    else:
        display_sessions = sessions.copy()
        display_sessions["date"] = pd.to_datetime(display_sessions["date"]).dt.strftime("%a %m-%d")
        st.dataframe(
            display_sessions[["date", "type", "duration_min", "rpe", "notes"]],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander(f"Source metrics for this recommendation ({len(rec.source_metric_ids)})"):
        st.code("\n".join(rec.source_metric_ids) or "(none)", language="text")


# ─── Raw data fallback ───────────────────────────────────────────────

with st.expander(f"All metrics in window ({len(metrics)} rows)"):
    if not metrics.empty:
        st.dataframe(metrics, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "Reasoning is rules-based and explainable — every recommendation "
    "traces back to source metric IDs. ACSM 11th ed. progression guidance; "
    "HRV thresholds per Buchheit (2014)."
)
