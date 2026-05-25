"""Override audit + rule-based tuning suggestions."""
from __future__ import annotations

import duckdb
import pandas as pd
from fastapi import APIRouter, Depends

from ..db import all_overrides
from .deps import current_trainer_id, read_only_conn
from .helpers import classify_rec, override_response
from .schemas import (
    CalibrationResponse,
    CalibrationSuggestion,
    ConfidenceBucket,
    PerClientAgreement,
    PlanAdherenceRow,
    WeeklyAgreement,
)

router = APIRouter()


@router.get("/api/calibration", response_model=CalibrationResponse)
def get_calibration(
    con=Depends(read_only_conn),
    trainer_id: str = Depends(current_trainer_id),
) -> CalibrationResponse:
    # Plan adherence is independent of override history — compute it
    # first so suggestions on a brand-new trainer (no overrides yet) can
    # still surface "this client is off-plan" before the override-based
    # signals have anything to say.
    plan_adherence = _build_plan_adherence(con, trainer_id)

    df = all_overrides(con, trainer_id, limit=1000)
    if df.empty:
        return CalibrationResponse(
            total=0, accept_rate=0.0, edits=0, rejects=0, matrix={}, recent=[],
            by_week=[], by_client=[],
            suggestions=_build_suggestions(pd.DataFrame(), plan_adherence),
            plan_adherence=plan_adherence,
        )

    df = df.copy()
    df["system_type"] = df["system_recommendation"].apply(classify_rec)

    total = len(df)
    accept_n = int((df["trainer_action"] == "accept").sum())
    edit_n = int((df["trainer_action"] == "edit").sum())
    reject_n = int((df["trainer_action"] == "reject").sum())

    matrix: dict[str, dict[str, int]] = {}
    for system_type, group in df.groupby("system_type"):
        action_counts = group["trainer_action"].value_counts().to_dict()
        matrix[str(system_type)] = {str(k): int(v) for k, v in action_counts.items()}

    recent = [override_response(row) for row in df.head(25).to_dict(orient="records")]

    by_week = _build_weekly_agreement(df)
    by_client = _build_per_client_agreement(con, trainer_id, df)
    suggestions = _build_suggestions(df, plan_adherence)
    confidence_audit = _build_confidence_audit(con, trainer_id)

    return CalibrationResponse(
        total=total,
        accept_rate=accept_n / total if total else 0.0,
        edits=edit_n,
        rejects=reject_n,
        matrix=matrix,
        recent=recent,
        by_week=by_week,
        by_client=by_client,
        suggestions=suggestions,
        confidence_audit=confidence_audit,
        plan_adherence=plan_adherence,
    )


