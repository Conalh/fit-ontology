"""Injury-aware contraindications.

The trainer captures ``injury_history`` as freeform text on every
client intake. Until now that field was dead weight — never read by
reasoning. This module scans it for known injury keywords and emits
**constraints on what the trainer should program**, regardless of the
weekly verdict.

Design choices worth flagging:

  - **Deterministic keyword dictionary, not LLM-interpreted.** The
    project's "explainable beats clever" thesis applies — the trainer
    should be able to read this file and predict exactly what'll
    match. Free-text Claude calls per render would be both unpredictable
    and expensive.

  - **Constraints, not overrides.** A knee tag doesn't change DELOAD
    into CONSERVATIVE; it caps plyometric volume on whatever the
    weekly verdict prescribes. Two layers: the recovery-based verdict
    (reasoning.py) and the structural constraint (this module).

  - **Independent rules.** "ACL reconstruction" rightly fires both the
    knee-history rule (cap plyometrics) and the ACL-specific rule (no
    deep squats under load). Different advice; both apply. We dedup
    only *within* a rule kind, not *across* kinds.

Patterns are anchored on word boundaries with the ``\\b`` regex
metacharacter so substrings inside other words don't trigger false
positives (e.g. "kneel" doesn't match "knee").
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ContraindicationRule:
    """One keyword-driven constraint."""

    pattern: re.Pattern[str]
    kind: str
    title: str
    advice: str


# Order is meaningful only for stable output; matches all fire independently.
RULES: list[ContraindicationRule] = [
    ContraindicationRule(
        # "ACL/MCL/PCL/meniscus" all signal a knee history; the ACL rule
        # below fires alongside with extra-specific advice.
        pattern=re.compile(r"\b(knee|meniscus|patellar|ACL|MCL|PCL)\b", re.IGNORECASE),
        kind="knee",
        title="Knee history",
        advice="Cap plyometric volume; avoid deep knee flexion under heavy load.",
    ),
    ContraindicationRule(
        pattern=re.compile(r"\bACL\b", re.IGNORECASE),
        kind="acl",
        title="ACL history",
        advice="No deep squats under load; reintroduce plyometrics via graded loading only.",
    ),
    ContraindicationRule(
        pattern=re.compile(r"\b(lumbar|low(?:er)? back|L[1-5]|disc(?: hernia)?)\b", re.IGNORECASE),
        kind="lumbar",
        title="Lumbar history",
        advice="Reduce loaded spinal flexion; cap deadlift volume on stressed weeks.",
    ),
    ContraindicationRule(
        pattern=re.compile(r"\b(shoulder|rotator cuff|labrum|impingement)\b", re.IGNORECASE),
        kind="shoulder",
        title="Shoulder history",
        advice="Avoid kipping and high-volume overhead pressing; favor neutral-grip pulls.",
    ),
    ContraindicationRule(
        pattern=re.compile(
            r"\b(tendinopathy|tendonitis|achilles|patellar tendon|tennis elbow|golfer'?s elbow)\b",
            re.IGNORECASE,
        ),
        kind="tendinopathy",
        title="Tendinopathy",
        advice="Heavy-slow-resistance protocol; avoid sudden volume jumps.",
    ),
    ContraindicationRule(
        pattern=re.compile(r"\b(hip|labral|FAI|femoroacetabular)\b", re.IGNORECASE),
        kind="hip",
        title="Hip history",
        advice="Limit sprinting and lateral plyometrics; cap end-range hip flexion.",
    ),
]


@dataclass(frozen=True)
class Contraindication:
    """One matched constraint, ready to surface to the trainer."""

    kind: str
    title: str
    advice: str
    source_phrase: str


def match_contraindications(injury_history: str | None) -> list[Contraindication]:
    """Scan ``injury_history`` and return one Contraindication per
    matched rule kind. Returns [] when the field is blank or no rules
    match — never raises."""
    if not injury_history or not injury_history.strip():
        return []

    matches: list[Contraindication] = []
    seen_kinds: set[str] = set()
    for rule in RULES:
        m = rule.pattern.search(injury_history)
        if m and rule.kind not in seen_kinds:
            seen_kinds.add(rule.kind)
            matches.append(
                Contraindication(
                    kind=rule.kind,
                    title=rule.title,
                    advice=rule.advice,
                    source_phrase=m.group(0),
                )
            )
    return matches
