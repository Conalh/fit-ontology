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

import contextlib
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from fit_ontology.config import load_env
from fit_ontology.db import (
    connect,
    insert_metrics,
    insert_override,
    latest_override_for_week,
    list_clients,
    metrics_for_client,
    overrides_for_client,
    sessions_for_client,
)
from fit_ontology.ingest import (
    from_apple_health_export,
    from_strava_export,
    from_whoop_json,
)
from fit_ontology.ontology import MetricKind, OverrideAction, RecommendationOverride
from fit_ontology.reasoning import generate_recommendation
from fit_ontology.report import build_weekly_pdf

load_env()

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
#
# The DuckDB read-only handle is cached as a singleton per Streamlit
# session. Without the cache, each script rerun would open a new
# connection and leave the previous one alive until GC — which blocks
# in-process write attempts ("Can't open a connection to same database
# file with a different configuration"). With the cache there's always
# exactly one read-only handle we can explicitly close before writing.

@st.cache_resource
def _open_db():
    return connect(read_only=True)


try:
    con = _open_db()
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


# ─── Upload wearable data for this client ─────────────────────────────
#
# Closes the "CLI-only ingestion" gap for non-technical trainers. The
# trainer picks a client above, drops an export file here, and we
# auto-detect the format (Apple Health zip/xml, Strava CSV, Whoop JSON)
# and route to the right adapter. Same close-then-write pattern as the
# override save: DuckDB blocks in-process write while a read-only
# handle is alive.

def _detect_and_parse(filename: str, raw_bytes: bytes, target_client_id: str) -> pd.DataFrame:
    """Sniff the file format from extension + content, dispatch to the
    right adapter, return a DataFrame ready for insert_metrics.

    Buffers the upload to a tempfile because the adapter functions take
    a Path — we could refactor them to accept file-like, but the I/O is
    cheap relative to the DuckDB write that follows, and a tempfile is
    safer for concurrent uploads from multiple browser tabs than a
    fixed scratch path under the project root.
    """
    suffix = Path(filename).suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(raw_bytes)
        tmp_path = Path(tmp_file.name)
    try:
        if suffix == ".zip" or (suffix == ".xml" and b"HealthData" in raw_bytes[:4096]):
            return from_apple_health_export(tmp_path, target_client_id)
        if suffix == ".csv":
            return from_strava_export(tmp_path, target_client_id)
        if suffix == ".json":
            return from_whoop_json(tmp_path, target_client_id)
        raise ValueError(f"Unrecognized file type: {filename}")
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp_path.unlink()


with st.expander("Upload wearable data for this client", expanded=False):
    st.caption(
        "Drop an Apple Health export (`.zip` or `.xml`), a Strava bulk export "
        "(`.csv`), or a Whoop daily-record JSON. Auto-detects the format and "
        "loads it for the currently selected client."
    )
    uploaded = st.file_uploader(
        "Choose a file",
        type=["zip", "xml", "csv", "json"],
        accept_multiple_files=False,
        label_visibility="collapsed",
        key=f"upload_{client_id}",
    )
    if uploaded is not None and st.button("Import", key=f"import_{client_id}"):
        try:
            df = _detect_and_parse(uploaded.name, uploaded.getvalue(), client_id)
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not parse {uploaded.name}: {e}")
            df = None

        if df is not None and df.empty:
            st.warning("File parsed, but no usable rows were found.")
        elif df is not None:
            client_name_for_msg = clients[clients["id"] == client_id]["name"].iloc[0]
            con.close()
            _open_db.clear()
            try:
                with connect(read_only=False) as write_con:
                    insert_metrics(write_con, df)
                kinds = ", ".join(sorted(df["kind"].unique()))
                st.success(f"Imported {len(df)} metric rows ({kinds}) for {client_name_for_msg}.")
                st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Could not write to DB: {e}. If a Garmin sync is running, wait and retry.")


# ─── Pull metrics ──────────────────────────────────────────────────────
#
# 35-day window: 28 days for the rolling baseline + 7-day acute window
# the reasoning layer compares against. The dashboard charts also use
# the full window so the baseline ribbon converges to its stable shape
# instead of wobbling on a short tail.

metrics = metrics_for_client(con, client_id, days=35)
sessions = sessions_for_client(con, client_id, days=35)


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


