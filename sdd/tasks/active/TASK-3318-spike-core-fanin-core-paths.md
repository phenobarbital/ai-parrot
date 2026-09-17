# TASK-3318: Spike S4 — measure source fan-in and write `CORE_PATHS`

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3307, TASK-3317
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview 2b (core detector), G7b, §7 Spikes S4, R15; spec §8 resolved question:
*threshold **50** confirmed; `CORE_PATHS` is set from the spike S4 measurement (no further sign-off required)*.

A changed source module is *core* when its **transitive source fan-in** (source modules that import
it, directly or indirectly) is ≥ `DEFAULT_CORE_FANIN_THRESHOLD` (50) **or** its path is in
`CORE_PATHS`. `CORE_PATHS` is the manual override for modules the AST index **under-counts**
(dynamic imports, `importlib`, string-based registries, the `parrot.tools.<x>` →
`parrot_tools.<x>` meta_path redirect — R15). TASK-3305 ships it seeded with
`clients/base.py` (182 grep importers) and `bots/abstract.py` (146). This task replaces the seed with
the measured list, using the `ImportIndex` built by TASK-3307, and commits the TSV evidence.

---

## Scope

- Build `ImportIndex` over the worktree and compute `source_fanin` for **every** source module.
- Compute a text-based cross-check per module: number of distinct source files whose text
  mentions the dotted module name (`rg -l -F`), plus the `parrot_tools.<x>` alias where applicable.
- Write `artifacts/logs/feat-563-core-fanin.tsv` (header + one row per module, sorted by AST fan-in desc):
  `module`, `path`, `ast_fanin`, `text_mentions`, `distributions`, `core_by_threshold`, `undercounted`, `in_core_paths`.
- `undercounted` := `ast_fanin < 50 and text_mentions >= 50`.
- Write `CORE_PATHS` in `test_scope/policy.py` = every path with `core_by_threshold` **or** `undercounted`,
  sorted, one per line with a trailing `# fan-in N (ast) / M (text)` comment.

**NOT in scope**: changing the threshold (confirmed 50); changing `impact.py` logic (report bugs found in
the Completion Note instead); `XDIST_SAFE_DISTRIBUTIONS` (TASK-3317).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` | MODIFY | replace the seeded `CORE_PATHS` tuple with the measured list |
| `artifacts/logs/feat-563-core-fanin.tsv` | CREATE | per-module fan-in evidence |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Measurement script (inline, not committed) — load the kernel BY PATH as top-level `test_scope`,
# never `import parrot…` (navconfig chdirs on import; dual class identities):
import sys
from pathlib import Path
sys.path.insert(0, str(Path("packages/ai-parrot/src/parrot/flows/dev_loop").resolve()))
from test_scope.impact import ImportIndex, source_fanin, module_name_for   # created by TASK-3307
from test_scope.policy import DEFAULT_CORE_FANIN_THRESHOLD, CORE_PATHS     # created by TASK-3305
```

### Existing Signatures to Use
- Grep baseline measured 2026-09-17 (spec §6): `parrot.clients.base` 182 source importers / 37 direct test importers;
  `parrot.bots.abstract` 146 / 13. The AST numbers should be of the same order; a large gap is a finding to report.
- Source layout: `packages/<dist>/src/<top>/…` (core `parrot`, satellites `parrot/*` via PEP 420, plus top-level
  `parrot_tools`, `parrot_loaders`, `parrot_pipelines`).

### Created by dependency tasks (verify they landed before starting)
```python
# TASK-3307 — packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/impact.py
def module_name_for(path: str) -> str | None: ...
@dataclass
class ImportIndex:
    by_module: dict[str, set[str]]          # module → test files
    src_importers: dict[str, set[str]]      # module → source modules importing it
    module_dist: dict[str, str]             # source module → distribution
    skipped: list[str]
    @classmethod
    def build(cls, worktree: Path) -> "ImportIndex": ...
def source_fanin(index: ImportIndex, module: str) -> tuple[int, frozenset[str]]: ...  # transitive count, distributions

# TASK-3305 (+ TASK-3317 edited XDIST only) — .../test_scope/policy.py
DEFAULT_CORE_FANIN_THRESHOLD: int = 50
CORE_PATHS: tuple[str, ...] = (  # seed; final list written from spike S4 measurement; always escalate
    "packages/ai-parrot/src/parrot/clients/base.py",
    "packages/ai-parrot/src/parrot/bots/abstract.py",
)
```

