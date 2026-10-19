# TASK-4085: SDD helpers move A: ledger/worktree helpers into parrot.sdd.scripts

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4070
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6: "The 18 doc-referenced helpers (…) move to `parrot/sdd/scripts/`;
ALL markdown (installed AND monorepo) references the single form
`python -m parrot.sdd.scripts.<name>` …; `scripts/sdd/*.py` become thin wrappers (import +
main) for direct-invocation compatibility". The spec §5 acceptance bullet requires that
"`scripts/sdd/` wrappers keep the monorepo's existing invocations working".

This is the first of the move tasks (TASK-4085–4088, TASK-4508). It creates the
`parrot.sdd.scripts` package and moves the **ID-ledger and worktree** helpers: `id_ledger`,
`reserve_ids`, `check_id_collisions`, `ensure_worktree`, plus `brief_meta` (rev 0.4 C17) and
`worktree_environment` (rev 0.3 C16). It also adds `parrot.sdd.scripts.sdd_meta`, a
re-export of `parrot.knowledge.wiki.ledger.sdd_meta`, so every moved module can import
`sdd_meta` from inside the package. `scripts/sdd/sdd_meta.py` itself is **already** a
re-export shim (the precedent) and is **not changed**.

> ⚠️ **LIVE INFRASTRUCTURE.** `reserve_ids` and `ensure_worktree` are run concurrently by
> other sessions (`/sdd-spec`, `/sdd-task`, `/sdd-start`, `sdd-worker`, the dev-loop
> orchestrators). The `scripts/sdd/` shim must keep `python -m scripts.sdd.reserve_ids …`
> and `python -m scripts.sdd.ensure_worktree …` **byte-for-byte identical**: the same
> stdout lines, stderr, exit codes and argparse `--help` text. **Never change their CLI**:
> no renamed or added flags, no changed `prog=`/`description=`, no reworded output. The
> moved file must differ from the original ONLY in the import lines listed in the
> blueprint.

---

## Amendments — spec rev 0.3 (2026-10-17)

Folded in on 2026-10-19 from spec §3 M6 *[rev 0.3 C16]* and
`sdd/proposals/parrot-installer-amendments.proposal.md` §3 C16 ("Amends: TASK-4085 (move +
shim)"; approved by Jesus Lara, 2026-10-17).

- **C16 — `worktree_environment` relocates to a light parent.** The shipped `sdd-coder` /
  `sdd-worker` frontmatter addresses `flows/dev_loop/worktree_environment.py` by monorepo path,
  and `python -m parrot.flows.dev_loop.worktree_environment` is not an option because
  `parrot.flows.dev_loop` imports the whole dev-loop stack at module load. Spec text: "the module
  itself moves to `parrot/sdd/scripts/` (light parent) and leaves a re-export shim behind … for
  its three in-core importers". This task does only that move + shim. The launcher fast path
  (TASK-4072), the frontmatter rewrite (TASK-4089), the widened `test_no_repo_script_refs`
  (TASK-4090) and the C3 coverage (TASK-4091) belong to other tasks. **Implementation of the C16
  rows is gated by the open decisions in the Readiness review below.**

---

## Amendments — spec rev 0.4 (2026-10-18)

Folded in from `sdd/proposals/parrot-installer-amendments.proposal.md` §3 C17 (decision by
Jesus Lara, 2026-10-18). Every section below is already edited to match.

- **C17 — `brief_meta` moves with the worktree helpers.** FEAT-698 (merged 2026-10-17)
  added `scripts/sdd/brief_meta.py` (pydantic `BriefMeta`, `brief_worktree_plan`,
  `write_brief_index`, …; 8.4 KB, no `main()`), and `scripts/sdd/ensure_worktree.py:20` now
  imports `brief_worktree_plan` from it. A moved `ensure_worktree` that still imports
  `scripts.sdd.brief_meta` is a monorepo import in a foreign repo, so `brief_meta.py` is the
  fifth `git mv` of this task: rewrite its `scripts.sdd.sdd_meta` import (`:19`) to
  `parrot.sdd.scripts.sdd_meta`, rewrite both imports of the moved `ensure_worktree.py`
  (`:20` brief_meta, `:21` sdd_meta — line numbers corrected 2026-10-19), leave the alias shim
  at `scripts/sdd/brief_meta.py`. It is a library
  module: the `--help` parity test does not cover it (`MOVED_LIBS`); TASK-4299 adds its
  argparse `main()`. `tests/sdd_scripts/test_brief_meta.py` keeps importing
  `scripts.sdd.brief_meta` through the shim, unmodified.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: completed the rev 0.4 C17 `brief_meta` fold-in (CREATE +
  shim blocks, `ensure_worktree` brief_meta import rewrite, "four" → "five" in steps/ACs/checklist);
  corrected `ensure_worktree.py` anchors (imports `:20`/`:21`, 379 lines, `main` `:265`,
  `ArgumentParser` `:273`, `Path.cwd()` `:343`, `__main__` `:378`); pydantic pin is now
  `"pydantic>=2.12.5,<3"`; added the three brief suites to Validation Commands; folded in the
  rev 0.3 C16 move of `flows/dev_loop/worktree_environment.py` + re-export shim (the proposal's
  `sdd_coder/background.py:49` importer is now `:57`).
