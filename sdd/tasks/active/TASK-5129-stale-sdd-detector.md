# TASK-5129: Stale SDD file detector (`parrot/sdd/stale.py`)

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 "Overview" items 1–3 and §3 Module 1. `parrot sdd install` / `uninstall` only know the **current**
manifest; files copied by hand, files from an older layout and files an older install recorded but a newer
release dropped stay forever (evidence table in spec §1). This task adds the pure, read-only computation of that
stale set. Nothing is deleted here — TASK-5132 wires removal into the installer, TASK-5135 exposes the CLI.

---

## Scope

- Create `packages/ai-parrot/src/parrot/sdd/stale.py` with `StaleReason`, `StaleEntry`, `RETIRED_PATTERNS`,
  `SDD_PREFIX_DIRS`, `SOURCE_CHECKOUT_MARKER`, `is_source_checkout()` and `find_stale()`.
- Three sources, de-duplicated with precedence `receipt-orphan` > `retired` > `sdd-orphan`:
  1. **receipt-orphan** — every key of `load_receipt(root)["files"]` that is not a current manifest target and
     exists on disk (host-neutral, always scanned).
  2. **retired** — files matched by `RETIRED_PATTERNS` whose hosts intersect `hosts`.
  3. **sdd-orphan** — direct `sdd-*` children of each `SDD_PREFIX_DIRS` folder (for the selected hosts) that
     are not manifest targets; a directory child contributes every file below it.
- Never return: a current manifest target (any host), `sdd/.sdd-installed.json`, or anything matched by
  `_PROTECTED` (SDD state, spec §1 Non-Goals).
- Never follow a symlink: a symlinked file or directory is returned once with `symlink=True` and not descended.
- Write the M1 unit tests in a new `packages/ai-parrot/tests/sdd/test_installer_stale.py`.

**NOT in scope**: deleting anything, `PlanAction` values, the receipt rewrite (TASK-5132); MCP entries
(TASK-5130/5131); the CLI (TASK-5135); `scripts/remove_worktree.py`'s replacement (TASK-5133). Do not edit
`installer.py` in this task.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/stale.py` | CREATE | Stale-set computation + source-checkout guard |
| `packages/ai-parrot/tests/sdd/test_installer_stale.py` | CREATE | M1 unit tests + `stale_repo` fixture |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.installer import SUPPORTED_HOSTS, RECEIPT_PATH, load_manifest, load_receipt  # verified: installer.py:39, :44, :136, :209
from parrot.sdd.installer import install_sdd_integration  # verified: installer.py:1059 (tests only)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
SUPPORTED_HOSTS: tuple[str, ...] = ("claude", "codex", "google")          # line 39
RECEIPT_PATH = Path("sdd/.sdd-installed.json")                             # line 44
def load_manifest() -> list[dict[str, Any]]                                # line 136; entries {"source","target","hosts",["seed": True]}
def load_receipt(root: Path) -> dict[str, Any]                             # line 209; {"files": {target: sha256}, ...}; never raises
def install_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False, portable=False,
                            base_branch=None, push_base=False, hotfix_base=None, dangerous_guard=True,
                            sdd_coder=True) -> list[str]                    # line 1059
# installer.py imports NOTHING from parrot.sdd.stale today; TASK-5132 will import stale lazily inside functions.
```

Monkeypatch target for the user-global Gemini file (used by the google host install; tests must never touch the
real home): `parrot.knowledge.wiki.google.assets.default_mcp_config_path` — same pattern as
`packages/ai-parrot/tests/mcp/conftest.py:27`.

### Does NOT Exist
- ~~`parrot.sdd.stale`~~ — created by this task.
- ~~an existing source-checkout guard in `installer.py`~~ — none; this task adds `is_source_checkout`.
- ~~a `"retired"` / `"stale"` key in `_assets/manifest.json`~~ — the retired list lives only in `stale.py`
  (`check_asset_sync.py --write` would drop a manifest key).
- ~~`installer._under` for real-path containment~~ — `_under` (installer.py:270) is lexical only; this task does
  not need it (it walks with `followlinks=False` and checks `is_symlink()` instead).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/stale.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer_stale.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#load_manifest",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#load_receipt",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Import direction**: `stale.py` imports `parrot.sdd.installer` at module level (it needs `SUPPORTED_HOSTS` for
  the `find_stale` default). TASK-5132 makes `installer.py` import `stale` **inside its functions**, so there is
  no import cycle. (The spec's M1 text describes the reverse direction; the goal — no cycle — is the same, and a
  module-level default needs the constant at import time.)
- Paths in `StaleEntry.path` are repo-relative **posix** strings of one **file** (or of the symlink itself).
- Globs use `fnmatch.fnmatch` on posix relative paths. `fnmatch`'s `*` matches `/`, so `scripts/sdd/**` matches
  every file below `scripts/sdd/` including dotfiles and `__pycache__/`.
- Walk with `os.walk(base, followlinks=False)`; check `Path.is_symlink()` on the base and on every dir/file name
  before reporting or descending. Never use `Path.glob` / `rglob`.
