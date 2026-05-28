"""Unit tests for OutputMode.INFOGRAPHIC enum value (FEAT-197, TASK-1320)."""
from __future__ import annotations

import sys

# Force real outputs module (bypass conftest stubs if any).
sys.modules.pop("parrot.models.outputs", None)
import parrot.models.outputs as _real_outputs
sys.modules["parrot.models.outputs"] = _real_outputs

from parrot.models.outputs import OutputMode  # noqa: E402


def test_infographic_value():
    """OutputMode('infographic') should resolve to OutputMode.INFOGRAPHIC."""
    assert OutputMode("infographic") is OutputMode.INFOGRAPHIC
    assert OutputMode.INFOGRAPHIC.value == "infographic"


def test_existing_values_untouched():
    """Pre-existing values must not be affected by the new INFOGRAPHIC addition."""
    for v in ("default", "json", "html", "map", "table", "telegram", "msteams"):
        assert OutputMode(v) is not None


def test_infographic_is_str():
    """OutputMode extends str so INFOGRAPHIC.value should equal 'infographic'."""
    assert OutputMode.INFOGRAPHIC == "infographic"


def test_infographic_not_default():
    """INFOGRAPHIC must be distinct from DEFAULT."""
    assert OutputMode.INFOGRAPHIC is not OutputMode.DEFAULT
