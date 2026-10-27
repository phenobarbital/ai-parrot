"""Shared fixtures and guards for the reel unit tests.

* ``veo_test_profile`` — an enabled, test-only Veo profile. The production
  ``VideoProfileRegistry.default()`` no longer ships one (FEAT-719 dropped the
  dead Developer-API previews; Vertex GA Veo is ``enabled=False``), so tests
  that drive the Veo adapter or a mixed Veo/Omni reel use this profile, which
  keeps the retained Veo shape.
* A per-test ``pytest-timeout`` limit for every test in this directory, so one
  hung test fails on its own instead of exhausting a merge-tier validation
  budget (ledger ``issue:990069166e04``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from parrot.clients.google.reel.profiles import VideoModelProfile

REEL_TEST_TIMEOUT_SECONDS = 120
_REEL_DIR = Path(__file__).parent


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Adds a default ``timeout`` marker to reel tests that declare none.

    Args:
        config: The pytest config (unused).
        items: All collected items; only those under this directory are marked.
    """
    for item in items:
        if _REEL_DIR not in Path(str(item.fspath)).parents:
            continue
        if item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(REEL_TEST_TIMEOUT_SECONDS))


@pytest.fixture
def veo_test_profile() -> VideoModelProfile:
    """Returns an enabled Developer-API Veo profile for adapter/orchestration tests."""
    return VideoModelProfile(
        model_id="veo-3.1-generate-preview",
        surface="gemini_developer",
        backend="veo",
        enabled=True,
        durations_seconds=[4, 6, 8],
        resolutions=["720p", "1080p", "4k"],
        resolution_min_duration={"1080p": 8, "4k": 8},
        supports_starting_frame=True,
        supports_reference_guidance=True,
        native_audio="controllable",
        person_generation_values=["allow_adult", "allow_all", "dont_allow"],
        source="test",
        checked_on=date(2026, 9, 17),
    )
