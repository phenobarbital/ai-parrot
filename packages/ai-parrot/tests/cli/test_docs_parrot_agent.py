"""AC26 — the `parrot agent` guide exists and names the feature's flags and keys (FEAT-573)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]  # packages/ai-parrot/tests/cli/ → repo root
DOC = REPO_ROOT / "docs" / "cli" / "parrot-agent.md"


def test_guide_exists() -> None:
    assert DOC.is_file(), f"missing {DOC}"


@pytest.mark.parametrize(
    "term",
    ["--ui", "--session", "--token", "PARROT_SERVER_TOKEN", "PARROT_HOME", "--no-history", "/resume", "--server"],
)
def test_guide_mentions_flag(term: str) -> None:
    assert term in DOC.read_text(encoding="utf-8")


def test_guide_documents_newline_key() -> None:
    text = DOC.read_text(encoding="utf-8").lower()
    assert "ctrl+j" in text


def test_agentd_doc_mentions_post_turn_hook() -> None:
    assert "add_post_turn_hook" in (REPO_ROOT / "docs" / "agentd.md").read_text(encoding="utf-8")
