# TASK-3476: Daily prune git-hook installer — `install_hooks.py`

**Feature**: FEAT-577 — `/sdd-spec` Intake Mode — Interview-Driven Spec Creation
**Spec**: `sdd/specs/sdd-feature-specification.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3473
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 11** (G13, revision 0.3). `/sdd-status` stays
read-only, so retention runs automatically from git hooks. An idempotent
installer adds a marker-delimited block to the `post-checkout`, `post-merge`
and `post-commit` hooks. The block calls
`python -m scripts.sdd.prune_intake --daily --apply` (TASK-3473), whose stamp
gate limits it to once a day. It follows the marker-block convention of the
existing parrot-wiki hook installed by `parrot claude install`.

---

## Scope

- Create `scripts/sdd/install_hooks.py` with `hooks_dir`, `render_block`,
  `install`, `uninstall`, `main` (spec Module 11 signatures).
- Create `tests/sdd_scripts/test_install_hooks.py`.

**NOT in scope**: running the installer on anyone's machine, changing
`core.hooksPath`, touching `.githooks/pre-commit`, or editing the parrot-wiki
block.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/install_hooks.py` | CREATE | idempotent hook-block installer/uninstaller |
| `tests/sdd_scripts/test_install_hooks.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# stdlib only: argparse, stat, subprocess, sys, pathlib
```

### Existing Anchors
- The existing wiki hook block (`.git/hooks/post-merge`, verified 2026-09-19), which is the convention to mirror:
  ```sh
  #!/bin/sh
  # >>> parrot-wiki post-commit >>>
  # Keep the LLM-wiki knowledge graph in sync with the last commit.
  # Installed by `parrot claude install`; remove with `parrot claude uninstall`.
  # FEAT-566: skip the structural upsert inside a linked worktree
  # (a worktree's .git is a file, never a directory).
  if [ ! -f .git ]; then
      /home/jesuslara/proyectos/ai-parrot/.venv/bin/wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true
  fi
  # <<< parrot-wiki post-commit <<<
  ```
- `git rev-parse --git-path hooks` returns the effective hooks dir and honours `core.hooksPath`.
- **Local hazard**: the author's `.git/config` sets `core.hooksPath=/home/jesuslara/proyectos/navigator/ai-parrot/.git/hooks`, which **does not exist**, so git currently runs no hooks there. The installer must detect this (hooks dir missing) and exit 2 with a message naming `core.hooksPath`. It must never `mkdir` the dir or rewrite the config.
- CLI pattern: `scripts/sdd/check_task_graph.py:445` `def main(argv: list[str] | None = None) -> int:`.
- TASK-3473: `python -m scripts.sdd.prune_intake --daily --apply` (exit 0 even outside a repo / within the 24 h window).

