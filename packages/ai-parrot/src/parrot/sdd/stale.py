"""Stale SDD files: hand-copied, retired or no-longer-shipped files left in a repository (FEAT-795 M1).

Read-only: computes the stale set and the source-checkout guard; never writes or deletes.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence

from pydantic import BaseModel

from parrot.sdd.installer import RECEIPT_PATH, SUPPORTED_HOSTS, load_manifest, load_receipt

logger = logging.getLogger(__name__)

StaleReason = Literal["receipt-orphan", "retired", "sdd-orphan"]
_PRECEDENCE: dict[str, int] = {"receipt-orphan": 0, "retired": 1, "sdd-orphan": 2}
_ALL: tuple[str, ...] = ("claude", "codex", "google")
_WT = "merged into .claude/rules/worktree-management.md (FEAT-553)"

#: (glob relative to the repo root, hosts, why) — legacy paths NOT starting with `sdd-` (spec §2 item 2).
RETIRED_PATTERNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("scripts/sdd/**", _ALL, "hand-copied helper; replaced by `parrot sdd <noun> <verb>` (FEAT-633)"),
    ("scripts/remove_worktree.py", _ALL, "hand-copied helper; replaced by `parrot sdd worktree list|remove`"),
    (".claude/rules/using-git-worktrees.md", ("claude",), _WT),
    (".claude/rules/worktree-status.md", ("claude",), _WT),
    (".claude/rules/worktree-start-feature.md", ("claude",), _WT),
    (".claude/rules/worktree-pr-and-clean.md", ("claude",), _WT),
    (".agent/skills/using-git-worktrees/**", ("google",), "retired Google twin; " + _WT),
    (".agent/skills/worktree-status/**", ("google",), "retired Google twin; " + _WT),
    (".agent/skills/worktree-start-feature/**", ("google",), "retired Google twin; " + _WT),
    (".agent/skills/worktree-pr-and-clean/**", ("google",), "retired Google twin; " + _WT),
    (".agent/skills/worktree-management/**", ("google",), "retired Google twin; " + _WT),
    (".agent/agents/sdd-*/**", ("google",), "old Google agent layout; now .agents/agents/sdd-*/agent.md"),
)
#: (host folder, hosts) whose direct `sdd-*` children are parrot-owned (spec §2 item 3).
SDD_PREFIX_DIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".claude/commands", _ALL),
    (".claude/agents", ("claude",)),
    (".agents/skills", ("codex", "google")),
    (".agents/agents", ("codex", "google")),
    (".agent/workflows", ("google",)),
    (".agent/skills", ("google",)),
    (".codex/agents", ("codex",)),
)
#: SDD state and team-owned files — never stale whatever the receipt says (spec §1 Non-Goals).
_PROTECTED: tuple[str, ...] = (
    "sdd/config.json",
    "sdd/specs/*",
    "sdd/tasks/*",
    "sdd/proposals/*",
    "sdd/ledger/*",
    "sdd/state/*",
)
#: Folders an install writes into; a receipt entry outside them is never a removal candidate.
RECEIPT_ROOTS: tuple[str, ...] = (".claude/", ".agent/", ".agents/", ".codex/", "sdd/", "docs/sdd/", "scripts/sdd/")
#: Host configuration that lives inside those folders but is never an installed asset.
_NEVER_STALE: tuple[str, ...] = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".codex/config.toml",
)
#: Present only in the ai-parrot monorepo (asset sources live there).
SOURCE_CHECKOUT_MARKER = Path("packages/ai-parrot/src/parrot/sdd/_assets/manifest.json")


class StaleEntry(BaseModel):
    """One stale file: repo-relative ``path``, ``reason``, human ``detail``, ``symlink`` (never followed)."""

    path: str
    reason: StaleReason
    detail: str
    symlink: bool = False


def is_source_checkout(root: Path) -> bool:
    """Return whether ``root`` is the ai-parrot monorepo."""
    return (root / SOURCE_CHECKOUT_MARKER).is_file()


def has_symlinked_ancestor(root: Path, rel_path: str) -> bool:
    """Return whether a folder between ``root`` and ``rel_path`` (exclusive) is a symlink."""
    current = root
    for part in PurePosixPath(rel_path).parts[:-1]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def is_safe_receipt_target(target: str) -> bool:
    """Return whether a receipt entry is a clean relative path inside a folder the installer writes to.

    The receipt is committed to the repository, so it is untrusted input: absolute paths, ``..``/``.``
    segments, backslashes and paths outside :data:`RECEIPT_ROOTS` are rejected.
    """
    if not target or "\\" in target or target.startswith("/"):
        return False
    parts = target.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if target in _NEVER_STALE:
        return False
    return target.startswith(RECEIPT_ROOTS)


def _walk_files(root: Path, rel_base: str) -> list[tuple[str, bool]]:
    """Return files below ``root/rel_base`` as ``(posix relpath, is_symlink)`` without following symlinks.

    A symlinked folder above ``rel_base`` counts as a symlink too: ``rel_base`` is reported once and never walked.
    """
    base = root / rel_base
    if has_symlinked_ancestor(root, rel_base):
        return [(rel_base, True)] if os.path.lexists(base) else []
    if base.is_symlink():
        return [(rel_base, True)]
    if base.is_file():
        return [(rel_base, False)]
    if not base.is_dir():
        return []

    files: list[tuple[str, bool]] = []
    for directory, dirnames, filenames in os.walk(base, followlinks=False):
        directory_path = Path(directory)
        for name in list(dirnames):
            path = directory_path / name
            if path.is_symlink():
                files.append((path.relative_to(root).as_posix(), True))
                dirnames.remove(name)
        for name in filenames:
            path = directory_path / name
            files.append((path.relative_to(root).as_posix(), path.is_symlink()))
    return files


def _retired_base(pattern: str) -> str:
    """Return the literal prefix of a glob before its first wildcard segment."""
    parts: list[str] = []
    for part in pattern.split("/"):
        if any(character in part for character in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def find_stale(root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS) -> list[StaleEntry]:
    """Return stale SDD files for ``hosts``, ordered by repository-relative path.

    Raises:
        ValueError: If a requested host is unsupported.
    """
    unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
    if unknown:
        raise ValueError(f"unknown host(s): {', '.join(unknown)} (supported: {', '.join(SUPPORTED_HOSTS)})")
    shipped = {entry["target"] for entry in load_manifest()}
    found: dict[str, StaleEntry] = {}

    def _add(path: str, reason: StaleReason, detail: str, symlink: bool) -> None:
        if path in shipped or path == RECEIPT_PATH.as_posix():
            return
        if any(fnmatch.fnmatch(path, glob) for glob in _PROTECTED):
            return
        current = found.get(path)
        if current is None or _PRECEDENCE[reason] < _PRECEDENCE[current.reason]:
            found[path] = StaleEntry(path=path, reason=reason, detail=detail, symlink=symlink)

    receipt_detail = "recorded by an earlier `parrot sdd install`; no longer shipped"
    for target in load_receipt(root)["files"]:
        if not is_safe_receipt_target(target):
            logger.warning("ignoring receipt entry %r: not a relative path inside an SDD install folder", target)
            continue
        path = root / target
        if has_symlinked_ancestor(root, target):
            if os.path.lexists(path):
                _add(target, "receipt-orphan", receipt_detail, True)
            continue
        if path.is_symlink() or path.is_file():
            _add(target, "receipt-orphan", receipt_detail, path.is_symlink())

    selected_hosts = set(hosts)
    for pattern, pattern_hosts, detail in RETIRED_PATTERNS:
        if not selected_hosts.intersection(pattern_hosts):
            continue
        base = _retired_base(pattern)
        for path, symlink in _walk_files(root, base):
            if fnmatch.fnmatch(path, pattern) or (symlink and path == base and pattern.startswith(f"{base}/")):
                _add(path, "retired", detail, symlink)

    for folder, dir_hosts in SDD_PREFIX_DIRS:
        if not selected_hosts.intersection(dir_hosts):
            continue
        directory = root / folder
        if has_symlinked_ancestor(root, folder) or not directory.is_dir() or directory.is_symlink():
            continue
        for child in sorted(directory.iterdir()):
            if not child.name.startswith("sdd-"):
                continue
            for path, symlink in _walk_files(root, child.relative_to(root).as_posix()):
                _add(path, "sdd-orphan", f"`sdd-` entry in {folder} that the package does not ship", symlink)

    return sorted(found.values(), key=lambda entry: entry.path)
