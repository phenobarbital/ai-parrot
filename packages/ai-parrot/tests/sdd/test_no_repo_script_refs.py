"""FEAT-633 M6 (rev 0.2): no shipped SDD asset references ``scripts/sdd`` at all, and none carries
org data, a ``CLAUDE.md`` pointer or a hardcoded flow base.

Every helper listed in ``_MOVED`` lives in ``parrot.sdd.scripts`` (TASK-4085..4088, C12) and is
invoked as ``parrot sdd run <name>`` (Q1). An installed asset that still says
``python -m scripts.sdd.<name>`` / ``scripts/sdd/<name>.py`` — moved helper or not — is broken in
any repository that is not this monorepo (C12). Shipped files must also be free of
``org-data`` / ``claude-md-ref`` / ``branch-literal`` findings (C11) and of any monorepo source
path — ``packages/``, ``scripts/``, ``$CLAUDE_PROJECT_DIR/…`` (C16) — or other monorepo-specific
text — ``tests/sdd_scripts/``, ``from navconfig``, ``PYTHONPATH=``, ``reference/sdd-insight/`` (C22);
``CLAUDE.md``, ``AGENTS.md`` and ``docs/sdd/WORKFLOW.md`` are repo-only and exempt from those gates,
and ``/sdd-insight`` (all hosts) is neither shipped nor rewritten (C22).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from parrot.sdd.audit import scan_paths

_REPO_ROOT = Path(__file__).resolve().parents[4]  # packages/ai-parrot/tests/sdd/ -> repo root
_MOVED: tuple[str, ...] = (
    "sdd_meta", "id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree", "finalize_task",
    "check_task_state", "check_task_graph", "worktree_status", "close_task", "heal_orphans",
    "doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "insight", "install_hooks",
    "prune_intake",  # added to TASK-4088 by the coordinator
    "review_checkpoint",  # C12 — moved by TASK-4086
    "spec_tools",  # TASK-4334
    "brief_meta",  # rev 0.4 C17
    "cache_test_contract", "test_report", "check_e2e_closeout", "close_resolved_issues",  # TASK-4508
    "worktree_environment",  # rev 0.3 C16
)
_ASSET_GLOBS: tuple[str, ...] = (
    ".claude/commands/*.md", ".claude/agents/*.md", ".claude/rules/*.md", ".claude/skills/**/*.md",
    ".agent/**/*.md", ".agents/**/*.md", ".codex/agents/*.toml",
    "sdd/WORKFLOW.md", "docs/sdd/WORKFLOW.md", "CLAUDE.md", "AGENTS.md", "sdd/templates/*.md",
    "packages/ai-parrot/src/parrot/flows/_rules_data/*.md",
)
# The files TASK-4090 actually ships (its Implementation Notes > Asset mapping); the C11 and C16
# gates apply to these only. `_ASSET_GLOBS` above is wider (non-SDD commands/agents/skills, the
# rulebooks, CLAUDE.md / AGENTS.md / docs/sdd/WORKFLOW.md), none of which ships.
_SHIPPED_GLOBS: tuple[str, ...] = (
    ".claude/commands/sdd-*.md", ".claude/agents/sdd-*.md", ".claude/hooks/sdd-worker-format.sh",
    ".claude/rules/worktree-management.md", ".claude/skills/second-opinion/SKILL.md",
    ".agents/skills/sdd-*/SKILL.md", ".codex/agents/sdd-worker.toml", ".agent/workflows/sdd-*.md",
    ".agents/agents/sdd-*/agent.md", "sdd/templates/*", "sdd/WORKFLOW.md", "sdd/CONVENTIONS.md",
)
_C11_KINDS: tuple[str, ...] = ("org-data", "claude-md-ref", "branch-literal")
# C16: a monorepo source path — `packages/…`, `scripts/…`, `$CLAUDE_PROJECT_DIR/…` / `${CLAUDE_PROJECT_DIR…}/…`.
_MONOREPO_PATH = re.compile(r"(?<![\w./-])(?:packages|scripts)/|\$\{?CLAUDE_PROJECT_DIR\b[^/\s]*/")
# C22: the second pattern both C16 gates add (this test and TASK-4090's --check / --wheel).
_MONOREPO_TEXT = re.compile(r"tests/sdd_scripts/|\bfrom navconfig\b|PYTHONPATH=|reference/sdd-insight/")
# (posix path, stripped line) pairs exempted from both patterns — C22 category D: the ONLY entry.
# `${CLAUDE_PROJECT_DIR:-}/.venv/bin` is the target repo's own venv (the PATH-first fallback).
_C16_ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    (".claude/hooks/sdd-worker-format.sh", 'for candidate in "$CWD/.venv/bin" "${CLAUDE_PROJECT_DIR:-}/.venv/bin" \\'),
})
# C22: /sdd-insight (all hosts) does not ship and is not rewritten — excluded from every gate here.
_NOT_SHIPPED_PREFIX = "sdd-insight"


def _glob_files(globs: tuple[str, ...]) -> list[Path]:
    """Files matching ``globs`` in the checkout (``.claude/worktrees/`` and ``/sdd-insight`` excluded)."""
    if not (_REPO_ROOT / ".claude").is_dir():
        pytest.skip("not a repo checkout (installed package)")
    files = {p for g in globs for p in _REPO_ROOT.glob(g) if p.is_file()}
    return sorted(
        p for p in files
        if "worktrees" not in p.relative_to(_REPO_ROOT).parts
        and not any(part.startswith(_NOT_SHIPPED_PREFIX) for part in p.relative_to(_REPO_ROOT).parts)
    )


def _asset_files() -> list[Path]:
    """Every SDD asset in the checkout (``.claude/worktrees/`` excluded)."""
    return _glob_files(_ASSET_GLOBS)


def _shipped_files() -> list[Path]:
    """TASK-4090's shipped set (the C11 publication gate and the C16 path gate apply to these only)."""
    return _glob_files(_SHIPPED_GLOBS)


