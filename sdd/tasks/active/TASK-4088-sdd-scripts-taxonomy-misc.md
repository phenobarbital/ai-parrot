# TASK-4088: SDD helpers move C: taxonomy, select_tests, insight, install_hooks

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4085
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 moves the doc-referenced SDD helpers into `parrot/sdd/scripts/`. The
`scripts/sdd/*.py` files become thin wrappers. The spec §5 bullet is: "every helper
referenced by installed markdown resolves as `python -m parrot.sdd.scripts.<name>`;
`scripts/sdd/` wrappers keep the monorepo's existing invocations working".

This is move **C**, the remaining six Python helpers: `doc_taxonomy`,
`backfill_taxonomy`, `migrate_index`, `select_tests`, `insight` and `install_hooks`.
Prerequisites from TASK-4085 are `parrot/sdd/scripts/__init__.py` and the
`parrot.sdd.scripts.sdd_meta` re-export. The mechanics are the same as TASK-4085/4086:
`git mv`, rewrite only the lines listed in the blueprint, and turn the old path into the
alias shim.

Repo-layout assumptions found by grep (2026-10-05). The table states what each moved
module assumes and how it locates the repository:

| Module | Assumption | Locates repo via | Action here |
|---|---|---|---|
| `doc_taxonomy` | `--root` default `Path(".")` (:84); globs `sdd/specs/*.spec.md` etc. (:28-30) | cwd | import rewrite only |
| `backfill_taxonomy` | `--root` default `Path(".")` (:149); `_SDD_TOOLING_RE = r"scripts/sdd/\|\.claude/commands/\|sdd/templates/"` (:41) classifies docs as SDD tooling | cwd | import rewrite only (regex: see NOT in scope) |
| `migrate_index` | `--source sdd/tasks/.index.json`, `--dest sdd/tasks/index` (:158,:164) | cwd | none |
| `select_tests` | `_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"` (:17), which **breaks in site-packages**. `--worktree` default `Path.cwd()` (:35). The kernel calls `git` with `cwd=worktree`. The kernel's planning encodes the monorepo `packages/<dist>/{src,tests}` layout (`test_scope/mirror.py:62-64,132`; `policy.py:17+`) | cwd (`--worktree`) + git inside the kernel | make `_KERNEL_PARENT` package-relative |
| `insight` | stdlib-only. `--sdd-dir` default `$SDD_DIR` or `"sdd"` (:1923). Report goes to `./ai_fluency_report.html`. Transcripts come from `~/.claude/projects` (:59). It is invoked as **`python3 scripts/sdd/insight.py`** (a path, not `-m`) in `.claude/commands/sdd-insight.md:51,85` | cwd + `~` | no change to the module; the shim gets a bare-interpreter fallback (see blueprint) |
| `install_hooks` | `--repo-root` default `Path.cwd()` (:118). Hooks dir from `git rev-parse --git-path hooks` (:26-30, honours `core.hooksPath`), with a fallback to `<root>/.git/hooks` (:126). The rendered hook bakes `sys.executable` (:140) and runs `python -m scripts.sdd.prune_intake` from the repo root (:40), and **`prune_intake` is not in the spec's move list** | cwd + git | none (see NOT in scope) |

None of the modules derives the **repository root** from `__file__`. Only `select_tests`
uses `__file__`, and it does so to find a sibling package. That becomes package-relative.

---

## Scope

- `git mv` the six modules into `packages/ai-parrot/src/parrot/sdd/scripts/`.
- Rewrite the `sdd_meta` imports in `doc_taxonomy` and `backfill_taxonomy` to
  `parrot.sdd.scripts.sdd_meta`.
- Make `select_tests._KERNEL_PARENT` package-relative
  (`<parrot pkg>/flows/dev_loop`).
- Recreate the six `scripts/sdd/<name>.py` as alias shims. The `insight` shim
  additionally falls back to its own checkout's `packages/ai-parrot/src`, so
  `python3 scripts/sdd/insight.py` keeps working with a bare interpreter.
- Add `packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py`.

