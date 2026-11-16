"""Source and packaged coder prompts agree on the structured checked-evidence contract (AC11/AC16)."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
_PACKAGED = "packages/ai-parrot/src/parrot/sdd/_assets/claude/agents"
PROMPT_PAIRS = [
    (".claude/agents/sdd-coder.md", f"{_PACKAGED}/sdd-coder.md"),
    (".claude/agents/sdd-worker.md", f"{_PACKAGED}/sdd-worker.md"),
]
REQUIRED_SENTENCES = [
    "Require checked_patterns to reference actually delivered versions and engine-verifiable checks.",
    "Keep citations in the structured channel; do not render them into the user-visible answer.",
    "An independently verified zero-fix delivery may be successful without a fabricated fix commit.",
    "Keep coder_record_feedback, coder_record_review, execution_id and review_ref contracts intact.",
    "Do not convert experience.pitfall lessons or cohort statistics into trusted per-memory outcomes.",
]


@pytest.mark.parametrize(("source", "packaged"), PROMPT_PAIRS)
def test_source_and_packaged_prompt_parity(source: str, packaged: str) -> None:
    """The source prompt and its installed copy are byte-identical, so neither can drift unnoticed."""
    assert (ROOT / source).read_bytes() == (ROOT / packaged).read_bytes(), f"{source} differs from {packaged}"


@pytest.mark.parametrize(("source", "packaged"), PROMPT_PAIRS)
def test_structured_evidence_and_zero_fix_contract(source: str, packaged: str) -> None:
    """Both copies carry the checked-evidence, zero-fix, public-signature and no-lesson-conversion requirements."""
    for path in (source, packaged):
        text = (ROOT / path).read_text(encoding="utf-8")
        missing = [sentence for sentence in REQUIRED_SENTENCES if sentence not in text]
        assert not missing, f"{path} is missing required sentences: {missing}"