def _build_plan_adherence(con, trainer_id: str) -> list[PlanAdherenceRow]:
    """Per-client plan-vs-execution telemetry.

    LEFT JOIN gives us every planned slot regardless of whether it was
    executed; the JOIN to sessions on executed_session_id pulls actual
    duration_min × rpe when a match exists. Aggregate per client into:
      - match_rate         matched / total slots
      - load_delta_pct     mean ((actual_load - planned_load) / planned_load)
                           where planned_load > 0 — null when no matched
                           rows have a planned target to compare against
      - rpe_delta          mean (actual_rpe - planned_rpe) where both
                           are non-null

    Sorts worst-adherence-first so the trainer scans for clients
    drifting from the plan without filtering.
    """
    try:
        df = con.execute(
            """
            SELECT
                ps.client_id,
                ps.target_load_au,
                ps.target_rpe,
                s.duration_min,
                s.rpe AS actual_rpe,
                CASE WHEN s.id IS NULL THEN 0 ELSE 1 END AS matched
            FROM planned_sessions ps
            LEFT JOIN sessions s ON s.id = ps.executed_session_id
            WHERE ps.trainer_id = ?
            """,
            [trainer_id],
        ).df()
    except duckdb.CatalogException:
        return []

    if df.empty:
        return []

    # Pull this trainer's client names once so we don't N+1 the per-client tally.
    name_rows = con.execute(
        "SELECT id, name FROM clients WHERE trainer_id = ?",
        [trainer_id],
    ).fetchall()
    name_map = {cid: name for cid, name in name_rows}

    rows: list[PlanAdherenceRow] = []
    for client_id, group in df.groupby("client_id"):
        total = len(group)
        matched = int(group["matched"].sum())
        match_rate = matched / total if total else 0.0

        # Deltas only meaningful where both planned and actual exist.
        matched_rows = group[group["matched"] == 1].copy()

        load_delta_pct: float | None = None
        rpe_delta: float | None = None
        if not matched_rows.empty:
            actual_load = matched_rows["duration_min"] * matched_rows["actual_rpe"]
            planned_load = matched_rows["target_load_au"]
            # Only compare where planned_load > 0 (None / 0 are skipped).
            load_pairs = matched_rows.assign(
                actual_load=actual_load,
                planned_load=planned_load,
            ).dropna(subset=["planned_load", "actual_load"])
            load_pairs = load_pairs[load_pairs["planned_load"] > 0]
            if not load_pairs.empty:
                deltas = (load_pairs["actual_load"] - load_pairs["planned_load"]) / load_pairs["planned_load"]
                load_delta_pct = float(deltas.mean() * 100)

            # RPE delta — actual vs planned where both present.
            rpe_pairs = matched_rows.dropna(subset=["target_rpe", "actual_rpe"])
            if not rpe_pairs.empty:
                rpe_delta = float((rpe_pairs["actual_rpe"] - rpe_pairs["target_rpe"]).mean())

        rows.append(PlanAdherenceRow(
            client_id=str(client_id),
            name=name_map.get(str(client_id), str(client_id)),
            total_slots=total,
            matched_slots=matched,
            match_rate=match_rate,
            load_delta_pct=load_delta_pct,
            rpe_delta=rpe_delta,
        ))

    # Worst adherence first; ties broken by larger total_slots (more
    # data = more confident signal worth surfacing first).
    rows.sort(key=lambda r: (r.match_rate, -r.total_slots))
    return rows


def _build_confidence_audit(con, trainer_id: str) -> list[ConfidenceBucket]:
    """Bucket persisted recommendations by their stated confidence and
    compute the rate at which the trainer accepted them.

    Inner-join semantics: we only count weeks where both a persisted
    recommendation and a trainer decision exist. Weeks the trainer
    hasn't ruled on yet are excluded — we don't know what they'll do.

    Window-function pick on the override side: if a trainer edited the
    same week twice we count their most recent action, not the first.
    """
    try:
        df = con.execute(
            """
            SELECT r.confidence, o.trainer_action
            FROM recommendations r
            INNER JOIN (
                SELECT client_id, week_of, trainer_action, trainer_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY client_id, week_of
                           ORDER BY created_at DESC
                       ) AS rn
                FROM recommendation_overrides
                WHERE trainer_id = ?
            ) o
            ON r.client_id = o.client_id
               AND r.week_of = o.week_of
               AND r.trainer_id = o.trainer_id
            WHERE o.rn = 1 AND r.trainer_id = ?
            """,
            [trainer_id, trainer_id],
        ).df()
    except duckdb.CatalogException:
        # Pre-migration DB — recommendations / overrides table may not
        # exist on a fresh install. Return empty buckets; the audit fills
        # in as decisions are logged.
        df = pd.DataFrame(columns=["confidence", "trainer_action"])

    # Fixed bands so the chart shape is comparable week-over-week even as
    # the data fills in. Top bucket includes 1.0 (otherwise a confidence
    # of exactly 1.0 falls out of the audit).
    bands = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.001)]
    buckets: list[ConfidenceBucket] = []
    for lo, hi in bands:
        mask = (df["confidence"] >= lo) & (df["confidence"] < hi) if not df.empty else None
        rows = df[mask] if mask is not None else df
        n = len(rows)
        accepts = int((rows["trainer_action"] == "accept").sum()) if n else 0
        buckets.append(ConfidenceBucket(
            low=lo,
            high=min(hi, 1.0),
            total=n,
            accepts=accepts,
            accept_rate=accepts / n if n else 0.0,
        ))
    return buckets


