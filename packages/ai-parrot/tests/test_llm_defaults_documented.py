"""FEAT-796 docs presence (TASK-5143)."""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["DEFAULT_LLM", "CREW_LLM", "AGENT_LLM", "EXPERT_JUDGMENT_LLM", "CREW_GOOGLE_API_KEY", "CREW_AI_KEY"])
def test_llm_defaults_documented(name: str) -> None:
    doc = ROOT / "docs" / "configuration" / "llm-defaults.md"
    if not doc.exists():
        pytest.skip("docs tree not present")
    assert name in doc.read_text(encoding="utf-8")
