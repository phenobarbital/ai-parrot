"""FEAT-555 TASK-3210 — the [devloop] extra declares redis (design research S12)."""

from __future__ import annotations

from pathlib import Path


def test_devloop_extra_installs_redis():
    root = Path(__file__).resolve().parents[3]  # packages/ai-parrot-integrations
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split("devloop = [", 1)[1].split("]", 1)[0]
    assert "redis>=5.0" in block
