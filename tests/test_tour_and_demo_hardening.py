from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_tour_provider_is_app_wide_not_tour_scoped():
    providers = read("web/app/providers.tsx")
    tour_layout = read("web/app/tour/layout.tsx")
    tour_provider = read("web/components/tour/tour-provider.tsx")
    auth_guard = read("web/components/auth-guard.tsx")

    assert 'from "@/components/tour/tour-provider"' in providers
    assert "<TourProvider>" in providers
    assert "</TourProvider>" in providers
    assert "TourProvider" not in tour_layout
    assert "usePathname" in tour_provider
    assert "readTourActive" in auth_guard
    assert "const needsRedirect = !isTourActive &&" in auth_guard
    assert "if (isLoading && !isTourActive)" in auth_guard


def test_spotlight_steps_have_real_page_anchors():
    expected = {
        "web/app/page.tsx": ["roster-table", "roster-ben"],
        "web/app/clients/page.tsx": ["recommendation", "override-btn"],
        "web/components/client-detail/plan-panel.tsx": ["plan"],
        "web/components/client-detail/send-to-client.tsx": ["send-client"],
        "web/components/calibration/matrix.tsx": ["cal-matrix"],
    }

    for rel, needles in expected.items():
        content = read(rel)
        for needle in needles:
            assert needle in content, f"{needle} missing from {rel}"


def test_demo_raw_video_artifacts_are_not_committable():
    ignore = read(".gitignore")
    recorder = read("scripts/record_demos.py")

    assert "docs/videos/" in ignore
    assert "TemporaryDirectory" in recorder
    assert 'record_video_dir=str(raw_dir / name)' in recorder