def _baseline_chart(
    kind: str,
    label: str,
    unit: str,
    *,
    baseline_days: int = 28,
    color: str = "#3b82f6",
    threshold_lines: list[tuple[float, str, str]] | None = None,
) -> alt.LayerChart | None:
    """Daily-value line + 28d rolling-mean ± 1 SD shaded ribbon.

    The ribbon makes the reasoning visible: a point dropping below the
    band IS a flag the reasoning layer would fire on. Optional
    horizontal threshold lines (e.g. ACSM sleep floors) draw a fixed
    reference instead of a per-subject baseline.
    """
    sub = metrics[metrics["kind"] == kind].copy()
    if sub.empty:
        return None
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date").reset_index(drop=True)

    sub["baseline"] = sub["value"].rolling(baseline_days, min_periods=7).mean()
    sub["sd"] = sub["value"].rolling(baseline_days, min_periods=7).std()
    sub["lower"] = sub["baseline"] - sub["sd"]
    sub["upper"] = sub["baseline"] + sub["sd"]

    base = alt.Chart(sub).encode(x=alt.X("date:T", title=None))

    layers = [
        base.mark_area(opacity=0.16, color=color).encode(
            y=alt.Y("lower:Q", title=f"{label} ({unit})" if unit else label),
            y2="upper:Q",
        ),
        base.mark_line(color=color, strokeDash=[4, 4], strokeWidth=1.5).encode(
            y="baseline:Q",
        ),
        base.mark_line(color="#1e293b", strokeWidth=2).encode(y="value:Q"),
        base.mark_point(color="#1e293b", filled=True, size=42).encode(
            y="value:Q",
            tooltip=[
                alt.Tooltip("date:T", title="Date"),
                alt.Tooltip("value:Q", title=label, format=".1f"),
                alt.Tooltip("baseline:Q", title="28d baseline", format=".1f"),
                alt.Tooltip("sd:Q", title="SD", format=".2f"),
            ],
        ),
    ]

    if threshold_lines:
        for value, color_t, label_t in threshold_lines:
            rule_df = pd.DataFrame({"y": [value], "label": [label_t]})
            layers.append(
                alt.Chart(rule_df).mark_rule(color=color_t, strokeDash=[2, 4], strokeWidth=1).encode(y="y:Q"),
            )

    return alt.layer(*layers).properties(height=180).configure_axis(grid=True, gridOpacity=0.18)


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


# ─── Client-facing PDF export ─────────────────────────────────────────
#
# Trainer-to-client artifact. Friendly language, no SD/ACWR jargon — the
# detailed view stays here in the dashboard. PDF is built on every render
# (~50ms for a one-page report) so the download is a single click.
#
# The trainer can type a personal note that the PDF renders as a "Note
# from your coach" section. The note persists across reruns via
# st.text_area's session-state-backed value, so toggling other controls
# doesn't clear it.

client_row = clients.iloc[options.index(selected)]
coach_message = st.text_area(
    "Note from coach (optional, appears in the PDF)",
    placeholder="e.g. 'Great push on Tuesday. This week's a recovery one — protect sleep and we'll be ready to PR Saturday.'",
    key=f"coach_msg_{client_id}_{rec.week_of}",
    height=80,
)
pdf_bytes = build_weekly_pdf(
    client_name=client_row["name"],
    client_goal=client_row["goal"],
    rec=rec,
    metrics=metrics,
    coach_message=coach_message or None,
)
pdf_filename = f"{client_row['name'].replace(' ', '_')}_week_{rec.week_of:%Y%m%d}.pdf"
st.download_button(
    "Download weekly PDF for client",
    data=pdf_bytes,
    file_name=pdf_filename,
    mime="application/pdf",
    help="One-page summary in client-friendly language. No SD baselines, no ACWR jargon.",
)


# ─── Trainer override ─────────────────────────────────────────────────
#
# The system's recommendation is a starting point, not a verdict. The
# trainer records what they actually decided so we have an audit trail
# and, eventually, a calibration signal: how often does the model agree
# with the practitioner?

latest_override_df = latest_override_for_week(con, client_id, rec.week_of)
if not latest_override_df.empty:
    row = latest_override_df.iloc[0]
    action = row["trainer_action"]
    when = pd.to_datetime(row["created_at"]).strftime("%Y-%m-%d %H:%M")
    pct = row["applied_load_change_pct"]
    parts = [f"**{action.capitalize()}**", f"logged {when}"]
    if action == OverrideAction.EDIT.value and pct is not None and not pd.isna(pct):
        parts.append(f"applied {pct:+.0f}% load change")
    if row["trainer_note"]:
        parts.append(f"note: {row['trainer_note']}")
    st.info(" · ".join(parts))