def _build_weekly_agreement(df: pd.DataFrame) -> list[WeeklyAgreement]:
    """Group overrides by ``week_of`` and compute the accept rate per
    week. Sorted oldest-first so the front-end can render a left-to-
    right time series."""
    grouped = df.groupby("week_of")
    out: list[WeeklyAgreement] = []
    for week_of, group in grouped:
        total = len(group)
        accepts = int((group["trainer_action"] == "accept").sum())
        out.append(WeeklyAgreement(
            week_of=week_of,
            total=total,
            accepts=accepts,
            accept_rate=accepts / total if total else 0.0,
        ))
    out.sort(key=lambda r: r.week_of)
    return out


def _build_per_client_agreement(con, trainer_id: str, df: pd.DataFrame) -> list[PerClientAgreement]:
    """Per-client tally. The trainer cares less about aggregate accept
    rate than about which specific client they keep disagreeing with."""
    grouped = df.groupby("client_id")
    rows: list[PerClientAgreement] = []
    # One small SELECT to get names; saves a per-client roundtrip.
    # trainer_id filter is defense-in-depth — df is already filtered
    # by all_overrides() above, so any client_id here belongs to this
    # trainer, but pinning the lookup to (id, trainer_id) means a
    # mistakenly-leaked id can't reveal another trainer's client name.
    name_map: dict[str, str] = {}
    for client_id in grouped.groups:
        row = con.execute(
            "SELECT name FROM clients WHERE id = ? AND trainer_id = ?",
            [client_id, trainer_id],
        ).fetchone()
        name_map[client_id] = row[0] if row else client_id

    for client_id, group in grouped:
        total = len(group)
        accepts = int((group["trainer_action"] == "accept").sum())
        edits = int((group["trainer_action"] == "edit").sum())
        rejects = int((group["trainer_action"] == "reject").sum())
        rows.append(PerClientAgreement(
            client_id=str(client_id),
            name=name_map.get(str(client_id), str(client_id)),
            total=total,
            accepts=accepts,
            edits=edits,
            rejects=rejects,
            accept_rate=accepts / total if total else 0.0,
        ))
    # Worst-agreement-first so the trainer scans top → calibration gaps.
    rows.sort(key=lambda r: (r.accept_rate, -r.total))
    return rows


