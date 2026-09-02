"""`QANode._baseline_aware_lint` — swap `ruff check` for the diff-scoped
runner (FEAT-497 Module 3).
"""

from __future__ import annotations

from parrot.flows.dev_loop.nodes.qa import QANode


def _compose(command: str, files: list[str]) -> str:
    """Exactly what _run_deterministic_qa does at the lint_cmd = ... site."""
    return QANode._scope_lint_to_files(QANode._baseline_aware_lint(command, files), files)


def test_ruff_half_is_replaced_mypy_half_scoped():
    assert _compose("ruff check . && mypy --no-incremental", ["a.py"]) == (
        "python -m scripts.sdd.lint_new a.py && mypy --no-incremental a.py"
    )


def test_command_without_ruff_is_untouched():
    assert _compose("mypy --no-incremental", ["a.py"]) == "mypy --no-incremental a.py"


def test_no_changed_files_leaves_command_unchanged():
    cmd = "ruff check . && mypy --no-incremental"
    assert QANode._baseline_aware_lint(cmd, []) == cmd
    assert _compose(cmd, []) == cmd


def test_paths_are_shell_quoted():
    out = QANode._baseline_aware_lint("ruff check .", ["dir with space/a.py"])
    assert out == "python -m scripts.sdd.lint_new 'dir with space/a.py'"