with st.expander(f"Record trainer decision for week of {rec.week_of}", expanded=False):
    action_value = st.radio(
        "What did you do with this recommendation?",
        options=[a.value for a in OverrideAction],
        format_func=lambda v: v.capitalize(),
        horizontal=True,
        key=f"action_{client_id}_{rec.week_of}",
    )
    applied_pct: float | None = None
    if action_value == OverrideAction.EDIT.value:
        applied_pct = st.number_input(
            "Applied load change (%) — what you actually did",
            min_value=-50.0,
            max_value=50.0,
            value=0.0,
            step=1.0,
            key=f"pct_{client_id}_{rec.week_of}",
        )
    note = st.text_input(
        "Note (optional)",
        placeholder="e.g. 'travel week, kept it light'",
        key=f"note_{client_id}_{rec.week_of}",
    )
    if st.button("Save decision", key=f"save_{client_id}_{rec.week_of}"):
        # DuckDB refuses to open a write connection in the same process while
        # any read-only handle to the same file is alive. We close the cached
        # singleton, clear the cache so the next rerun reopens cleanly, then
        # do the write.
        ov = RecommendationOverride(
            id=f"o_{uuid.uuid4().hex[:12]}",
            client_id=client_id,
            week_of=rec.week_of,
            system_recommendation=rec.recommendation,
            system_confidence=rec.confidence,
            trainer_action=OverrideAction(action_value),
            applied_load_change_pct=applied_pct,
            trainer_note=note or None,
            created_at=datetime.now(),
        )
        con.close()
        _open_db.clear()
        try:
            with connect(read_only=False) as write_con:
                insert_override(write_con, ov)
            st.success("Decision saved.")
            st.rerun()
        except Exception as e:  # noqa: BLE001 — surface lock errors to the user
            st.error(f"Could not save: {e}. If a Garmin sync is running, wait for it to finish and try again.")


# ─── Status row ───────────────────────────────────────────────────────

STATUS_CARDS = [
    ("Training Readiness", MetricKind.TRAINING_READINESS.value, ""),
    ("HRV last night", MetricKind.HRV_RMSSD.value, " ms"),
    ("Sleep last night", MetricKind.SLEEP_HOURS.value, " h"),
    ("Resting HR", MetricKind.RESTING_HR.value, " bpm"),
    ("Body Battery high", MetricKind.BODY_BATTERY_HIGH.value, ""),
]

cards = st.columns(len(STATUS_CARDS))
for col, (label, kind, unit) in zip(cards, STATUS_CARDS, strict=True):
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
    st.subheader("Trends with baseline")
    st.caption("Solid: daily value. Dashed: 28-day rolling mean. Shaded: ±1 SD of that mean. Points landing outside the band are what the reasoning layer flags.")

    hrv_chart = _baseline_chart(MetricKind.HRV_RMSSD.value, "HRV (RMSSD)", "ms", color="#3b82f6")
    if hrv_chart is None:
        hrv_chart = _baseline_chart(MetricKind.HRV_SDNN.value, "HRV (SDNN)", "ms", color="#3b82f6")
    if hrv_chart is not None:
        st.altair_chart(hrv_chart, use_container_width=True)

    rhr_chart = _baseline_chart(MetricKind.RESTING_HR.value, "Resting HR", "bpm", color="#ef4444")
    if rhr_chart is not None:
        st.altair_chart(rhr_chart, use_container_width=True)

    sleep_chart = _baseline_chart(
        MetricKind.SLEEP_HOURS.value,
        "Sleep",
        "h",
        color="#8b5cf6",
        # ACSM 11e adult-general guidance: 7-9h target, 6h as severe-deficit floor.
        threshold_lines=[
            (7.0, "#f59e0b", "ACSM floor 7h"),
            (6.0, "#dc2626", "Severe deficit 6h"),
        ],
    )
    if sleep_chart is not None:
        st.altair_chart(sleep_chart, use_container_width=True)

    if hrv_chart is None and rhr_chart is None and sleep_chart is None:
        st.info("No daily trend data yet. Run a Garmin sync or load the synthetic fixtures.")

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


# ─── Decision history ────────────────────────────────────────────────

history = overrides_for_client(con, client_id, limit=20)
if not history.empty:
    with st.expander(f"Decision history ({len(history)})"):
        display_history = history[
            ["created_at", "week_of", "trainer_action", "applied_load_change_pct", "system_recommendation", "trainer_note"]
        ].copy()
        display_history["created_at"] = pd.to_datetime(display_history["created_at"]).dt.strftime("%Y-%m-%d %H:%M")
        st.dataframe(display_history, use_container_width=True, hide_index=True)


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