**Decided by the spec author (2026-10-05) — part of this task's scope, not a follow-up:**
- **`prune_intake` moves too** (19th module; no `__file__` usage — verified; pydantic is a
  core dep). Same move + shim pattern as the rest of this task's modules.
- **`install_hooks.render_block` retargets the rendered hook** to
  `"{python}" -m parrot.sdd.scripts.prune_intake --daily --apply` (install_hooks.py:40) and
  updates the marker comment at :38 accordingly — the rendered block is the one piece of
  this module that RUNS in installed repos, where `scripts.sdd` does not exist. Re-running
  install replaces the old marker block, so monorepo hooks pick the new form up on the next
  `install_hooks` run. The baked absolute `sys.executable` (:140) stays as-is (hook runs
  outside any venv activation; still correct in foreign repos once ai-parrot is installed).
- **`tests/sdd_scripts/test_install_hooks.py`** must be updated where it asserts the
  rendered block's contents (it imports render_block at :12 — grep it for
  `prune_intake`/block-content asserts and fix only those).

**NOT in scope** (record each item in the Completion Note as an open follow-up):
- **`select_tests` in foreign repos.** The kernel's `packages/<dist>` layout logic is
  monorepo-specific. Generalising it is out of scope.
- **`backfill_taxonomy._SDD_TOOLING_RE`** (:41) does not match the new
  `parrot.sdd.scripts` form that TASK-4089 introduces into docs. Widening it changes the
  classification. Leave it unchanged and flag it for TASK-4089.
- Docstring/`prog=` strings naming `scripts.sdd.*` (`doc_taxonomy.py:83`,
  `backfill_taxonomy.py:148`, usage lines). These are user-visible and owned by
  TASK-4089.
- Rewriting `.claude/commands/sdd-insight.md` (TASK-4089).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/doc_taxonomy.py` | CREATE | `git mv` + `sdd_meta` import rewrite |
| `packages/ai-parrot/src/parrot/sdd/scripts/backfill_taxonomy.py` | CREATE | `git mv` + `sdd_meta` import rewrite |
| `packages/ai-parrot/src/parrot/sdd/scripts/migrate_index.py` | CREATE | `git mv` (no line changes) |
| `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` | CREATE | `git mv` + package-relative `_KERNEL_PARENT` |
| `packages/ai-parrot/src/parrot/sdd/scripts/insight.py` | CREATE | `git mv` (no line changes; 2079 lines) |
| `packages/ai-parrot/src/parrot/sdd/scripts/install_hooks.py` | CREATE | `git mv` + hook retarget to `parrot.sdd.scripts.prune_intake` (:38-40) |
| `packages/ai-parrot/src/parrot/sdd/scripts/prune_intake.py` | CREATE | `git mv` (no line changes; no `__file__`, pydantic is core) |
| `scripts/sdd/doc_taxonomy.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/backfill_taxonomy.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/migrate_index.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/select_tests.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/insight.py` | MODIFY | Becomes alias shim with bare-interpreter fallback |
| `scripts/sdd/install_hooks.py` | MODIFY | Becomes alias shim |
| `scripts/sdd/prune_intake.py` | MODIFY | Becomes alias shim |
| `tests/sdd_scripts/test_install_hooks.py` | MODIFY | Update rendered-block content asserts to the new module path |
| `packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py` | CREATE | Importability, `-m --help`, shim identity, kernel path, insight path-run |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.sdd.scripts.sdd_meta import normalize_project, normalize_tag, parse_taxonomy   # TASK-4085 re-export of
from parrot.sdd.scripts.sdd_meta import KNOWN_PROJECTS, parse_taxonomy                     # parrot/knowledge/wiki/ledger/sdd_meta.py
#   (normalize_project :188, normalize_tag :173, parse_taxonomy :247, KNOWN_PROJECTS :45)
# Third-party imports across the six modules: pydantic only (doc_taxonomy :19, backfill_taxonomy :17) — core dep.
# select_tests, insight, install_hooks, migrate_index: stdlib only (verified import lists).
```