def test_no_repo_script_findings_at_all() -> None:
    """parrot.sdd.audit reports zero ``repo-script`` findings — moved helper or not (C12)."""
    findings = scan_paths(_asset_files())
    offenders = [f for f in findings if f.kind == "repo-script"]
    assert not offenders, "\n".join(f"{f.path}:{f.line}: {f.snippet}" for f in offenders)


def test_no_publication_findings_in_shipped_files() -> None:
    """Zero ``org-data`` / ``claude-md-ref`` / ``branch-literal`` findings over the shipped set (C11)."""
    findings = scan_paths(_shipped_files())
    offenders = [f for f in findings if f.kind in _C11_KINDS]
    assert not offenders, "\n".join(f"{f.path}:{f.line}: [{f.kind}] {f.snippet}" for f in offenders)


def test_every_invocation_uses_parrot_sdd_run() -> None:
    """Every helper invocation in an asset is ``parrot sdd run <moved name>`` (Q1)."""
    bad = re.compile(r"python3?[ \t]+-m[ \t]+parrot\.sdd\.scripts\.")
    offenders = [p for p in _asset_files() if bad.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"assets still invoke helpers with python -m: {offenders}"


def test_every_rewritten_reference_resolves() -> None:
    """Each ``parrot.sdd.scripts.<name>`` named by an asset is an importable module."""
    pattern = re.compile(r"parrot\.sdd\.scripts\.([a-z0-9_]+)")  # digits: check_e2e_closeout
    names = {m for p in _asset_files() for m in pattern.findall(p.read_text(encoding="utf-8"))}
    missing = sorted(n for n in names if importlib.util.find_spec(f"parrot.sdd.scripts.{n}") is None)
    assert not missing, f"unresolvable parrot.sdd.scripts modules referenced: {missing}"


def test_moved_names_all_resolve() -> None:
    """Every name in ``_MOVED`` is an importable ``parrot.sdd.scripts`` module."""
    missing = [n for n in _MOVED if importlib.util.find_spec(f"parrot.sdd.scripts.{n}") is None]
    assert not missing, f"moved helpers that do not resolve: {missing}"


def test_no_inline_python_imports_parrot() -> None:
    """Rule 6: no ``python -c`` in an asset imports ``parrot.sdd.scripts`` (a global-only install's python cannot)."""
    bad = re.compile(r"python3?\s+-c\s+\"[^\"]*parrot\.sdd\.scripts")  # [^"] spans the multi-line block
    offenders = [p for p in _asset_files() if bad.search(p.read_text(encoding="utf-8"))]
    assert not offenders, f"inline python still imports a helper (use `parrot sdd run sdd_meta …`): {offenders}"


def test_no_monorepo_source_paths_in_shipped_files() -> None:
    """C16 + C22: no shipped file names ``packages/``, ``scripts/``, ``$CLAUDE_PROJECT_DIR/…`` or other
    monorepo-specific text, except the single category-D line in ``_C16_ALLOWLIST``."""
    offenders = []
    for p in _shipped_files():
        rel = p.relative_to(_REPO_ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            hit = _MONOREPO_PATH.search(line) or _MONOREPO_TEXT.search(line)
            if hit and (rel, line.strip()) not in _C16_ALLOWLIST:
                offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
    assert not offenders, "\n".join(offenders)
