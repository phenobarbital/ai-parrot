"""FEAT-801 contract: /sdd-task documentation-task rule and /sdd-done Step 4.6b in every twin."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestCloseoutContract:
    def test_sdd_done_twins_call_check(self):
        """Both /sdd-done twins call parrot sdd techwiki check."""
        for twin in [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md"]:
            text = (REPO_ROOT / twin).read_text()
            assert "parrot sdd techwiki check" in text, twin

    def test_codex_sdd_done_twin_carries_step(self):
        """The codex /sdd-done twin carries step 4.6b."""
        text = (REPO_ROOT / ".agents/skills/sdd-done/SKILL.md").read_text()
        assert "4.6b" in text
        assert "parrot sdd techwiki check" in text

    def test_step_46b_between_46_and_47(self):
        """### 4.6b sits between 4.6 and 4.7."""
        for twin in [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md"]:
            text = (REPO_ROOT / twin).read_text()
            assert text.index("### 4.6.") < text.index("### 4.6b") < text.index("### 4.7"), twin

    def test_never_blocks_present(self):
        """The step states that it never blocks and no exit code aborts closeout."""
        for twin in [".claude/commands/sdd-done.md", ".agent/workflows/sdd-done.md"]:
            text = (REPO_ROOT / twin).read_text()
            assert "never blocks" in text.lower(), twin
            assert "No exit code of `techwiki check` aborts closeout" in text, twin

    def test_sdd_task_twins_carry_docs_rule(self):
        """All three sdd-task twins carry the documentation-task rule."""
        for twin in [
            ".claude/commands/sdd-task.md",
            ".agents/skills/sdd-task/SKILL.md",
            ".agent/workflows/sdd-task.md",
        ]:
            text = (REPO_ROOT / twin).read_text()
            assert "documentation task" in text.lower(), twin
