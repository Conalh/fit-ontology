"""Injury keyword matcher.

Anchors on word boundaries — substrings inside other words shouldn't
trigger. Multiple keywords for the same rule kind collapse to one
match; keywords for different kinds fire independently.
"""
from __future__ import annotations

from fit_ontology.contraindications import match_contraindications


def test_no_history_returns_empty():
    assert match_contraindications(None) == []
    assert match_contraindications("") == []
    assert match_contraindications("   ") == []


def test_knee_keyword_matches():
    out = match_contraindications("R meniscus repair 2024")
    assert len(out) == 1
    assert out[0].kind == "knee"
    assert "meniscus" in out[0].source_phrase.lower()
    assert "plyometric" in out[0].advice.lower()


def test_lumbar_keyword_matches():
    out = match_contraindications("Lower back stiffness on heavy days")
    assert any(c.kind == "lumbar" for c in out)


def test_acl_and_knee_both_fire():
    """ACL history is a knee history too — both rules carry distinct
    advice the trainer cares about, both should surface."""
    out = match_contraindications("ACL reconstruction Q2 2023")
    kinds = {c.kind for c in out}
    assert "acl" in kinds
    assert "knee" in kinds


def test_substring_inside_other_word_does_not_match():
    """The \\b boundary keeps `kneel` and `hipster` from firing."""
    assert match_contraindications("client likes to kneel during stretches") == []
    assert match_contraindications("hipster style training environment") == []


def test_duplicate_keyword_does_not_double_fire():
    """Two mentions of `knee` produce one contraindication, not two."""
    out = match_contraindications("knee pain — old knee surgery")
    knees = [c for c in out if c.kind == "knee"]
    assert len(knees) == 1


def test_case_insensitive():
    out_lower = match_contraindications("acl repair")
    out_upper = match_contraindications("ACL REPAIR")
    assert {c.kind for c in out_lower} == {c.kind for c in out_upper}


def test_tendinopathy_matches():
    out = match_contraindications("patellar tendon flare-ups under high mileage")
    kinds = {c.kind for c in out}
    assert "tendinopathy" in kinds