- `logger = logging.getLogger(__name__)`; no `print`. Google docstrings, 120 columns.

### References in Codebase
- `scripts/sdd/check_asset_sync.py:30-43` — the globs that define what ships (why these folders are parrot-owned).
- Spec §2 item 2 — the exact retired list; §1 Non-Goals — what must never be reported.

---

## Implementation Blueprint

### Steps (in order)
1. Create `stale.py` with the constants exactly as below — *why*: the lists are spec-fixed (§2) and TASK-5132's
   tests assert reasons/details from them.
2. Implement `_walk_files(root, rel_base)` — *why*: one symlink-safe walker serves both retired `**` patterns and
   `sdd-*` directory children.
3. Implement `find_stale()` source by source, then merge by precedence — *why*: a path found by two sources keeps
   only the highest reason (spec §2 "These rules apply…").
4. Write the tests with the `stale_repo` fixture — *why*: AC-1..AC-8 are proved only against a real install.

### `packages/ai-parrot/src/parrot/sdd/stale.py` (CREATE)
```python
"""Stale SDD files: hand-copied, retired or no-longer-shipped files left in a repository (FEAT-795 M1).

Read-only: computes the stale set and the source-checkout guard; never writes or deletes.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
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
    "sdd/config.json", "sdd/specs/*", "sdd/tasks/*", "sdd/proposals/*", "sdd/ledger/*", "sdd/state/*",
)
#: present only in the ai-parrot monorepo (asset sources live there).
SOURCE_CHECKOUT_MARKER = Path("packages/ai-parrot/src/parrot/sdd/_assets/manifest.json")


class StaleEntry(BaseModel):
    """One stale file: repo-relative ``path``, ``reason``, human ``detail``, ``symlink`` (never followed)."""

    path: str
    reason: StaleReason
    detail: str
    symlink: bool = False


def is_source_checkout(root: Path) -> bool:
    """True when ``root`` is the ai-parrot monorepo (``SOURCE_CHECKOUT_MARKER`` exists)."""
    return (root / SOURCE_CHECKOUT_MARKER).is_file()


def _walk_files(root: Path, rel_base: str) -> list[tuple[str, bool]]:
    """Every file below ``root/rel_base`` as ``(posix relpath, is_symlink)``; symlinks are reported, never descended.

    ``rel_base`` itself may be a file or a symlink; a missing base yields ``[]``.
    """
    # FILL IN: base = root / rel_base; if base.is_symlink() -> [(rel_base, True)]; if base.is_file() -> [(rel_base,
    #   False)]; if not base.is_dir() -> []; else os.walk(base, followlinks=False): for each name in dirnames that is
    #   a symlink, report it (True) and remove it from dirnames; for each filename report (relpath, is_symlink).
    #   Relpaths are Path(...).relative_to(root).as_posix(). Bounded by AC-6 (symlinks never followed).
    raise NotImplementedError


def _retired_base(pattern: str) -> str:
    """The literal folder prefix of ``pattern`` before its first wildcard segment (walk root for the glob)."""
    # FILL IN: split on "/", keep segments until one contains any of "*?["; join them back — e.g.
    #   "scripts/sdd/**" -> "scripts/sdd", ".agent/agents/sdd-*/**" -> ".agent/agents", a literal path -> itself.
    raise NotImplementedError


def find_stale(root: Path, hosts: Sequence[str] = SUPPORTED_HOSTS) -> list[StaleEntry]:
    """Stale SDD files for ``hosts`` (receipt orphans always), sorted by path, de-duplicated with reason
    precedence receipt-orphan > retired > sdd-orphan. Current manifest targets and seeds are never returned.
    Symlinks are returned with ``symlink=True`` and never descended.

    Raises:
        ValueError: an unknown host.
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

    # FILL IN: (1) receipt orphans — for target in load_receipt(root)["files"]: p = root / target; add when
    #   p.is_symlink() or p.is_file(), detail "recorded by an earlier `parrot sdd install`; no longer shipped".
    # FILL IN: (2) retired — for (glob, pattern_hosts, why) in RETIRED_PATTERNS with set(pattern_hosts) & set(hosts):
    #   for (rel, link) in _walk_files(root, _retired_base(glob)): add when fnmatch(rel, glob) or (link and the
    #   symlink is the walk base itself, e.g. a symlinked `scripts/sdd`), detail = why.
    # FILL IN: (3) sdd-orphans — for (folder, dir_hosts) in SDD_PREFIX_DIRS with overlap: for child in
    #   sorted((root / folder).iterdir()) if the folder is a real directory (not a symlink) and
    #   child.name.startswith("sdd-"): every (rel, link) of _walk_files(root, child relpath) that is not shipped,
    #   detail f"`sdd-` entry in {folder} that the package does not ship".
    #   Bounded by AC-3 (host filtering) and AC-4 (non-SDD files never reported).
    return sorted(found.values(), key=lambda entry: entry.path)
```
**Why this shape**: constants and the merge/filters are spec-fixed, so they are written out; only the three
filesystem walks are left to you. `_add` centralises the "never stale" rules so no source can bypass them.
Keep `find_stale`'s signature exactly — TASK-5132 and TASK-5135 call it positionally.