### Existing Signatures to Use
```python
# scripts/sdd/doc_taxonomy.py (123 lines)
from scripts.sdd.sdd_meta import normalize_project, normalize_tag, parse_taxonomy   # :21 ← REWRITE
def main(argv: list[str] | None = None) -> int:                 # :81 — prog="python -m scripts.sdd.doc_taxonomy" :83 (unchanged)
if __name__ == "__main__": sys.exit(main())                     # :122-123

# scripts/sdd/backfill_taxonomy.py (184 lines)
from scripts.sdd.sdd_meta import KNOWN_PROJECTS, parse_taxonomy                     # :19 ← REWRITE
_SDD_TOOLING_RE = re.compile(r"scripts/sdd/|\.claude/commands/|sdd/templates/")     # :41 (unchanged)
def main(argv: list[str] | None = None) -> int:                 # :146 — prog="python -m scripts.sdd.backfill_taxonomy" :148
if __name__ == "__main__": sys.exit(main())                     # :183-184

# scripts/sdd/migrate_index.py (177 lines)
def main(argv: list[str] | None = None) -> int:                 # :150 (defaults :158 .index.json, :164 index/)
if __name__ == "__main__": raise SystemExit(main())             # :176-177

# scripts/sdd/select_tests.py (130 lines)
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"   # :17 ← REWRITE
def _load_kernel() -> ModuleType:                               # :20 — sys.path.insert(0, _KERNEL_PARENT); import test_scope
parser.add_argument("--worktree", type=Path, default=Path.cwd())   # :35
def main(argv: list[str] | None = None) -> int:                 # :52 — subprocess.run(argv, cwd=worktree) :108 (pytest, not scripts/sdd)
if __name__ == "__main__": raise SystemExit(main())             # :129-130

# scripts/sdd/insight.py (2079 lines, git mode 100644, shebang :1 "#!/usr/bin/env python3")
DEFAULT_DIRS = ["~/.claude/projects", "~/.claude/sessions"]     # :59
def main(argv=None):                                            # :1894 — returns 0/1 (:1956,1961,1990,2050,2075)
    ap.add_argument("--sdd-dir", default=os.environ.get("SDD_DIR", "sdd"), ...)   # :1923
if __name__ == "__main__": raise SystemExit(main())             # :2078-2079
# Invoked by path: .claude/commands/sdd-insight.md:51,85 `python3 scripts/sdd/insight.py \`

# scripts/sdd/install_hooks.py (149 lines)
MARKER_BEGIN, MARKER_END, HOOK_EVENTS, SHEBANG                  # :18-21
def hooks_dir(repo_root: Path) -> Path:                         # :24 — git rev-parse --git-path hooks (cwd=repo_root) :26-28
def render_block(python: str, repo_root: Path) -> str:          # :33 — hook runs `"{python}" -m scripts.sdd.prune_intake --daily --apply` :40
def install(hooks: Path, block: str, events=HOOK_EVENTS) -> list[Path]:   # :64
def uninstall(hooks: Path, events=HOOK_EVENTS) -> list[Path]:   # :92
def main(argv: list[str] | None = None) -> int:                 # :114 — --repo-root default Path.cwd() :118; block uses sys.executable :140
if __name__ == "__main__": raise SystemExit(main())             # :148-149

# Existing tests that must keep passing through the shim (all verified to exist):
#   tests/sdd_scripts/test_doc_taxonomy.py      (from scripts.sdd.doc_taxonomy import TaxonomyRow, collect, filter_rows, main :10)
#   tests/sdd_scripts/test_backfill_taxonomy.py (from scripts.sdd.backfill_taxonomy import infer_projects, main, plan_edit :8)
#   tests/sdd_scripts/test_migrate_index.py     (from scripts.sdd.migrate_index import migrate :10)
#   tests/sdd_scripts/test_select_tests.py      (from scripts.sdd.select_tests import main / _load_kernel :12,76;
#                                                monkeypatch.setattr("scripts.sdd.select_tests.subprocess", …) :154-155)
#   tests/sdd_scripts/test_insight_sdd.py       (from scripts.sdd import insight :16)
#   tests/sdd_scripts/test_install_hooks.py     (from scripts.sdd.install_hooks import HOOK_EVENTS, MARKER_BEGIN, install, main, … :12)
```

