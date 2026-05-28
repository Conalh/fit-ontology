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


def test_mutations_that_change_coaching_queue_invalidate_it():
    expected_counts = {
        "web/app/clients/new/page.tsx": 1,
        "web/app/clients/edit/page.tsx": 2,
        "web/app/clients/upload/page.tsx": 1,
        "web/components/client-detail/override-drawer.tsx": 1,
        "web/components/client-detail/plan-panel.tsx": 1,
        "web/components/thresholds-panel.tsx": 1,
    }

    for rel, count in expected_counts.items():
        source = read(rel)
        assert source.count('queryKey: ["action-queue"]') >= count, rel


def test_intake_page_is_public_in_auth_guard():
    guard = read("web/components/auth-guard.tsx")

    assert '"/intake"' in guard