def _build_suggestions(
    df: pd.DataFrame,
    plan_adherence: list[PlanAdherenceRow] | None = None,
) -> list[CalibrationSuggestion]:
    """Rule-based tuning prompts. These aren't ML; they're explicit
    if/then heuristics the trainer can audit. The "explainable beats
    clever" thesis applies — a trainer who can't reason about why a
    suggestion appeared won't trust it.

    Sources of signal:
      - ``df``              the recommendation_overrides log
                            (engine-vs-trainer agreement patterns)
      - ``plan_adherence``  per-client plan-vs-execution rows derived
                            from the planned_sessions ⋈ sessions join
                            (did the client actually do the work?)

    Override-based rules surface trainer-engine drift. Adherence-based
    rules surface trainer-client drift. Both go in the same suggestions
    list so the trainer sees a single consolidated "things to consider"
    panel, sorted naturally by severity (warn > info).
    """
    suggestions: list[CalibrationSuggestion] = []

    # ---- Override-based rules (engine ↔ trainer drift) -----------------

    if not df.empty:
        # Rule 1: ≥60% of recent (last 5) deload calls were not accepted →
        # HRV thresholds may be too sensitive for this trainer's clients.
        deloads = df[df["system_type"] == "Deload"].sort_values("created_at", ascending=False).head(5)
        if len(deloads) >= 3:
            rejected_or_edited = int(((deloads["trainer_action"] == "reject") | (deloads["trainer_action"] == "edit")).sum())
            if rejected_or_edited / len(deloads) >= 0.6:
                suggestions.append(CalibrationSuggestion(
                    kind="threshold_tune",
                    severity="warn",
                    message=(
                        f"You've pushed back on {rejected_or_edited} of the last {len(deloads)} deload calls. "
                        f"Consider raising hrv_severe_sd or rhr_severe_bpm in the affected clients' threshold panel — "
                        f"your athletes may be more reactive than the population default."
                    ),
                    target="hrv_severe_sd",
                ))

        # Rule 2: ≥50% of recent (last 5) standard calls were edited or
        # rejected → standard progression may be too aggressive for this practice.
        standards = df[df["system_type"] == "Standard"].sort_values("created_at", ascending=False).head(5)
        if len(standards) >= 3:
            not_accepted = int((standards["trainer_action"] != "accept").sum())
            if not_accepted / len(standards) >= 0.5:
                suggestions.append(CalibrationSuggestion(
                    kind="threshold_tune",
                    severity="info",
                    message=(
                        f"You've adjusted {not_accepted} of the last {len(standards)} standard-progression calls. "
                        f"The ACSM 5-10% range may be too aggressive for your clients — consider tuning per client."
                    ),
                    target=None,
                ))

        # Rule 3: any single client with ≥3 overrides and accept rate ≤0.25
        # → flag for review.
        for client_id, group in df.groupby("client_id"):
            if len(group) >= 3:
                rate = (group["trainer_action"] == "accept").sum() / len(group)
                if rate <= 0.25:
                    suggestions.append(CalibrationSuggestion(
                        kind="per_client_drift",
                        severity="warn",
                        message=(
                            f"You've accepted only {int((group['trainer_action'] == 'accept').sum())} of "
                            f"{len(group)} system calls for this client. Their thresholds may need per-client tuning."
                        ),
                        target=str(client_id),
                    ))

    # ---- Plan-adherence rules (trainer ↔ client drift) -----------------

    for row in (plan_adherence or []):
        # Rule 4 (warn): The "out of sync" client — they're skipping
        # prescribed sessions AND when they do train, they're way off
        # the prescribed intensity. Both signals at once suggests a
        # conversation, not a threshold tune.
        if (
            row.total_slots >= 3
            and row.match_rate < 0.6
            and row.load_delta_pct is not None
            and abs(row.load_delta_pct) >= 25
        ):
            direction = "over" if row.load_delta_pct > 0 else "under"
            suggestions.append(CalibrationSuggestion(
                kind="plan_adherence",
                severity="warn",
                message=(
                    f"{row.name}'s plan adherence is {int(row.match_rate * 100)}% "
                    f"({row.matched_slots} of {row.total_slots} slots), and the sessions they did do "
                    f"averaged {row.load_delta_pct:+.0f}% load vs. plan — they're training "
                    f"{direction} the prescription. Worth a check-in on pacing."
                ),
                target=row.client_id,
            ))
            continue  # don't double-flag with the milder rules below

        # Rule 5 (info): Just low adherence — they're not showing up
        # for the prescribed work. Could be life, could be that the
        # plan doesn't fit their actual schedule. Soft signal.
        if row.total_slots >= 4 and row.match_rate <= 0.5:
            suggestions.append(CalibrationSuggestion(
                kind="plan_adherence",
                severity="info",
                message=(
                    f"{row.name} executed {row.matched_slots} of {row.total_slots} prescribed sessions "
                    f"({int(row.match_rate * 100)}%). Consider whether the plan template matches "
                    f"their actual training week."
                ),
                target=row.client_id,
            ))
            continue

        # Rule 6 (info): Just systematic load drift — they're showing up
        # but consistently harder or softer than asked. Useful for
        # spotting clients who need explicit RPE coaching.
        if (
            row.matched_slots >= 3
            and row.load_delta_pct is not None
            and abs(row.load_delta_pct) >= 30
        ):
            direction = "over" if row.load_delta_pct > 0 else "under"
            suggestions.append(CalibrationSuggestion(
                kind="plan_adherence",
                severity="info",
                message=(
                    f"{row.name} is consistently training {direction} plan "
                    f"({row.load_delta_pct:+.0f}% load across {row.matched_slots} executed sessions). "
                    f"Consider explicit RPE coaching."
                ),
                target=row.client_id,
            ))

    # Stable sort: keep insertion order within each severity, warn-first.
    suggestions.sort(key=lambda s: 0 if s.severity == "warn" else 1)
    return suggestions