### Does NOT Exist
- `parrot.sdd.scripts.prune_intake` does not exist YET — THIS task creates it (19th
  module, spec-author amendment 2026-10-05, superseding the spec's original 18-module list).
- ~~`parrot.flows.dev_loop.test_scope` imported by dotted name from select_tests~~ — it
  is loaded by path as the top-level `test_scope`, which avoids the heavy
  `parrot.flows.dev_loop` `__init__` (about 2.4 s, navconfig). Keep that.
- ~~A `main(argv)` return annotation on insight~~ — `def main(argv=None):` is untyped.
  Do not retype a moved file.
- ~~Any `__file__`-based repo-root derivation in these six modules~~ — none. Only
  `select_tests:17` uses `__file__`, for a sibling package path.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/doc_taxonomy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/backfill_taxonomy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/migrate_index.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/insight.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/install_hooks.py", "action": "CREATE"},
    {"path": "scripts/sdd/doc_taxonomy.py", "action": "MODIFY"},
    {"path": "scripts/sdd/backfill_taxonomy.py", "action": "MODIFY"},
    {"path": "scripts/sdd/migrate_index.py", "action": "MODIFY"},
    {"path": "scripts/sdd/select_tests.py", "action": "MODIFY"},
    {"path": "scripts/sdd/insight.py", "action": "MODIFY"},
    {"path": "scripts/sdd/install_hooks.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/prune_intake.py", "action": "CREATE"},
    {"path": "scripts/sdd/prune_intake.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_install_hooks.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_project",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#normalize_tag",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py#parse_taxonomy",
    "sym:scripts/sdd/doc_taxonomy.py#main",
    "sym:scripts/sdd/backfill_taxonomy.py#main",
    "sym:scripts/sdd/migrate_index.py#main",
    "sym:scripts/sdd/select_tests.py#main",
    "sym:scripts/sdd/select_tests.py#_load_kernel",
    "sym:scripts/sdd/insight.py#main",
    "sym:scripts/sdd/install_hooks.py#main",
    "sym:scripts/sdd/install_hooks.py#hooks_dir",
    "sym:scripts/sdd/install_hooks.py#render_block"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# Alias shim fixed by the FEAT-633 brief (TASK-4085/4086 use it verbatim):
"""Compatibility shim — moved to ``parrot.sdd.scripts.<name>`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import <name> as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### Key Constraints
- **`git mv` first, then edit.** Most importantly, do not retype `insight.py` (2079
  lines). The moved files differ from the originals only in the lines the blueprint
  lists.
- `raise SystemExit(_impl.main())` is equivalent to the originals' `sys.exit(main())`
  (doc_taxonomy, backfill_taxonomy).
- **`insight` shim deviation (deliberate).** `insight.py` is invoked by **path**
  (`python3 scripts/sdd/insight.py`) and is advertised as "Pure Python standard library
  — no pip". With a bare `python3` (no venv), `import parrot` fails. Its shim therefore
  retries after prepending this checkout's `packages/ai-parrot/src`. That works because
  `parrot/__init__.py` imports only stdlib plus `parrot.version`, and
  `parrot.sdd`/`parrot.sdd.scripts`/`insight` are import-free or stdlib-only. Using
  `__file__` here is legitimate, because the shim is repo-local and never installed.
- **Worktree gotcha (same as TASK-4085).** Inside the FEAT-633 worktree, the other
  shims only resolve with `PYTHONPATH=packages/ai-parrot/src`.
- The `ruff.toml` rules apply equally to `scripts/` and `packages/`.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/` — the kernel loaded by path.
- TASK-4086 `check_task_graph._KERNEL_DIR` — the same package-relative rewrite.

---

## Implementation Blueprint

### Steps (in order)
1. `git mv` the seven files (the six below plus `prune_intake.py`) into
   `packages/ai-parrot/src/parrot/sdd/scripts/`, one command per file. *Why*: this
   preserves history.
2. Apply the in-file edits below (two imports, `_KERNEL_PARENT`, and the
   `install_hooks.render_block` retarget). *Why*: the package must not depend on the
   repo-local `scripts` package or on the monorepo path layout — and the rendered hook
   is the one output that RUNS in installed repos.
3. Commit the renames on their own, then write the seven shims and update
   `tests/sdd_scripts/test_install_hooks.py`'s block-content asserts. *Why*: rename
   detection stays intact.
4. Write the test file and run every Validation Command. *Why*: the shim must preserve
   `monkeypatch.setattr("scripts.sdd.select_tests.subprocess", …)` and
   `from scripts.sdd import insight`.

### `packages/ai-parrot/src/parrot/sdd/scripts/doc_taxonomy.py` (CREATE)
```python
# git mv scripts/sdd/doc_taxonomy.py packages/ai-parrot/src/parrot/sdd/scripts/doc_taxonomy.py, then:
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import normalize_project, normalize_tag, parse_taxonomy' scripts/sdd/doc_taxonomy.py)
# REPLACE — `from scripts.sdd.sdd_meta import normalize_project, normalize_tag, parse_taxonomy` (verified: scripts/sdd/doc_taxonomy.py:21)
from parrot.sdd.scripts.sdd_meta import normalize_project, normalize_tag, parse_taxonomy
```

### `packages/ai-parrot/src/parrot/sdd/scripts/backfill_taxonomy.py` (CREATE)
```python
# git mv scripts/sdd/backfill_taxonomy.py packages/ai-parrot/src/parrot/sdd/scripts/backfill_taxonomy.py, then:
# occurrences: 1 (verified: grep -c 'from scripts.sdd.sdd_meta import KNOWN_PROJECTS, parse_taxonomy' scripts/sdd/backfill_taxonomy.py)
# REPLACE — `from scripts.sdd.sdd_meta import KNOWN_PROJECTS, parse_taxonomy` (verified: scripts/sdd/backfill_taxonomy.py:19)
from parrot.sdd.scripts.sdd_meta import KNOWN_PROJECTS, parse_taxonomy
```

### `packages/ai-parrot/src/parrot/sdd/scripts/migrate_index.py` (CREATE)
```python
# git mv scripts/sdd/migrate_index.py packages/ai-parrot/src/parrot/sdd/scripts/migrate_index.py
# No line changes (stdlib-only, cwd-relative defaults, no __file__/subprocess).
```

### `packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py` (CREATE)
```python
# git mv scripts/sdd/select_tests.py packages/ai-parrot/src/parrot/sdd/scripts/select_tests.py, then:
# occurrences: 1 (verified: grep -c '_KERNEL_PARENT = Path(__file__).resolve().parents\[2\] / "packages/ai-parrot/src/parrot/flows/dev_loop"' scripts/sdd/select_tests.py)
# REPLACE — `_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"` (verified: scripts/sdd/select_tests.py:17)
# parrot/sdd/scripts/select_tests.py -> parents[2] is the `parrot` package dir (package-relative, wheel-safe).
_KERNEL_PARENT = Path(__file__).resolve().parents[2] / "flows" / "dev_loop"
```

### `packages/ai-parrot/src/parrot/sdd/scripts/insight.py` (CREATE)
```python
# git mv scripts/sdd/insight.py packages/ai-parrot/src/parrot/sdd/scripts/insight.py
# No line changes (stdlib-only; shebang/docstring "python3 scripts/sdd/insight.py" left for TASK-4089).
```

### `packages/ai-parrot/src/parrot/sdd/scripts/install_hooks.py` (CREATE)
```python
# git mv scripts/sdd/install_hooks.py packages/ai-parrot/src/parrot/sdd/scripts/install_hooks.py
# Then ONE functional edit in render_block:
# occurrences: 1 (verified: grep -cF 'scripts.sdd.prune_intake --daily --apply' scripts/sdd/install_hooks.py)
# REPLACE — in the f-string at install_hooks.py:40
#   old: "{python}" -m scripts.sdd.prune_intake --daily --apply
#   new: "{python}" -m parrot.sdd.scripts.prune_intake --daily --apply
# Also update the marker comment at :38 ("Installed by `python -m scripts.sdd.install_hooks`"
# → `python -m parrot.sdd.scripts.install_hooks`). Re-running install replaces old marker
# blocks, so existing monorepo hooks converge on the next run.
```

### `packages/ai-parrot/src/parrot/sdd/scripts/prune_intake.py` (CREATE)
```python
# git mv scripts/sdd/prune_intake.py packages/ai-parrot/src/parrot/sdd/scripts/prune_intake.py
# No line changes: no __file__ usage (verified), imports are stdlib + pydantic (core dep),
# main(argv: list[str] | None = None) -> int at prune_intake.py:142 (verified).
```

### `scripts/sdd/prune_intake.py` (MODIFY)
```python
# Becomes the standard alias shim (same pattern as doc_taxonomy's block above):
# import parrot.sdd.scripts.prune_intake as _impl; __main__ → SystemExit(_impl.main());
# sys.modules[__name__] = _impl
```

### `tests/sdd_scripts/test_install_hooks.py` (MODIFY)
```python
# grep this file for 'prune_intake' / rendered-block content asserts (it imports
# render_block at :12) and update ONLY those expected strings to
# 'parrot.sdd.scripts.prune_intake' / the new marker comment. No behavioral test changes.
```

### `scripts/sdd/doc_taxonomy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""List SDD docs by ``projects``/``tags`` frontmatter (FEAT-576).' scripts/sdd/doc_taxonomy.py)
# REPLACE — whole file; first line was `"""List SDD docs by ``projects``/``tags`` frontmatter (FEAT-576).` (verified: scripts/sdd/doc_taxonomy.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.doc_taxonomy`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import doc_taxonomy as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/backfill_taxonomy.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""Infer ``projects`` frontmatter for existing SDD docs (FEAT-576). Dry-run by default.' scripts/sdd/backfill_taxonomy.py)
# REPLACE — whole file; first line was `"""Infer ``projects`` frontmatter for existing SDD docs (FEAT-576). Dry-run by default.` (verified: scripts/sdd/backfill_taxonomy.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.backfill_taxonomy`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import backfill_taxonomy as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/migrate_index.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""One-shot migration: monolithic ``sdd/tasks/.index.json`` → per-spec index files.' scripts/sdd/migrate_index.py)
# REPLACE — whole file; first line was `"""One-shot migration: monolithic ``sdd/tasks/.index.json`` → per-spec index files.` (verified: scripts/sdd/migrate_index.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.migrate_index`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import migrate_index as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/select_tests.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``select_tests.py`` — tier-scoped pytest plans for SDD agents (FEAT-563).' scripts/sdd/select_tests.py)
# REPLACE — whole file; first line was `"""``select_tests.py`` — tier-scoped pytest plans for SDD agents (FEAT-563).` (verified: scripts/sdd/select_tests.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.select_tests`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import select_tests as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/insight.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '#!/usr/bin/env python3' scripts/sdd/insight.py)
# REPLACE — whole file; first line was `#!/usr/bin/env python3` (verified: scripts/sdd/insight.py:1); entry `def main(argv=None):` (:1894)
#!/usr/bin/env python3
"""Compatibility shim — moved to ``parrot.sdd.scripts.insight`` (FEAT-633).

Still runnable as ``python3 scripts/sdd/insight.py`` with a bare interpreter: the module is stdlib-only, so when
``parrot`` is not importable the shim retries with this checkout's ``packages/ai-parrot/src`` on ``sys.path``.
"""
import sys
from pathlib import Path

try:
    from parrot.sdd.scripts import insight as _impl
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "ai-parrot" / "src"))
    from parrot.sdd.scripts import insight as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `scripts/sdd/install_hooks.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"""``install_hooks.py`` — install the daily /sdd-spec intake prune git hook (FEAT-577).' scripts/sdd/install_hooks.py)
# REPLACE — whole file; first line was `"""``install_hooks.py`` — install the daily /sdd-spec intake prune git hook (FEAT-577).` (verified: scripts/sdd/install_hooks.py:1)
"""Compatibility shim — moved to ``parrot.sdd.scripts.install_hooks`` (FEAT-633)."""
import sys

from parrot.sdd.scripts import install_hooks as _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
sys.modules[__name__] = _impl
```

### `packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py` (CREATE)
See **Test Specification**. That block is the starting file.

### FILL IN checklist
- [ ] None in production code: every change is mechanical.
- [ ] Completion Note: list the three open follow-ups from NOT in scope. They are
  `install_hooks` → `prune_intake` (plus the baked `sys.executable`), the monorepo-only
  `select_tests` kernel layout, and `backfill_taxonomy._SDD_TOOLING_RE` versus the new
  `parrot.sdd.scripts` references.

---

## Acceptance Criteria

- [ ] AC-1: `python -m parrot.sdd.scripts.<name> --help` exits 0 from a non-repo cwd for
  all six modules.
- [ ] AC-2: `scripts.sdd.<name> is parrot.sdd.scripts.<name>` for all six.
- [ ] AC-3: `parrot.sdd.scripts.select_tests._KERNEL_PARENT` equals
  `<parrot pkg>/flows/dev_loop` and `_load_kernel()` returns the `test_scope` kernel.
- [ ] AC-4: `python3 -I -S scripts/sdd/insight.py --help` exits 0 when run by path from
  the repo root. `-I -S` means isolated mode with no site-packages, so no venv and no
  editable `.pth`. This proves the bare-interpreter fallback.
- [ ] AC-5: The moved files differ from the originals only in the lines the blueprint
  lists (`git diff -M` shows renames; `insight.py` is a 100% rename).
- [ ] AC-6: The existing suites in Validation Commands pass unmodified.
- [ ] AC-7: `ruff check packages/ai-parrot/src/parrot/sdd/scripts scripts/sdd packages/ai-parrot/tests/sdd`
  is clean.
- [ ] Spec §5: "every helper referenced by installed markdown resolves as
  `python -m parrot.sdd.scripts.<name>`; `scripts/sdd/` wrappers keep the monorepo's
  existing invocations working" (for these six).

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py -q`
- `pytest tests/sdd_scripts/test_doc_taxonomy.py -q`
- `pytest tests/sdd_scripts/test_backfill_taxonomy.py -q`
- `pytest tests/sdd_scripts/test_migrate_index.py -q`
- `pytest tests/sdd_scripts/test_select_tests.py -q`
- `pytest tests/sdd_scripts/test_insight_sdd.py -q`
- `pytest tests/sdd_scripts/test_install_hooks.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_scripts_taxonomy_misc.py
"""FEAT-633 move C: taxonomy/select_tests/insight/install_hooks live in parrot.sdd.scripts; shims alias them."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("doc_taxonomy", "backfill_taxonomy", "migrate_index", "select_tests", "insight", "install_hooks")


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", f"parrot.sdd.scripts.{name}", "--help"],
        cwd=tmp_path, env=_env(), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", MOVED)
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


def test_select_tests_kernel_is_package_relative() -> None:
    import parrot
    from parrot.sdd.scripts import select_tests

    assert select_tests._KERNEL_PARENT == Path(parrot.__file__).resolve().parent / "flows" / "dev_loop"
    assert hasattr(select_tests._load_kernel(), "plan_tests")


def test_insight_runs_by_path_with_bare_interpreter() -> None:
    # -I -S: isolated + no site-packages (no venv, no editable .pth) — a truly bare interpreter; only the shim's
    # own-checkout fallback can find parrot.sdd.scripts.insight (stdlib-only), so this exercises the fallback.
    proc = subprocess.run(
        [sys.executable, "-I", "-S", str(REPO_ROOT / "scripts" / "sdd" / "insight.py"), "--help"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4088 parrot-installer verified`.
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
