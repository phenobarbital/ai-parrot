# packages/ai-parrot/tests/sdd/test_audit.py
"""Tests for parrot.sdd.audit (FEAT-633 spike S5)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parrot.sdd import audit
from parrot.sdd.audit import AssumptionFinding, missing_tools, scan_paths, scan_text

REPO_ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("python -m scripts.sdd.reserve_ids --kind task", "repo-script"),
        ("scripts/sdd/close_task.sh TASK-1 slug verified", "repo-script"),
        ("source .venv/bin/activate", "venv-path"),
        ("uv run --no-sync pytest", "uv-run"),
        ("TASK_FILES=$(jq -r '.tasks[].file' idx.json)", "external-tool"),
        ("TASK_FILES=$(jq -r '.tasks[].file' idx.json)", "posix-shell"),
        ("cd .claude/worktrees/feat-FEAT-1-x", "monorepo-path"),
        ("Open https://trocglobal.atlassian.net/browse/NAV-1234 first", "org-data"),      # C11a
        ("Resolves NAV-1234 and NAV-77", "org-data"),                                      # C11a
        ("See CLAUDE.md § Adversarial Second Opinion", "claude-md-ref"),                   # C11a
        ("Follow CLAUDE.md throughout.", "claude-md-ref"),                                 # C11a
        ("git fetch origin && git rebase origin/dev", "branch-literal"),                   # C11a
        ("python -m scripts.sdd.reserve_ids --base-branch dev --count 1", "branch-literal"),  # C11a
        ("base_branch: main", "branch-literal"),                                           # C11a
        ("git checkout staging", "branch-literal"),                                        # C11a
    ],
)
def test_scan_text_kinds(line: str, kind: str) -> None:
    assert kind in {f.kind for f in scan_text(line, "x.md")}


def test_scan_text_prose_is_clean() -> None:
    assert scan_text("Ask codex for a second opinion about the design.", "x.md") == []


@pytest.mark.parametrize(
    ("line", "kind"),
    [
        ("Tracker: https://your-org.atlassian.net/browse/PROJ-123", "org-data"),   # placeholders
        ("FEAT-633 decomposes into TASK-4070 … TASK-4095", "org-data"),            # SDD's own ids
        ("checksum SHA-256, encoding UTF-8, dates ISO-8601, criterion AC-1", "org-data"),
        ("the main checkout, the dev-loop and the staging area", "branch-literal"),  # prose words
        ("git fetch origin/<base_branch>; --base <base_branch>", "branch-literal"),  # placeholders
        ("development on the dev branch is described in the handbook", "branch-literal"),
    ],
)
def test_c11a_kinds_skip_placeholders_and_prose(line: str, kind: str) -> None:
    assert kind not in {f.kind for f in scan_text(line, "x.md")}


def test_main_fail_on_exits_1_and_names_the_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "a.md").write_text("ok line\nticket NAV-1 here\n", encoding="utf-8")
    assert audit.main([str(tmp_path), "--root", str(tmp_path), "--fail-on", "org-data"]) == 1
    assert "a.md:2: [org-data]" in capsys.readouterr().err
    assert audit.main([str(tmp_path), "--root", str(tmp_path), "--fail-on", "claude-md-ref"]) == 0


def test_main_fail_on_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        audit.main([str(tmp_path), "--root", str(tmp_path), "--fail-on", "no-such-kind"])
    assert exc.value.code == 2


def test_missing_tools_uses_which(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit.shutil, "which", lambda name: None if name == "jq" else f"/usr/bin/{name}")
    findings = [AssumptionFinding("a.md", 1, "external-tool", "jq -r .x f && gh pr view")]
    assert missing_tools(findings) == ["jq"]


def test_import_is_stdlib_only() -> None:
    code = "import sys, parrot.sdd.audit; print(sorted(m for m in sys.modules if m.startswith('parrot')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['parrot', 'parrot.sdd', 'parrot.sdd.audit', 'parrot.version']"


def test_real_assets_reference_map() -> None:
    """TASK-4089 rewrote every ``scripts/sdd`` reference to ``parrot sdd run``: the real asset has none left."""
    findings = scan_paths([REPO_ROOT / ".claude/commands/sdd-spec.md"])
    names = {m.group("name") for f in findings if f.kind == "repo-script" for m in audit.REPO_SCRIPT_RE.finditer(f.snippet)}
    assert names == set()


def test_default_globs_cover_codex_and_google_twins() -> None:  # rev 0.5 C24
    assert {
        ".agents/skills/sdd-*/SKILL.md", ".agents/agents/sdd-*/agent.md",
        ".agent/workflows/sdd-*.md", ".agent/agents/sdd-*/agent.md",
    } <= set(audit.DEFAULT_GLOBS)


def test_main_empty_root_exits_2(tmp_path: Path) -> None:
    assert audit.main(["--root", str(tmp_path)]) == 2


def test_main_report_has_no_absolute_paths(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    assert audit.main(["--root", str(REPO_ROOT), "--output", str(out)]) == 0
    assert str(REPO_ROOT) not in out.read_text(encoding="utf-8")
