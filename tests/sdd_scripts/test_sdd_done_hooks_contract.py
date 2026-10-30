"""Text contract for the FEAT-764 closeout hooks in both `/sdd-done` twins (TASK-4870).

Both the Claude command and the Codex skill must call the same dispatcher
(`scripts.sdd.run_closeout_hooks`) for `pre_pr`, `post_pr` and `on_failure`,
must no longer offer `--resolve-jira`, and must never let `--force` bypass a
blocking hook. Every dispatcher flag the twins reference is checked against the
dispatcher's own argparse definitions.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DOC = _ROOT / ".claude/commands/sdd-done.md"
_TWIN = _ROOT / ".agents/skills/sdd-done/SKILL.md"
_DISPATCHER = _ROOT / "scripts/sdd/run_closeout_hooks.py"
_TWINS = (_DOC, _TWIN)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_resolve_jira_anywhere() -> None:
    for path in _TWINS:
        assert "--resolve-jira" not in _text(path), path.name


def test_all_three_events_invoked_in_both_twins() -> None:
    for path in _TWINS:
        text = _text(path)
        for event in ("pre_pr", "post_pr", "on_failure"):
            assert f"--event {event}" in text, (path.name, event)
        assert "scripts.sdd.run_closeout_hooks" in text, path.name


def test_pre_pr_between_test_report_and_report() -> None:
    text = _text(_DOC)
    assert text.index("### 4.7") < text.index("### 4.8") < text.index("### 5. Build")


def test_codex_pre_pr_between_gate_and_classify() -> None:
    text = _text(_TWIN)
    assert text.index("4.6. Verify E2E evidence") < text.index("4.8. Closeout hooks") < text.index("5. Classify:")


def test_post_pr_after_integrate() -> None:
    doc = _text(_DOC)
    assert doc.index("### 9.2") < doc.index("### 9.3. Closeout Hooks — post_pr") < doc.index("### 9.5")
    twin = _text(_TWIN)
    assert (
        twin.index("12. Integrate:")
        < twin.index("12.1. Closeout hooks — post_pr")
        < twin.index("13. Hotfix sync-down:")
    )


def test_hooks_not_force_bypassable() -> None:
    for path in _TWINS:
        text = _text(path)
        assert "--force" in text, path.name
        assert "never bypassed by `--force`" in text or "does not bypass this" in text, path.name
        # No sentence may say that --force bypasses a hook.
        assert not re.search(r"--force[^\n]*\bbypass(es)? (the )?hooks?\b", text), path.name


def test_jira_points_to_builtin() -> None:
    for path in _TWINS:
        text = _text(path)
        assert "jira.transition" in text, path.name
        assert ".parrot/sdd_hooks.toml" in text, path.name


def test_on_failure_wired_on_every_abort_path() -> None:
    # Closeout-flow aborts: E2E gate (4.6), pre-push --merge-into-main gate (8),
    # merge-blocker refusal (9), pre_pr abort (4.8), --merge-from-worktree (9.2).
    # --sync-down exits are post-merge and intentionally excluded.
    assert _text(_DOC).count("--event on_failure") >= 5
    assert _text(_TWIN).count("on_failure") >= 4


def test_write_hook_context_defined_before_first_use() -> None:
    text = _text(_DOC)
    definition = text.index("write_hook_context() {")
    first_call = text.index('write_hook_context "')
    assert definition < first_call, (
        "write_hook_context must be defined before its first call"
    )


def test_evidence_in_pr_body_and_hooks_line_in_output() -> None:
    for path in _TWINS:
        text = _text(path)
        assert "## Evidence" in text, path.name
        assert "Hooks: pre_pr" in text, path.name


def test_dispatcher_flags_referenced_exist() -> None:
    defined = set(re.findall(r'add_argument\("(--[a-z-]+)"', _text(_DISPATCHER)))
    assert "--dry-run" in defined
    for path in _TWINS:
        lines = _text(path).splitlines()
        used: set[str] = set()
        for index, line in enumerate(lines):
            if "run_closeout_hooks" not in line:
                continue
            # Continuation lines of a multi-line shell command are part of the same invocation.
            window = lines[index : index + 4]
            for item in window:
                used.update(re.findall(r"(--[a-z][a-z-]*)", item))
        unknown = used - defined - {"--help"}
        assert not unknown, (path.name, sorted(unknown))
