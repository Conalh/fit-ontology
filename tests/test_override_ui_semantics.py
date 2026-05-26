from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_override_drawer_sends_exact_trainer_recommendation():
    drawer = read("web/components/client-detail/override-drawer.tsx")

    assert "trainer_recommendation" in drawer
    assert "recommendationForVerdict(chosen)" in drawer


def test_decision_history_prefers_stored_trainer_recommendation():
    verdict_utils = read("web/components/client-detail/verdict-utils.ts")

    assert "o.trainer_recommendation" in verdict_utils
    assert "textToVerdict(o.trainer_recommendation)" in verdict_utils
