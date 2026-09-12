"""Google installer writes/removes the managed conventions block (FEAT-553, AC-6/AC-6b)."""
from __future__ import annotations

from pathlib import Path

from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.installer import _install_gemini_md, uninstall_google_integration


def _seed(root: Path) -> None:
    (root / ".agent" / "rules").mkdir(parents=True)
    (root / ".agent" / "rules" / "codebase-conventions.md").write_text("---\nx: 1\n---\nRULE-ONE\n")
    (root / ".agent" / "rules" / "python-development.md").write_text("RULE-TWO\n")


def test_install_gemini_md_upserts_conventions_block(tmp_path):
    _seed(tmp_path)
    (tmp_path / "GEMINI.md").write_text("# Gemini\nkeep me\n")
    first = _install_gemini_md(tmp_path)
    text = (tmp_path / "GEMINI.md").read_text()
    # "created" vs "updated" mirrors the file's PRE-EXISTING semantics (unchanged by this task):
    # it reflects whether GEMINI.md existed at all before the call, not whether the markers did.
    # GEMINI.md is seeded with content above, so this call reports "updated".
    assert "updated" in first and text.index(assets.AGENTS_BEGIN) < text.index(assets.CONVENTIONS_BEGIN)
    assert "RULE-ONE" in text and "RULE-TWO" in text and "keep me" in text
    assert "already current" in _install_gemini_md(tmp_path)


def test_uninstall_removes_conventions_block(tmp_path):
    # Install the blocks first
    _seed(tmp_path)
    (tmp_path / "GEMINI.md").write_text("# Gemini\nkeep me\n")
    _install_gemini_md(tmp_path)
    
    # Verify the blocks were installed
    text = (tmp_path / "GEMINI.md").read_text()
    assert assets.AGENTS_BEGIN in text
    assert assets.CONVENTIONS_BEGIN in text
    
    # Uninstall and verify both blocks are removed but original content remains
    actions = uninstall_google_integration(tmp_path)
    text_after = (tmp_path / "GEMINI.md").read_text()
    
    # Check that the managed blocks are removed
    assert assets.AGENTS_BEGIN not in text_after
    assert assets.CONVENTIONS_BEGIN not in text_after
    
    # Check that original content is preserved
    assert "keep me" in text_after
    
    # Check that the uninstall action mentions both sections
    uninstall_actions = [action for action in actions if "GEMINI.md" in action]
    assert len(uninstall_actions) == 1
    assert "wiki + conventions sections removed" in uninstall_actions[0]