- Open decisions — do not implement the affected part until resolved (spec rev 0.5 / owner):
  - **C16 kernel lookup.** `_load_guard_bash` (`flows/dev_loop/worktree_environment.py:294-307`)
    imports `.test_scope.guard` relative to its package, or top-level `test_scope` from its own
    directory when run as a script. After the move neither resolves, and `_scope_guard`
    (`:336-340`) turns the ImportError into "allow": the FEAT-563 over-broad-pytest guard would be
    silently disabled, and `test_worktree_environment.py:273-283` would fail. A package-relative
    kernel path (as TASK-4086 does for `check_task_graph`) is not in the spec text.
  - **C16 shim form and by-path callers.** Live hooks run the OLD path by file with bare `python3`
    and `|| exit 2` (`.claude/agents/sdd-coder.md:21`, `.claude/agents/sdd-worker.md:32`,
    `flows/dev_loop/_subagent_data/sdd-{coder,worker}.md:21/32`), and `dispatchers/claude.py:625`
    builds `[sys.executable, Path(worktree_environment.__file__).resolve(), "--hook"]` (proposal §3
    C16 item 3, now owned by TASK-4509, which depends on this task). Until TASK-4509/4089 land, a shim that is not runnable by
    path without `parrot` importable denies every `sdd-coder`/`sdd-worker` tool call. Decide the
    shim form (by-path `__main__` + bare-interpreter fallback, like TASK-4088's `insight` shim?)
    and what `claude.py:625` points at; `test_worktree_environment.py:231-236,286-295` depend on it.

---

## Scope

- Create `parrot/sdd/scripts/__init__.py` (docstring only, no imports).
- Create `parrot/sdd/scripts/sdd_meta.py`, re-exporting the same 15 names as
  `scripts/sdd/sdd_meta.py`.
- Move `id_ledger.py`, `reserve_ids.py`, `check_id_collisions.py`, `ensure_worktree.py` and
  `brief_meta.py` *(rev 0.4 C17)* from `scripts/sdd/` to `packages/ai-parrot/src/parrot/sdd/scripts/`
  **with `git mv`** to keep history. Then rewrite only their `from scripts.sdd…` import
  lines.
- Recreate each `scripts/sdd/<name>.py` as the alias shim. The module object becomes
  identical to the moved module, so existing tests that monkeypatch private names keep
  working.
- *(rev 0.3 C16 — gated by the Readiness review open decisions)* `git mv`
  `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` to
  `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py`; the old path becomes a
  re-export shim for its three in-core importers (`flows/dev_loop/dispatchers/claude.py:66`,
  `flows/dev_loop/dispatchers/llm.py:58`, `flows/dev_loop/sdd_coder/background.py:57`).
- Add `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py`.

**NOT in scope**:
- Moving any other helper (TASK-4086/4087/4088).
- Rewriting markdown references (TASK-4089).
- Docstring `Usage:` lines that still say `python -m scripts.sdd.<name>` (e.g.
  `id_ledger.py:14,176`, `reserve_ids.py:22`, `check_id_collisions.py:18`,
  `ensure_worktree.py:6`). Leave them. They are not CLI behaviour, and TASK-4089 owns the
  reference rewrite.
- Changing `scripts/sdd/sdd_meta.py` or `scripts/sdd/__init__.py`.
- Changing any test under `tests/sdd_scripts/`. The shim keeps them passing unmodified.
- *(C16)* The launcher fast path for `parrot sdd run worktree_environment --hook` (TASK-4072),
  rewriting the `sdd-coder`/`sdd-worker` frontmatter hooks (TASK-4089), widening
  `test_no_repo_script_refs` (TASK-4090), C3 foreign-repo coverage (TASK-4091), and
  `dispatchers/claude.py:625` (open decision — see Readiness review).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/__init__.py` | CREATE | Package marker; docstring only |
| `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` | CREATE | Re-export of `parrot.knowledge.wiki.ledger.sdd_meta` |
| `packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py` | CREATE | `git mv` of `scripts/sdd/id_ledger.py` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py` | CREATE | `git mv` of `scripts/sdd/reserve_ids.py` + 1 import rewrite |
| `packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py` | CREATE | `git mv` of `scripts/sdd/check_id_collisions.py` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` | CREATE | `git mv` of `scripts/sdd/ensure_worktree.py` + 2 import rewrites (`brief_meta` at `:20` — rev 0.4 C17, `sdd_meta` at `:21`) |
| `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` | CREATE | `git mv` of `scripts/sdd/brief_meta.py` + 1 import rewrite (`:19`, `sdd_meta`) — rev 0.4 C17 |
| `scripts/sdd/id_ledger.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/reserve_ids.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/check_id_collisions.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/ensure_worktree.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/brief_meta.py` | MODIFY | Becomes alias shim (rev 0.4 C17) |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | CREATE | `git mv` of `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` (rev 0.3 C16 — gated, see Readiness review) |
| `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` | MODIFY | Becomes re-export shim for its three in-core importers (rev 0.3 C16 — gated) |
| `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` | CREATE | Importability, `-m --help`, shim identity, help parity |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# re-export source (all verified in packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py)
from parrot.knowledge.wiki.ledger.sdd_meta import (
    KNOWN_BRANCHES,   # :30
    WORK_KIND_FLOW,   # :35
    KNOWN_PROJECTS,   # :45
    PROJECT_ALIASES,  # :84
    FlowMeta,         # :99
    parse,            # :129
    emit,             # :156
    normalize_tag,    # :173
    normalize_project,# :188
    DocTaxonomy,      # :218
    parse_taxonomy,   # :247
    resolve_flow,     # :263
    WORKTREE_ROOT,    # :322
    WorktreePlan,     # :328
    plan_worktree,    # :336
)
# sdd_meta's own third-party imports: yaml (:20), pydantic (:21) — both core deps
# (packages/ai-parrot/pyproject.toml: "pydantic>=2.12.5,<3", "PyYAML>=6.0.2" — re-verified 2026-10-19).
# Importing it is light: 0.16 s, no navconfig, no chdir (verified 2026-10-05).
```

### Existing Signatures to Use
```python
# scripts/sdd/sdd_meta.py (26 lines) — the PRECEDENT re-export shim; re-exports exactly the 15 names above,
# lines 10-26 `from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401 ... )`. NOT modified.

# scripts/sdd/id_ledger.py (220 lines)
LEDGER_PATH = Path("sdd/tasks/.id_ledger.json")                     # :28  (cwd-relative — fine, not __file__)
def main(argv: list[str] | None = None) -> int:                      # :175 (subparsers required=True :180)
if __name__ == "__main__": raise SystemExit(main())                  # :219-220
#   third-party: `from pydantic import BaseModel, Field` (:25) — core. No __file__/parents[/subprocess.

# scripts/sdd/reserve_ids.py (657 lines)
from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger  # :42  ← REWRITE
def main(argv: list[str] | None = None) -> int:                      # :616 (ArgumentParser :626, no prog=)
if __name__ == "__main__": raise SystemExit(main())                  # :656-657
#   subprocess: git only, via subprocess.run at :121 (no scripts/sdd or `-m scripts.sdd` spawn).
#   repo root: `root = repo_root if repo_root is not None else Path.cwd()` (:541) — cwd, fine.
#   third-party: `from pydantic import BaseModel, Field, ValidationError` (:40) — core.
#   No __file__ / parents[.

# scripts/sdd/check_id_collisions.py (327 lines)
def main(argv: list[str] | None = None) -> int:                      # :254 (ArgumentParser :264, no prog=)
if __name__ == "__main__": raise SystemExit(main())                  # :326-327
#   defaults cwd-relative Path("sdd/tasks/index") etc. (:82-85, :267-270). pydantic (:30) — core.
#   No inter-import, no __file__, no subprocess.

# scripts/sdd/ensure_worktree.py (379 lines — re-verified 2026-10-19 on dev 9f51c7735)
from scripts.sdd.brief_meta import brief_worktree_plan                     # :20 ← REWRITE (rev 0.4 C17)
from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow  # :21 ← REWRITE
def main(argv: Sequence[str] | None = None) -> int:                  # :265 (ArgumentParser :273, description= only, no prog=)
    repo_root = Path.cwd()                                            # :343 — cwd, fine
if __name__ == "__main__":  # pragma: no cover                       # :378-379 raise SystemExit(main())
#   subprocess: git only (:32, :223, :233). Stdlib + sdd_meta + brief_meta only. No __file__ / parents[.

# scripts/sdd/brief_meta.py (232 lines; rev 0.4 C17) — library module, NO main() (TASK-4299 adds it)
from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan          # :19 ← REWRITE
def parse_brief(doc_path: Path) -> BriefMeta:                         # :123
def brief_worktree_plan(*, slug: str, key: str, base_branch: str) -> WorktreePlan:   # :150
def write_brief_index(meta: BriefMeta, tasks: list[dict[str, Any]], worktree_root: Path) -> Path:  # :187
#   third-party: yaml (:16), pydantic (:17) — core. No __file__ / parents[ / subprocess.

# packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py (484 lines; rev 0.3 C16, git mode 100644)
#   stdlib-only (:9-17); "can run directly as a Claude hook, even when importing the rest of Parrot is
#   unavailable" (docstring :1-5).
def main() -> None:                                                   # :464 — NO argv; --hook required (:467)
if __name__ == "__main__": main()                                     # :483-484
def _load_guard_bash() -> Any:                                        # :294-307 — `.test_scope.guard` when
#   __package__ is set, else top-level `test_scope.guard` from this file's directory (see open decision)
#   in-core importers (keep working through the shim):
#     flows/dev_loop/dispatchers/claude.py:66   from parrot.flows.dev_loop import worktree_environment
#     flows/dev_loop/dispatchers/llm.py:58      from parrot.flows.dev_loop.worktree_environment import
#                                               command_policy_error, protected_argv, validate_write_path
#     flows/dev_loop/sdd_coder/background.py:57 from parrot.flows.dev_loop.worktree_environment import protected_argv
#   by-path callers: dispatchers/claude.py:625 (sys.executable + __file__ + --hook);
#     .claude/agents/sdd-coder.md:21, sdd-worker.md:32 and _subagent_data/ copies (bare python3 + monorepo path)

# Existing tests that must keep passing through the shim (all verified to exist):
#   tests/sdd_scripts/test_id_ledger.py           (from scripts.sdd.id_ledger import IdLedger, bootstrap_ledger, …  :7)
#   tests/sdd_scripts/test_reserve_ids.py         (monkeypatches subprocess.run globally :151)
#   tests/sdd_scripts/test_check_id_collisions.py (imports private _id_sort_key :225)
#   tests/sdd_scripts/test_ensure_worktree.py     (from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure, main :11)
#   tests/sdd_scripts/test_sdd_meta.py, tests/sdd_scripts/test_worktree_plan.py (sdd_meta shim — unchanged)
#   tests/sdd_scripts/test_brief_meta.py                (from scripts.sdd.brief_meta import (…) :11 — rev 0.4 C17)
#   tests/sdd_scripts/test_brief_scaffold_integration.py (brief_meta + ensure_worktree main :12-13)
#   tests/sdd_scripts/test_brief_template_contract.py   (from scripts.sdd.brief_meta import parse_brief :7)
#   packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
#       (from parrot.flows.dev_loop import worktree_environment as policy :17; monkeypatches policy.* — C16)
```

