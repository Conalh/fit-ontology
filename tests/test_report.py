"""Weekly PDF — round-trip the bytes and spot-check the content."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from fit_ontology.ontology import MetricKind, Recommendation
from fit_ontology.report import build_weekly_pdf


def _metrics_df(today: date) -> pd.DataFrame:
    rows = []
    for offset in range(7):
        d = today - timedelta(days=offset)
        rows.append({"id": f"m_{offset}_a", "date": d, "kind": MetricKind.HRV_RMSSD.value, "value": 50.0, "unit": "ms", "source": "garmin"})
        rows.append({"id": f"m_{offset}_b", "date": d, "kind": MetricKind.SLEEP_HOURS.value, "value": 7.5, "unit": "h", "source": "garmin"})
        rows.append({"id": f"m_{offset}_c", "date": d, "kind": MetricKind.RESTING_HR.value, "value": 58.0, "unit": "bpm", "source": "garmin"})
    return pd.DataFrame(rows)


def _rec(text: str, rationale: str) -> Recommendation:
    return Recommendation(
        id="r_test",
        client_id="c_test",
        generated_at=datetime.now(),
        week_of=date(2026, 5, 18),
        recommendation=text,
        rationale=rationale,
        source_metric_ids=["m_0_a", "m_0_b"],
        confidence=0.85,
    )


def test_pdf_renders_bytes_for_deload():
    pdf = build_weekly_pdf(
        client_name="Test Client",
        client_goal="general fitness",
        rec=_rec(
            "Deload week: reduce training load by 20%.",
            "HRV acute is 1.2 SD below baseline. Flags: hrv_below_baseline, sleep_deficit.",
        ),
        metrics=_metrics_df(date(2026, 5, 23)),
        today=date(2026, 5, 23),
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000  # not empty / not just a header


def test_pdf_renders_for_standard_with_no_flags():
    pdf = build_weekly_pdf(
        client_name="Clean Client",
        client_goal="strength",
        rec=_rec(
            "Standard progression per ACSM 11e: increase load 5–10%.",
            "Recovery markers within baseline range; no flags. Proceed with planned progression.",
        ),
        metrics=_metrics_df(date(2026, 5, 23)),
        today=date(2026, 5, 23),
    )
    assert pdf.startswith(b"%PDF")


def test_pdf_renders_with_empty_metrics():
    """The PDF should still render even when no recent wearable data
    landed — the recovery snapshot becomes em-dashes."""
    pdf = build_weekly_pdf(
        client_name="Stale Client",
        client_goal="rehab",
        rec=_rec(
            "Conservative progression: hold volume, increase load ~5%.",
            "Recovery markers limited; one mild flag. Flags: rpe_rising.",
        ),
        metrics=pd.DataFrame(columns=["id", "date", "kind", "value", "unit", "source"]),
        today=date(2026, 5, 23),
    )
    assert pdf.startswith(b"%PDF")


def _build_two_pdfs(coach_message):
    """Build a baseline and an instrumented PDF, identical except for the
    coach_message. Used to assert that providing a coach message causes
    the document to grow — ReportLab compresses its content stream, so
    we can't substring-search the raw bytes for the rendered text."""
    common = dict(
        client_name="Note Client",
        client_goal="strength",
        rec=_rec(
            "Standard progression per ACSM 11e: increase load 5–10%.",
            "Recovery markers within baseline range; no flags.",
        ),
        metrics=_metrics_df(date(2026, 5, 23)),
        today=date(2026, 5, 23),
    )
    baseline = build_weekly_pdf(**common, coach_message=None)
    instrumented = build_weekly_pdf(**common, coach_message=coach_message)
    return baseline, instrumented


def test_pdf_grows_when_coach_message_added():
    baseline, instrumented = _build_two_pdfs("Great push on Tuesday. Protect sleep this week.")
    assert baseline.startswith(b"%PDF") and instrumented.startswith(b"%PDF")
    assert len(instrumented) > len(baseline)


def test_pdf_unchanged_for_whitespace_or_none_coach_message():
    baseline, with_empty = _build_two_pdfs("")
    _, with_whitespace = _build_two_pdfs("   \n  ")
    # Trailing-metadata bytes (creation timestamps) make exact equality
    # flaky; identical content streams produce nearly-identical sizes
    # within a small constant.
    assert abs(len(with_empty) - len(baseline)) < 30
    assert abs(len(with_whitespace) - len(baseline)) < 30


def test_pdf_survives_reportlab_markup_in_user_text():
    """SECURITY (audit fix #3): client_name/goal arrive from the public
    intake form. ReportLab's Paragraph parses a mini-XML markup, so an
    unescaped "<" or unbalanced tag in those fields would raise during
    doc.build() — a planted 500 on the trainer's export. We escape at the
    boundary, so a hostile name must now render a valid PDF, not throw."""
    pdf = build_weekly_pdf(
        client_name='<font color="red">Ahab</font></para><inject',
        client_goal="strength & <b>power",
        rec=_rec(
            "Standard progression.",
            "Recovery clean.",
        ),
        metrics=_metrics_df(date(2026, 5, 23)),
        today=date(2026, 5, 23),
        coach_message="Nice work <not-a-tag> & keep it up\n\nSee you Monday",
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