### `packages/ai-parrot/tests/sdd/test_installer_stale.py` (CREATE)
```python
"""FEAT-795 M1/M2 — stale SDD files (`parrot sdd uninstall --stalled`)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from parrot.sdd.installer import SUPPORTED_HOSTS, install_sdd_integration
from parrot.sdd.stale import SOURCE_CHECKOUT_MARKER, find_stale, is_source_checkout


@pytest.fixture
def gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the user-global Gemini MCP file — tests never touch the real home."""
    path = tmp_path / "gemini_home" / "mcp_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr("parrot.knowledge.wiki.google.assets.default_mcp_config_path", lambda: path)
    return path


@pytest.fixture
def stale_repo(tmp_path: Path, gemini: Path) -> Path:
    """A git repo after `install_sdd_integration(root, SUPPORTED_HOSTS)` plus hand-made orphans:
    scripts/sdd/{reserve_ids.py,__pycache__/x.pyc}, .claude/rules/worktree-status.md,
    .agent/agents/sdd-worker/agent.md, .claude/commands/sdd-insight.md, and a receipt entry for a dropped asset."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    install_sdd_integration(root, SUPPORTED_HOSTS, sdd_coder=False)
    # FILL IN: create the orphan files listed in the docstring, plus `.claude/commands/sdd-dropped.md`, and record
    #   `.claude/commands/sdd-dropped.md` as a key of sdd/.sdd-installed.json["files"] (json load, set, dump) — it
    #   is the "dropped asset" receipt-orphan.
    return root


def _paths(entries: list) -> dict[str, str]:
    return {e.path: e.reason for e in entries}


# FILL IN: one test per row of spec §4 "Unit Tests" with Module = M1:
#   test_receipt_orphan_detected, test_retired_scripts_sdd_tree (incl. `.collision_baseline.json`),
#   test_legacy_agent_layout_google_only, test_sdd_prefix_orphan_file_and_dir, test_current_targets_and_seeds_never_stale
#   (fresh install -> find_stale == []), test_non_sdd_files_untouched, test_reason_precedence, test_symlink_not_followed
#   (scripts/sdd symlinked to tmp_path/"outside" -> one entry, symlink=True), test_source_checkout_detected,
#   test_retired_remove_worktree_script, plus test_unknown_host_raises (ValueError).
```
**Why**: the `gemini` fixture is mandatory because the google host writes the user-global MCP file; `sdd_coder=False`
keeps MCP toolkit registration out of these file-only tests. TASK-5132 appends its M2 tests to this same file.

### FILL IN checklist
- [ ] `stale.py::_walk_files` — symlink-safe walk; bounded by AC-6.
- [ ] `stale.py::_retired_base` — literal prefix before the first wildcard segment.
- [ ] `stale.py::find_stale` — the three sources via `_add`; bounded by AC-1..AC-5.
- [ ] `test_installer_stale.py::stale_repo` + the 11 tests listed.

---

## Acceptance Criteria

- [ ] AC-1: a receipt key that is not a manifest target and exists on disk → `receipt-orphan`.
- [ ] AC-2: `scripts/sdd/a.py`, `scripts/sdd/__pycache__/a.pyc`, `scripts/sdd/.collision_baseline.json` and
      `scripts/remove_worktree.py` → `retired`; an installed `.claude/commands/remove-worktree.md` is not stale.
- [ ] AC-3: `.agent/agents/sdd-worker/agent.md` is stale for `google`, not reported for `hosts=("claude",)`.
- [ ] AC-4: right after a full install `find_stale(root)` == `[]`; `.codex/config.toml`,
      `.codex/skills/parrot-wiki/SKILL.md`, `.claude/rules/python-development.md` are never reported.
- [ ] AC-5: a receipt-recorded `scripts/sdd/x.py` is reported once, as `receipt-orphan`.
- [ ] AC-6: a symlinked `scripts/sdd` → one entry `symlink=True`; the target folder is not walked.
- [ ] AC-7: `is_source_checkout` is True only when `SOURCE_CHECKOUT_MARKER` exists; unknown host → `ValueError`.
- [ ] `ruff check packages/ai-parrot/src/parrot/sdd/stale.py packages/ai-parrot/tests/sdd/test_installer_stale.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_installer_stale.py -q`

---

## Test Specification

See the blueprint test file; the named tests are spec §4 "Unit Tests" rows with Module M1 plus
`test_retired_remove_worktree_script` and `test_unknown_host_raises`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug parrot-sdd-install-remove --feature-id FEAT-795`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/parrot-sdd-install-remove.json`
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5129 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: import direction — `stale.py` imports `installer` at module level; `installer.py`
imports `stale` lazily (TASK-5132). Same no-cycle goal as spec §3 M1.