### Does NOT Exist
- ~~`parrot.sdd.scripts`~~ — created here. `parrot/sdd/__init__.py` comes from TASK-4070.
- ~~`parrot.sdd.scripts.close_task` / `heal_orphans`~~ — TASK-4087. Never import them here.
- ~~A `prog=` argument on the reserve_ids / ensure_worktree / id_ledger /
  check_id_collisions parsers~~ — none exists. Help text derives `prog` from
  `sys.argv[0]`'s basename, which is the same (`<name>.py`) for both
  `-m scripts.sdd.<name>` and `-m parrot.sdd.scripts.<name>`. Keep it that way.
- ~~Any `__file__`-based repo-root derivation in these five modules~~ — none (grep-verified,
  `brief_meta` included 2026-10-19). `worktree_environment` derives no repo root from `__file__`
  either, but resolves its `test_scope` kernel relative to its own location (open decision).
- ~~`parrot.sdd.scripts.test_scope`~~ — does not exist; the kernel stays at
  `parrot/flows/dev_loop/test_scope/`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/__init__.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py", "action": "CREATE"},
    {"path": "scripts/sdd/id_ledger.py", "action": "MODIFY"},
    {"path": "scripts/sdd/reserve_ids.py", "action": "MODIFY"},
    {"path": "scripts/sdd/check_id_collisions.py", "action": "MODIFY"},
    {"path": "scripts/sdd/ensure_worktree.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py", "action": "CREATE"},
    {"path": "scripts/sdd/brief_meta.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#FlowMeta",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#emit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_tag",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#DocTaxonomy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse_taxonomy",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#resolve_flow",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#WorktreePlan",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#plan_worktree",
    "sym:scripts/sdd/id_ledger.py#main",
    "sym:scripts/sdd/reserve_ids.py#main",
    "sym:scripts/sdd/check_id_collisions.py#main",
    "sym:scripts/sdd/ensure_worktree.py#main",
    "sym:scripts/sdd/brief_meta.py#brief_worktree_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#main"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# scripts/sdd/sdd_meta.py — existing re-export shim (precedent for "implementation lives in the wheel").
# Alias shim pattern (fixed by the FEAT-633 task brief):
"""Compatibility shim — moved to ``parrot.sdd.scripts.<name>`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import <name> as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### Key Constraints
- **`git mv` first, then edit.** This keeps `git log --follow` history. Never retype or
  copy a moved file.
- The moved file differs from the original **only** in the lines the blueprint lists.
  `git diff -M --stat` must show a rename with a near-100% similarity index.
- The shim replaces `sys.modules["scripts.sdd.<name>"]` with the package module. Then
  `from scripts.sdd.<name> import _private`, `monkeypatch.setattr(mod, …)` and
  `patch("scripts.sdd.<name>.X")` all hit the real module. When run as `__main__`, the shim
  calls `_impl.main()` before the alias line, which is harmless.
- **Worktree gotcha.** The shared `.venv` is editable-installed against the MAIN
  checkout, which has no `parrot.sdd` until this feature merges. Inside the FEAT-633
  worktree, `python -m scripts.sdd.reserve_ids …` therefore only works with
  `PYTHONPATH=packages/ai-parrot/src`. Primary-checkout invocations
  (`python -m scripts.sdd.ensure_worktree …` from the main repo, used by every other
  session) keep running the old, unmoved code until merge, so they are unaffected.
- Run `ruff check` on every moved file. The global `ruff.toml` rules apply equally to
  `scripts/` and `packages/`, so no new lint findings are expected.

### References in Codebase
- `scripts/sdd/sdd_meta.py` — precedent shim.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` — re-export source.

---

## Implementation Blueprint

### Steps (in order)
1. `mkdir -p packages/ai-parrot/src/parrot/sdd/scripts`, then write `__init__.py` and
   `sdd_meta.py`. *Why*: the moved modules import `parrot.sdd.scripts.sdd_meta`.
2. `git mv` the five files:
   `git mv scripts/sdd/{id_ledger,reserve_ids,check_id_collisions,ensure_worktree,brief_meta}.py packages/ai-parrot/src/parrot/sdd/scripts/`
   (one `git mv` per file). *Why*: this preserves history.
3. Apply the four import rewrites (reserve_ids `:42`, ensure_worktree `:20` and `:21`,
   brief_meta `:19`). *Why*: the package must never import the repo-local `scripts` package,
   which is absent from the wheel.
4. Commit the rename on its own (moved files + `__init__.py` + `sdd_meta.py`) before
   writing the shims. *Why*: git rename detection stays at 100% and the shims show as new
   content.
5. Write the five shims at the original paths. *Why*: existing `python -m scripts.sdd.*`
   invocations and `tests/sdd_scripts/` must keep working.
6. *(rev 0.3 C16 — only after the Readiness review open decisions are resolved)* `git mv`
   `worktree_environment.py` into `parrot/sdd/scripts/`, commit the rename on its own, then
   write the re-export shim at the old path.
7. Write the test file and run the Validation Commands. *Why*: they prove the alias and
   the byte-identical help output.

### `packages/ai-parrot/src/parrot/sdd/scripts/__init__.py` (CREATE)
```python
"""SDD helper scripts, invocable as ``python -m parrot.sdd.scripts.<name>`` (FEAT-633).

The repo-local ``scripts/sdd/<name>.py`` files are compatibility shims aliasing these modules.
Intentionally import-free.
"""
```

### `packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py` (CREATE)
```python
"""Re-export of :mod:`parrot.knowledge.wiki.ledger.sdd_meta` for in-package SDD helpers (FEAT-633).

Same names as the repo-local ``scripts/sdd/sdd_meta.py`` shim, so moved helpers import
``from parrot.sdd.scripts.sdd_meta import …`` without touching the repo-local ``scripts`` package.
"""

from parrot.knowledge.wiki.ledger.sdd_meta import (  # noqa: F401
    KNOWN_BRANCHES,
    KNOWN_PROJECTS,
    PROJECT_ALIASES,
    WORK_KIND_FLOW,
    WORKTREE_ROOT,
    DocTaxonomy,
    FlowMeta,
    WorktreePlan,
    emit,
    normalize_project,
    normalize_tag,
    parse,
    parse_taxonomy,
    plan_worktree,
    resolve_flow,
)
```

### `packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py` (CREATE)
```python
# git mv scripts/sdd/id_ledger.py packages/ai-parrot/src/parrot/sdd/scripts/id_ledger.py
# No line changes: id_ledger has no scripts.sdd import, no __file__, no subprocess (verified).
```

### `packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py` (CREATE)
```python
# git mv scripts/sdd/reserve_ids.py packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py, then:
# occurrences: 1 (verified: grep -c 'from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger' scripts/sdd/reserve_ids.py)
# REPLACE — `from scripts.sdd.id_ledger import LEDGER_PATH, IdLedger, save_ledger` (verified: scripts/sdd/reserve_ids.py:42)
from parrot.sdd.scripts.id_ledger import LEDGER_PATH, IdLedger, save_ledger
```

### `packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py` (CREATE)
```python
# git mv scripts/sdd/check_id_collisions.py packages/ai-parrot/src/parrot/sdd/scripts/check_id_collisions.py
# No line changes (no scripts.sdd import, no __file__, no subprocess — verified).
```

### `packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py` (CREATE)
```python
# git mv scripts/sdd/ensure_worktree.py packages/ai-parrot/src/parrot/sdd/scripts/ensure_worktree.py, then TWO rewrites:
# occurrences: 1 (verified 2026-10-19: grep -c 'from scripts.sdd.brief_meta import brief_worktree_plan' scripts/sdd/ensure_worktree.py)
# REPLACE — `from scripts.sdd.brief_meta import brief_worktree_plan` (verified: scripts/sdd/ensure_worktree.py:20 — rev 0.4 C17)
from parrot.sdd.scripts.brief_meta import brief_worktree_plan
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow' scripts/sdd/ensure_worktree.py)
# REPLACE — `from scripts.sdd.sdd_meta import WorktreePlan, plan_worktree, resolve_flow` (verified: scripts/sdd/ensure_worktree.py:21)
from parrot.sdd.scripts.sdd_meta import WorktreePlan, plan_worktree, resolve_flow
```

### `packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py` (CREATE — rev 0.4 C17)
```python
# git mv scripts/sdd/brief_meta.py packages/ai-parrot/src/parrot/sdd/scripts/brief_meta.py, then:
# occurrences: 1 (verified 2026-10-19: grep -c 'from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan' scripts/sdd/brief_meta.py)
# REPLACE — `from scripts.sdd.sdd_meta import WORKTREE_ROOT, WorktreePlan` (verified: scripts/sdd/brief_meta.py:19)
from parrot.sdd.scripts.sdd_meta import WORKTREE_ROOT, WorktreePlan
# No other line changes. No main() here — TASK-4299 adds the argparse CLI.
```

### `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` (CREATE — rev 0.3 C16, gated)
```python
# git mv packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
# Line changes: NONE decided yet. `_load_guard_bash` (:294-307) needs a kernel lookup that works from
# parrot/sdd/scripts/ — blocked on the Readiness review open decision "C16 kernel lookup".
```

### `scripts/sdd/id_ledger.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``IdLedger`` model + bootstrap for the git-native TASK/FEAT ID allocator.' scripts/sdd/id_ledger.py)
# REPLACE — whole file (the original moved away via git mv; recreate the path with exactly this content);
#           first line was `"""``IdLedger`` model + bootstrap for the git-native TASK/FEAT ID allocator.` (verified: scripts/sdd/id_ledger.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.id_ledger`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import id_ledger as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/reserve_ids.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``reserve_ids.py`` — the git-native compare-and-swap TASK/FEAT ID allocator.' scripts/sdd/reserve_ids.py)
# REPLACE — whole file; first line was `"""``reserve_ids.py`` — the git-native compare-and-swap TASK/FEAT ID allocator.`
#           (verified: scripts/sdd/reserve_ids.py:1). original main: `def main(argv: list[str] | None = None) -> int:` (:616)
"""Compatibility shim — moved to ``parrot.sdd.scripts.reserve_ids`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import reserve_ids as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/check_id_collisions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``check_id_collisions.py`` — defense-in-depth SDD ID collision scanner.' scripts/sdd/check_id_collisions.py)
# REPLACE — whole file; first line was `"""``check_id_collisions.py`` — defense-in-depth SDD ID collision scanner.`
#           (verified: scripts/sdd/check_id_collisions.py:1). original main: `def main(argv: list[str] | None = None) -> int:` (:254)
"""Compatibility shim — moved to ``parrot.sdd.scripts.check_id_collisions`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import check_id_collisions as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/ensure_worktree.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""Idempotent feature/hotfix worktree provisioning for SDD commands (FEAT-552).' scripts/sdd/ensure_worktree.py)
# REPLACE — whole file; first line was `"""Idempotent feature/hotfix worktree provisioning for SDD commands (FEAT-552).`
#           (verified: scripts/sdd/ensure_worktree.py:1). original main: `def main(argv: Sequence[str] | None = None) -> int:` (:225)
"""Compatibility shim — moved to ``parrot.sdd.scripts.ensure_worktree`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import ensure_worktree as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/brief_meta.py` (MODIFY — rev 0.4 C17)
```python
# occurrences: 1 (verified 2026-10-19: grep -c '"""Brief frontmatter model and worktree/index planning for ``/sdd-brief`` (FEAT-698).' scripts/sdd/brief_meta.py)
# REPLACE — whole file; first line was `"""Brief frontmatter model and worktree/index planning for ``/sdd-brief`` (FEAT-698).`
#           (verified: scripts/sdd/brief_meta.py:1). Library module: no main() until TASK-4299, so running this shim
#           as __main__ raises AttributeError until then (nothing runs it today).
"""Compatibility shim — moved to ``parrot.sdd.scripts.brief_meta`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import brief_meta as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py` (MODIFY — rev 0.3 C16, gated)
```python
# REPLACE — whole file (original moved by git mv) with the re-export shim. Its exact form is blocked on the
# Readiness review open decision "C16 shim form and by-path callers". Fixed requirements from the spec text:
#   - the three in-core importers keep working unchanged: dispatchers/claude.py:66 (module object),
#     dispatchers/llm.py:58 (command_policy_error, protected_argv, validate_write_path),
#     sdd_coder/background.py:57 (protected_argv);
#   - packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py passes unmodified.
```

### `packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py` (CREATE)
See **Test Specification**. That block is the starting file.

### FILL IN checklist
- [ ] None in production code: every change is mechanical (`git mv` + four import lines +
  five fixed shims). The C16 `worktree_environment` rows wait for the open decisions.
- [ ] `test_scripts_ledger_worktree.py`: confirm `--help` parity holds on the
  interpreter in use. Python 3.14 changed argparse's default `prog` for `-m`; the venv is
  3.12.3. If parity breaks on a newer interpreter, report it and do NOT add `prog=`
  (bounded by the "never change their CLI" warning).

---

## Acceptance Criteria

- [ ] AC-1: `python -m parrot.sdd.scripts.<name> --help` exits 0 for `id_ledger`,
  `reserve_ids`, `check_id_collisions`, `ensure_worktree`, run from a non-repo cwd.
- [ ] AC-2: `import scripts.sdd.<name>` yields the very same module object as
  `parrot.sdd.scripts.<name>` for the five moved modules (the four CLIs + `brief_meta`).
- [ ] AC-3: `python -m scripts.sdd.reserve_ids --help` and
  `python -m scripts.sdd.ensure_worktree --help` stdout are byte-identical to the
  `parrot.sdd.scripts` invocations. Exit codes for a usage error (missing required flag)
  are identical (2).
- [ ] AC-4: `parrot.sdd.scripts.sdd_meta.<name> is parrot.knowledge.wiki.ledger.sdd_meta.<name>`
  for all 15 names. `scripts/sdd/sdd_meta.py` is unchanged (`git diff` empty).
- [ ] AC-5: The existing suites pass unmodified (see Validation Commands).
- [ ] AC-6: `git log --follow packages/ai-parrot/src/parrot/sdd/scripts/reserve_ids.py`
  shows the pre-move history.
- [ ] AC-7: `ruff check packages/ai-parrot/src/parrot/sdd/scripts scripts/sdd packages/ai-parrot/tests/sdd`
  is clean.
- [ ] AC-8 (rev 0.3 C16, gated): `parrot.sdd.scripts.worktree_environment` imports without
  importing `parrot.flows.dev_loop`; `command_policy_error`, `protected_argv`,
  `validate_write_path` imported from `parrot.flows.dev_loop.worktree_environment` are the
  objects of `parrot.sdd.scripts.worktree_environment`; `test_worktree_environment.py` passes
  unmodified.
- [ ] Spec §5: "`scripts/sdd/` wrappers keep the monorepo's existing invocations working"
  (for these five).

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py -q`
- `pytest tests/sdd_scripts/test_id_ledger.py -q`
- `pytest tests/sdd_scripts/test_reserve_ids.py -q`
- `pytest tests/sdd_scripts/test_check_id_collisions.py -q`
- `pytest tests/sdd_scripts/test_ensure_worktree.py -q`
- `pytest tests/sdd_scripts/test_sdd_meta.py -q`
- `pytest tests/sdd_scripts/test_worktree_plan.py -q`
- `pytest tests/sdd_scripts/test_brief_meta.py -q` (rev 0.4 C17)
- `pytest tests/sdd_scripts/test_brief_scaffold_integration.py -q` (rev 0.4 C17)
- `pytest tests/sdd_scripts/test_brief_template_contract.py -q` (rev 0.4 C17)
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py -q` (rev 0.3 C16, once ungated)

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
"""FEAT-633 move A: ledger/worktree helpers live in parrot.sdd.scripts; scripts/sdd shims alias them."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree")
MOVED_LIBS = ("brief_meta",)  # rev 0.4 C17: library module, no main() until TASK-4299 adds the CLI
SDD_META_NAMES = (
    "KNOWN_BRANCHES", "KNOWN_PROJECTS", "PROJECT_ALIASES", "WORK_KIND_FLOW", "WORKTREE_ROOT", "DocTaxonomy",
    "FlowMeta", "WorktreePlan", "emit", "normalize_project", "normalize_tag", "parse", "parse_taxonomy",
    "plan_worktree", "resolve_flow",
)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