### Does NOT Exist
- ~~a module → path reverse helper in `impact.py`~~ — derive paths by walking `packages/*/src/**/*.py` with `module_name_for`
- ~~an `imports` relation in wikitoolkit blast radius~~ — do not use wikitoolkit for this measurement
- ~~`DEFAULT_CORE_FANIN_THRESHOLD` changes~~ — threshold is confirmed at 50

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py", "action": "MODIFY"},
    {"path": "artifacts/logs/feat-563-core-fanin.tsv", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Evidence-first spike: the committed TSV is the justification of every `CORE_PATHS` entry.

### Key Constraints
- Run from the feature worktree root; the index must reflect the worktree tree, not the main checkout.
- `ImportIndex.build` (not `load_or_build`) — a fresh measurement, no cache.
- `CORE_PATHS` entries are repo-relative file paths (same form the planner compares against changed files).
- Keep `CORE_PATHS` a `tuple[str, ...]`, sorted, no duplicates.
- Do not touch `XDIST_SAFE_DISTRIBUTIONS` (TASK-3317 owns it).

### References in Codebase
- spec §2 Overview 2b, §7 R15, §8 resolved threshold question

---

## Implementation Blueprint

### Steps (in order)
1. Confirm `impact.py` and `policy.py` from TASK-3307/3305 exist — *why*: the measurement reuses the production index.
2. Run the measurement script below from the worktree root — *why*: one AST pass gives the same numbers the planner will see.
3. Write the TSV — *why*: evidence committed next to the decision.
4. Replace `CORE_PATHS` — *why*: threshold is confirmed; the measurement is authoritative (no sign-off).
5. Run the kernel tests — *why*: `CORE_PATHS` changes must not break planner/impact tests.

### Measurement script (inline, not committed)
```python
"""S4: transitive source fan-in per module → TSV + CORE_PATHS candidates."""
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "packages/ai-parrot/src/parrot/flows/dev_loop"))
from test_scope.impact import ImportIndex, module_name_for, source_fanin  # noqa: E402
from test_scope.policy import DEFAULT_CORE_FANIN_THRESHOLD  # noqa: E402

index = ImportIndex.build(ROOT)
rows = []
for path in sorted(ROOT.glob("packages/*/src/**/*.py")):
    rel = path.relative_to(ROOT).as_posix()
    module = module_name_for(rel)
    if module is None:
        continue
    fanin, dists = source_fanin(index, module)
    # FILL IN: text_mentions = count of distinct files under packages/*/src from
    # `rg -l -F <module> packages --glob '*/src/**/*.py'` (plus `parrot_tools.<x>` alias for parrot/tools/<x>),
    # excluding the module's own file — bounded by R15 cross-check definition
    text_mentions = 0
    core = fanin >= DEFAULT_CORE_FANIN_THRESHOLD
    under = fanin < DEFAULT_CORE_FANIN_THRESHOLD and text_mentions >= DEFAULT_CORE_FANIN_THRESHOLD
    rows.append((module, rel, fanin, text_mentions, ",".join(sorted(dists)), core, under))
rows.sort(key=lambda r: (-r[2], r[0]))
# FILL IN: write artifacts/logs/feat-563-core-fanin.tsv with the header from Scope; print the CORE_PATHS candidates
```

### `artifacts/logs/feat-563-core-fanin.tsv` (CREATE)
```text
module	path	ast_fanin	text_mentions	distributions	core_by_threshold	undercounted	in_core_paths
# FILL IN: one row per source module, sorted by ast_fanin desc — bounded by S4 definition
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/policy.py` (MODIFY)
```python
# FILL IN: disambiguate — replace the whole seeded tuple starting at the line
# `CORE_PATHS: tuple[str, ...] = (  # seed; final list written from spike S4 measurement; always escalate`
# (occurrences: 1, verified after TASK-3305/3317 with grep -c) through its closing `)` with:
CORE_PATHS: tuple[str, ...] = (  # measured by FEAT-563 S4 — artifacts/logs/feat-563-core-fanin.tsv; always escalate
    # FILL IN: every path with core_by_threshold or undercounted, sorted, one per line,
    # each with `# fan-in <ast> (ast) / <text> (text)` — bounded by spec §8 (threshold 50, measurement authoritative)
)
```
**Why**: G7b escalates when fan-in ≥ 50 **or** the path is listed; listing the threshold hits too makes the
core set explicit and reviewable, and the `undercounted` rows cover R15 blind spots.

### FILL IN checklist
- [ ] `text_mentions` via `rg -l -F`; bounded by R15 cross-check
- [ ] TSV written, sorted, header exact; bounded by S4
- [ ] `CORE_PATHS` = threshold ∪ undercounted, sorted, commented; bounded by spec §8
- [ ] report any AST vs grep gap > 2× for `clients/base.py` / `bots/abstract.py` in the Completion Note

---

## Acceptance Criteria

- [ ] `artifacts/logs/feat-563-core-fanin.tsv` exists with the exact header and ≥ 1 row per source module found
- [ ] `CORE_PATHS` equals the set of TSV rows with `core_by_threshold=True` or `undercounted=True` (script check below)
- [ ] `packages/ai-parrot/src/parrot/clients/base.py` and `packages/ai-parrot/src/parrot/bots/abstract.py` are in `CORE_PATHS` (or the Completion Note explains, with TSV numbers, why not)
- [ ] `DEFAULT_CORE_FANIN_THRESHOLD` still 50; `XDIST_SAFE_DISTRIBUTIONS` untouched
- [ ] Kernel tests still pass (Validation Commands)

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_impact.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py -q`

---

## Test Specification

```bash
head -1 artifacts/logs/feat-563-core-fanin.tsv | grep -q $'^module\tpath\tast_fanin\ttext_mentions\tdistributions\tcore_by_threshold\tundercounted\tin_core_paths$'
python - <<'PY'
import csv, sys
from pathlib import Path
sys.path.insert(0, "packages/ai-parrot/src/parrot/flows/dev_loop")
from test_scope.policy import CORE_PATHS, DEFAULT_CORE_FANIN_THRESHOLD
assert DEFAULT_CORE_FANIN_THRESHOLD == 50
rows = list(csv.DictReader(Path("artifacts/logs/feat-563-core-fanin.tsv").open(), delimiter="\t"))
expected = sorted({r["path"] for r in rows if r["core_by_threshold"] == "True" or r["undercounted"] == "True"})
assert list(CORE_PATHS) == expected, (len(CORE_PATHS), len(expected))
PY
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-3318-spike-core-fanin-core-paths.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