### Does NOT Exist
- ~~`scripts/sdd/install_hooks.py`~~ — created here.
- ~~A `parrot claude install` Python API to reuse~~ — not verified; do not import it. Mirror its marker convention in a standalone script.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/install_hooks.py", "action": "CREATE"},
    {"path": "tests/sdd_scripts/test_install_hooks.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- **Never break git**: the block runs in a subshell, with all output to
  `/dev/null` and `|| true`. A post-* hook's exit code doesn't abort the
  operation, but it must still stay silent and fast.
- **Primary checkout only**: guard with `[ -d .git ]`, because a linked
  worktree's `.git` is a file. Staging lives in the primary checkout.
- **Absolute paths**: embed `sys.executable` and the repo root (`cd "<root>"`
  inside the subshell), because hooks run with an arbitrary PATH and venv.
- **Idempotent**: replace everything between the markers; never duplicate. Keep all other bytes unchanged.
- New hook file: `#!/bin/sh\n` + block, `chmod` user/group/other execute bits added (`stat.S_IXUSR | S_IXGRP | S_IXOTH`).
- `post-checkout` receives args, which the block ignores.

---

## Implementation Blueprint

### Steps (in order)
1. Write `install_hooks.py`. *Why*: spec M11. A reviewed script beats hand-editing `.git/hooks`.
2. Write the tests against a `tmp_path` hooks dir. *Why*: never touch the real `.git/hooks` in tests.

### `scripts/sdd/install_hooks.py` (CREATE)
```python
"""``install_hooks.py`` — install the daily /sdd-spec intake prune git hook (FEAT-577).

Adds a marker-delimited block to post-checkout / post-merge / post-commit in the
effective hooks directory (``git rev-parse --git-path hooks``). The block runs
``python -m scripts.sdd.prune_intake --daily --apply`` from the primary checkout;
the ``--daily`` stamp limits it to once per 24 h. Idempotent; ``--uninstall``
removes only this block. Refuses (exit 2) when the hooks directory is missing.
"""

from __future__ import annotations

import argparse
import stat
import subprocess
import sys
from pathlib import Path

MARKER_BEGIN: str = "# >>> sdd-intake-prune >>>"
MARKER_END: str = "# <<< sdd-intake-prune <<<"
HOOK_EVENTS: tuple[str, ...] = ("post-checkout", "post-merge", "post-commit")
SHEBANG: str = "#!/bin/sh\n"


def hooks_dir(repo_root: Path) -> Path:
    """Resolve ``git rev-parse --git-path hooks`` against ``repo_root`` (honours core.hooksPath)."""
    out = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"], cwd=repo_root, capture_output=True, text=True, check=True
    ).stdout.strip()
    path = Path(out)
    return path if path.is_absolute() else (repo_root / path).resolve()


def render_block(python: str, repo_root: Path) -> str:
    """The marker-delimited shell block: primary checkout only; prune --daily --apply; never fails."""
    return (
        f"{MARKER_BEGIN}\n"
        "# Prune /sdd-spec intake staging older than 10 days, at most once a day (FEAT-577).\n"
        "# Installed by `python -m scripts.sdd.install_hooks`; remove with `--uninstall`.\n"
        "if [ -d .git ]; then\n"
        f'    ( cd "{repo_root}" && "{python}" -m scripts.sdd.prune_intake --daily --apply ) >/dev/null 2>&1 || true\n'
        "fi\n"
        f"{MARKER_END}\n"
    )


def _strip_block(text: str) -> str:
    """Remove an existing sdd-intake-prune block (markers inclusive); return the rest unchanged."""
    # FILL IN: locate MARKER_BEGIN line .. MARKER_END line (inclusive, incl. its newline); return text without it;
    # unchanged when absent — bounded by "keep all other bytes unchanged"


def install(hooks: Path, block: str, events: tuple[str, ...] = HOOK_EVENTS) -> list[Path]:
    """Add or replace the block in each hook; create + chmod +x missing hooks. Raises FileNotFoundError when ``hooks`` is missing."""
    if not hooks.is_dir():
        raise FileNotFoundError(hooks)
    # FILL IN: per event: existing text (or SHEBANG when absent) → _strip_block → ensure trailing "\n" → append block;
    # write; add exec bits; collect paths — bounded by idempotency + test_install_preserves_other_blocks


def uninstall(hooks: Path, events: tuple[str, ...] = HOOK_EVENTS) -> list[Path]:
    """Remove only the sdd-intake-prune block from each hook; leave everything else byte-identical."""
    # FILL IN: per existing hook containing MARKER_BEGIN: write _strip_block(text); collect paths — bounded by M11


def main(argv: list[str] | None = None) -> int:
    """CLI: [--uninstall] [--repo-root]. Exit 0; 2 when the hooks dir is missing (message names core.hooksPath)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    # FILL IN: repo_root = args.repo_root.resolve(); hooks = hooks_dir(repo_root); if not hooks.is_dir(): print
    # "hooks directory <hooks> does not exist — check `git config core.hooksPath`; nothing installed" and return 2;
    # install(hooks, render_block(sys.executable, repo_root)) or uninstall(hooks); print one line per hook; return 0
    # — bounded by "never mkdir / never rewrite core.hooksPath"


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: signatures, markers and events are fixed by spec Module 11.
`_strip_block` is the single place that edits hook content, so install and
uninstall can't diverge.

### `tests/sdd_scripts/test_install_hooks.py` (CREATE)
```python
"""Tests for scripts/sdd/install_hooks.py (FEAT-577, spec §4 Module 11)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.sdd.install_hooks import HOOK_EVENTS, MARKER_BEGIN, install, main, render_block, uninstall

_WIKI_BLOCK = (
    "# >>> parrot-wiki post-commit >>>\n"
    "wikitoolkit upsert --changed --quiet >/dev/null 2>&1 || true\n"
    "# <<< parrot-wiki post-commit <<<\n"
)


@pytest.fixture
def hooks(tmp_path: Path) -> Path:
    d = tmp_path / "hooks"
    d.mkdir()
    return d


@pytest.fixture
def block(tmp_path: Path) -> str:
    return render_block("/usr/bin/python3", tmp_path)


# FILL IN: test_install_creates_missing_hooks (3 files, shebang, one MARKER_BEGIN, os.access X_OK),
# test_install_is_idempotent, test_install_preserves_other_blocks (pre-seed "#!/bin/sh\n" + _WIKI_BLOCK; after
# install+uninstall the file is byte-identical), test_uninstall_removes_only_its_block,
# test_missing_hooks_dir_exits_2 (install raises FileNotFoundError; main(["--repo-root", <repo whose hooksPath is
# missing>]) == 2 — build it with `git init` + `git config core.hooksPath <tmp>/nope` in tmp_path; nothing created),
# test_block_never_fails_git ("[ -d .git ]", "--daily --apply", "|| true" in block) — bounded by spec §4 M11 rows
```

### FILL IN checklist
- [ ] `_strip_block`, `install`, `uninstall`, `main` bodies
- [ ] the six tests

---

## Acceptance Criteria

- [ ] `python -m scripts.sdd.install_hooks` adds exactly one `sdd-intake-prune` block to `post-checkout`, `post-merge`, `post-commit` (creating executable hooks when missing), and re-running changes nothing
- [ ] Other hook content (e.g. the parrot-wiki block) is preserved byte-for-byte; `--uninstall` removes only its block
- [ ] A missing hooks dir (incl. a dangling `core.hooksPath`) ⇒ exit 2, a message naming `core.hooksPath`, and nothing created
- [ ] The block runs only in the primary checkout and can never fail or print during a git operation
- [ ] `pytest tests/sdd_scripts/test_install_hooks.py -q` passes; `ruff check scripts/sdd/install_hooks.py` is clean

---

## Validation Commands

- `pytest tests/sdd_scripts/test_install_hooks.py -q`

---

## Test Specification

See the blueprint test module.

---

## Agent Instructions

1. Read spec §2 "Staging retention" and §3 Module 11.
2. Confirm TASK-3473 is done (`prune_intake --daily` exists).
3. Implement; run the Validation Commands and `ruff check scripts/sdd/install_hooks.py`.
4. Do **not** run the installer against the real repository as part of the task.
5. Move this file to `sdd/tasks/completed/` and set the index status to `done`.

---

## Completion Note

*(Agent fills this in when done)*