def _run(module: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, env=_env(), capture_output=True, text=True)


@pytest.mark.parametrize("name", (*MOVED, *MOVED_LIBS, "sdd_meta"))
def test_importable_from_package(name: str) -> None:
    assert importlib.import_module(f"parrot.sdd.scripts.{name}") is not None


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    assert _run(f"parrot.sdd.scripts.{name}", "--help", cwd=tmp_path).returncode == 0


@pytest.mark.parametrize("name", (*MOVED, *MOVED_LIBS))
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


@pytest.mark.parametrize("name", ("reserve_ids", "ensure_worktree"))
def test_live_cli_help_and_usage_error_unchanged(name: str) -> None:
    shim, pkg = _run(f"scripts.sdd.{name}", "--help", cwd=REPO_ROOT), _run(f"parrot.sdd.scripts.{name}", "--help", cwd=REPO_ROOT)
    assert (shim.returncode, shim.stdout) == (pkg.returncode, pkg.stdout)
    assert _run(f"scripts.sdd.{name}", cwd=REPO_ROOT).returncode == _run(f"parrot.sdd.scripts.{name}", cwd=REPO_ROOT).returncode == 2


def test_sdd_meta_reexport_identity() -> None:
    pkg = importlib.import_module("parrot.sdd.scripts.sdd_meta")
    src = importlib.import_module("parrot.knowledge.wiki.ledger.sdd_meta")
    for name in SDD_META_NAMES:
        assert getattr(pkg, name) is getattr(src, name), name
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree**. Never work on `base_branch`.
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context.
3. **Check dependencies**: every `Depends-on` task must be `"done"` in the per-spec index
   `sdd/tasks/index/parrot-installer.json`.
4. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
5. **Update status** in `sdd/tasks/index/parrot-installer.json` to `"in-progress"` (set
   `started_at`) and commit only that index file.
6. **Implement**. Start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes.
7. **Verify** that all acceptance criteria are met by running the Validation Commands.
8. **Commit the code**. Stage only the files this task lists (never `git add .` / `-A`).
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4085 parrot-installer verified`.
   It moves this file to `sdd/tasks/completed/` and marks it `"done"` in the index. Never
   move or copy the file by hand.
10. **Fill in the Completion Note** below, then commit the staged SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
