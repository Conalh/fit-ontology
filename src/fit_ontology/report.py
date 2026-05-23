"""Weekly client-facing PDF report.

A trainer-to-client artifact. NOT the technical view — no SD baselines,
no ACWR jargon, no metric IDs. The client sees their week summarized
in plain language plus a small recovery snapshot.

The flag → friendly-language mapping is deterministic, not LLM-rewritten,
so a trainer can predict what the PDF will say before clicking export.
The Ask FitOntology page is where Claude-generated text lives; this
artifact stays mechanical.
"""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .ontology import MetricKind
from .reasoning import Recommendation


# Flag → friendly translation. The reasoning module names flags by
# mechanism (hrv_below_baseline, sleep_deficit). For a client audience,
# we restate them as observations.
FRIENDLY_FLAG_TEXT: dict[str, str] = {
    "hrv_below_baseline": "Your recovery markers suggest your body's working harder than usual this week.",
    "rhr_above_baseline": "Your resting heart rate has been elevated, which is a sign of accumulated stress.",
    "sleep_deficit": "Sleep was short on average this week — your body may be running short on recovery time.",
    "acwr_high": "Total training load picked up sharply compared to recent weeks.",
    "acwr_low": "Training load is below your usual — there's room to push a bit if you're feeling good.",
    "rpe_rising": "Sessions have been feeling tougher than they did the week before.",
}


# Recommendation-text → headline + conclusion.
def _headline_and_conclusion(rec_text: str) -> tuple[str, str]:
    low = rec_text.lower()
    if low.startswith("deload"):
        return (
            "This week: ease back to recover.",
            "We're pulling load down by around 20% this week. The goal is to come back next week feeling fresh.",
        )
    if low.startswith("conservative"):
        return (
            "This week: hold steady.",
            "We're holding volume and nudging load up just a little. Listening to recovery before pushing further.",
        )
    return (
        "This week: keep building.",
        "Recovery looks clean. We're moving forward with the planned progression.",
    )


def _latest(metrics: pd.DataFrame, kind: str) -> float | None:
    sub = metrics[metrics["kind"] == kind]
    if sub.empty:
        return None
    return float(sub.sort_values("date")["value"].iloc[-1])


def _week_mean(metrics: pd.DataFrame, kind: str, today: date) -> float | None:
    sub = metrics[metrics["kind"] == kind].copy()
    if sub.empty:
        return None
    sub["date"] = pd.to_datetime(sub["date"])
    cutoff = pd.Timestamp(today) - pd.Timedelta(days=7)
    last_week = sub[sub["date"] > cutoff]
    if last_week.empty:
        return None
    return float(last_week["value"].mean())


def _flags_from_rationale(rationale: str) -> list[str]:
    """The aggregator appends 'Flags: a, b.' to its rationale. Parse them
    out so the PDF doesn't need to re-run reasoning."""
    if "Flags:" not in rationale:
        return []
    tail = rationale.split("Flags:", 1)[1].strip().rstrip(".")
    return [f.strip() for f in tail.split(",") if f.strip()]


def build_weekly_pdf(
    *,
    client_name: str,
    client_goal: str,
    rec: Recommendation,
    metrics: pd.DataFrame,
    today: date | None = None,
) -> bytes:
    """Render the client-facing one-pager as PDF bytes."""
    today = today or date.today()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        title=f"Weekly summary — {client_name}",
        author="FitOntology",
    )

    styles = getSampleStyleSheet()
    h_title = ParagraphStyle(
        "title",
        parent=styles["Title"],
        fontSize=24,
        leading=28,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=4,
    )
    h_sub = ParagraphStyle(
        "sub",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=18,
    )
    h_section = ParagraphStyle(
        "section",
        parent=styles["Heading2"],
        fontSize=14,
        leading=18,
        textColor=colors.HexColor("#1e293b"),
        spaceBefore=14,
        spaceAfter=8,
    )
    h_headline = ParagraphStyle(
        "headline",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1e3a8a"),
        spaceAfter=6,
    )
    h_body = ParagraphStyle(
        "body",
        parent=styles["BodyText"],
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#334155"),
        spaceAfter=8,
    )
    h_footer = ParagraphStyle(
        "footer",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#94a3b8"),
        alignment=1,  # centre
    )

    headline, conclusion = _headline_and_conclusion(rec.recommendation)

    story: list = []
    story.append(Paragraph(client_name, h_title))
    story.append(Paragraph(f"Weekly summary · {client_goal} · week of {rec.week_of:%B %d, %Y}", h_sub))

    story.append(Paragraph(headline, h_headline))
    story.append(Paragraph(conclusion, h_body))

    # What we saw — friendly translations of each flag.
    flags = _flags_from_rationale(rec.rationale)
    if flags:
        story.append(Paragraph("What we saw this week", h_section))
        for flag in flags:
            text = FRIENDLY_FLAG_TEXT.get(flag, f"Flag noted: {flag}.")
            story.append(Paragraph(f"• {text}", h_body))
    else:
        story.append(Paragraph("What we saw this week", h_section))
        story.append(Paragraph("• Recovery markers look healthy. Nothing flagged for the week.", h_body))

    # Recovery snapshot — last-7-day means where data is available.
    story.append(Paragraph("Recovery snapshot", h_section))
    snapshot_rows = [["Signal", "Last 7 days"]]
    snapshot_specs: list[tuple[str, str, str, int]] = [
        ("HRV (RMSSD)", MetricKind.HRV_RMSSD.value, "ms", 1),
        ("Sleep", MetricKind.SLEEP_HOURS.value, "h", 1),
        ("Resting HR", MetricKind.RESTING_HR.value, "bpm", 0),
        ("Training Readiness", MetricKind.TRAINING_READINESS.value, "", 0),
    ]
    for label, kind, unit, decimals in snapshot_specs:
        v = _week_mean(metrics, kind, today)
        if v is None:
            value = "—"
        else:
            value = f"{v:.{decimals}f}{(' ' + unit) if unit else ''}"
        snapshot_rows.append([label, value])

    table = Table(snapshot_rows, colWidths=[2.5 * inch, 2.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 10),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
                ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#334155")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, colors.HexColor("#cbd5e1")),
            ]
        )
    )
    story.append(table)

    story.append(Spacer(1, 0.5 * inch))
    story.append(
        Paragraph(
            f"Generated {datetime.now():%B %d, %Y at %H:%M} · FitOntology",
            h_footer,
        )
    )

    doc.build(story)
    return buffer.getvalue()
