"""CREW_AI_KEY is documented (FEAT-575 AC10, TASK-3458)."""

from pathlib import Path

import pytest

# parents: [0]=crew [1]=flows [2]=bots [3]=tests [4]=ai-parrot [5]=packages [6]=repo root
REPO_ROOT = Path(__file__).resolve().parents[6]


@pytest.mark.parametrize("doc", ["docs/crew_handler.md", "docs/config.md"])
def test_crew_ai_key_is_documented(doc):
    # Skip the test when the file is missing (a wheel checkout has no docs/ tree)
    doc_path = REPO_ROOT / doc
    if not doc_path.exists():
        pytest.skip(f"Documentation file {doc} not found in wheel checkout")

    # Assert "CREW_AI_KEY" appears in its text — bounded by AC10
    # Assert on the variable name only; do NOT assert on prose wording
    content = doc_path.read_text(encoding="utf-8")
    assert "CREW_AI_KEY" in content, f"CREW_AI_KEY not found in {doc}"
