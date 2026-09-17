# TASK-3315: Mandatory `## Validation Commands` contract + `check_task_graph` lint

**Feature**: FEAT-563 — Scoped Test Selection for the SDD Cycle
**Spec**: `sdd/specs/scoped-test-selection.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3304
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 / AC7. Today `validation_commands` only exists inside the optional
`DelegationPacket` and is never executed, so nothing tells a coder seat which tests
are *its* tests. This task makes a file-level `## Validation Commands` section
mandatory for every task that `/sdd-task` generates, and teaches the deterministic
graph lint (`scripts/sdd/check_task_graph.py`) to enforce it — mirroring the existing
`parallel_semantics` → `legacy-semantics` header-flag pattern so legacy indexes only warn.

The section is parsed by `test_scope.contract.parse_validation_commands` and judged by
`test_scope.contract.is_broad_pytest`, both created by TASK-3304. The same parser is used
later by the guard (task tier), so the lint and the runtime agree on one format.

---

## Scope

- Add `VALIDATION_CONTRACT = "required"` and `_check_validation_contract(...)` to
  `scripts/sdd/check_task_graph.py`, called from `check_graph()`.
- Emit four finding codes per task:
  - `missing-validation-commands` — `error` when the index header has
    `"validation_contract": "required"`, `warning` otherwise.
  - `broad-validation-command` — `error`: a command for which `is_broad_pytest(argv)` is True.
  - `directory-validation-target` — `error`: a pytest operand (node id stripped of `::…`)
    that is an existing directory.
  - `validation-path-unknown` — `warning`: operand neither exists under `root` nor is
    declared in the task's `## Files to Create / Modify`.
- Load the kernel **by path** as top-level `test_scope` (never `import parrot…`).
- Document the mandatory section and the new header flag in **both**
  `.claude/commands/sdd-task.md` and `.agent/workflows/sdd-task.md` (identical wording).
- Extend `tests/sdd_scripts/test_check_task_graph.py`.

**NOT in scope**: editing `sdd/templates/task.md` (orchestrator follow-up below — the
sdd-coder fidelity gate rejects any change under `sdd/`); the parser itself (TASK-3304);
guard/runtime use of the section (TASK-3309); agent prose (TASK-3319).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/check_task_graph.py` | MODIFY | `VALIDATION_CONTRACT`, kernel loader, `_check_validation_contract`, call in `check_graph`, docstring codes |
| `tests/sdd_scripts/test_check_task_graph.py` | MODIFY | tests for the four codes, required vs legacy header |
| `.claude/commands/sdd-task.md` | MODIFY | mandatory `## Validation Commands` + `"validation_contract": "required"` header |
| `.agent/workflows/sdd-task.md` | MODIFY | same text as the `.claude` copy |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/sdd/check_task_graph.py:31-39 (current imports)
from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from pydantic import BaseModel, Field

# tests/sdd_scripts/test_check_task_graph.py:6
from scripts.sdd.check_task_graph import check_graph, main, module_of, parse_declared_files
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py
PARALLEL_SEMANTICS = "exclusive"                                   # L41
_HEADING = re.compile(r"^## Files to Create ?/ ?Modify\s*$", re.M)  # L43
class Finding(BaseModel):                                           # L50
    level: str  # "error" | "warning"
    code: str
    tasks: list[str] = Field(default_factory=list)
    message: str
class GraphReport(BaseModel):                                       # L59 — findings: list[Finding]
class _Task(BaseModel):                                             # L74
    id: str; depends_on: list[str]; parallel: bool = True; notes: str = ""; text: str = ""
    files: dict[str, bool]  # path -> is CREATE
def parse_declared_files(task_md: str) -> dict[str, bool]:          # L83
def _read_task_text(root: Path, file: str) -> str:                  # L129
def check_graph(index_path: Path, root: Path) -> GraphReport:       # L176
    data = json.loads(index_path.read_text(encoding="utf-8"))       # L186
    add = report.findings.append                                    # L199
    exclusive_semantics = data.get("parallel_semantics") == PARALLEL_SEMANTICS  # L200
    return report                                                   # L300 (only occurrence)
def main(argv: list[str] | None = None) -> int:                     # L318

# tests/sdd_scripts/test_check_task_graph.py
_TASK = """# {tid}: demo ... ## Files to Create / Modify ... {rows} ... ## Codebase Contract ... {contract}"""  # L8-19
def _repo(tmp_path: Path, tasks: list[dict], header: dict | None = None) -> Path:  # L22 (header=None → {"parallel_semantics": "exclusive"})
def _codes(report) -> list[str]:                                    # L47
```

### Created by dependency tasks (TASK-3304 — verify it landed before starting)
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/contract.py  (stdlib-only, relative imports)
VALIDATION_HEADING: str = "## Validation Commands"
def parse_validation_commands(task_md: str) -> list[list[str]]: ...  # backticked bullets, shlex-split; [] when absent
def is_broad_pytest(argv: Sequence[str]) -> bool: ...
```

### Markdown anchors (verified)
- `.claude/commands/sdd-task.md:273` and `.agent/workflows/sdd-task.md:277` — `  "parallel_semantics": "exclusive",` (1 occurrence each)
- `.claude/commands/sdd-task.md:336` and `.agent/workflows/sdd-task.md:340` — `#### Complexity Contract (mandatory, per task)` (1 occurrence each)
- `.claude/commands/sdd-task.md:377` / `.agent/workflows/sdd-task.md:381` — `- **Every warning is resolved, not ignored**: ...` (§4b)

### Does NOT Exist
- ~~`validation_commands` on index task entries / `_Task`~~ — the SSOT is the task-file section (spec §8)
- ~~`VALIDATION_CONTRACT`, `_check_validation_contract`~~ — new here
- ~~`import parrot` in `check_task_graph.py`~~ — must stay parrot-free (navconfig `os.chdir` on import)
- ~~`## Validation Commands` in `sdd/templates/task.md`~~ — orchestrator follow-up, not this task's diff

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/check_task_graph.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_check_task_graph.py", "action": "MODIFY"},
    {"path": ".claude/commands/sdd-task.md", "action": "MODIFY"},
    {"path": ".agent/workflows/sdd-task.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/check_task_graph.py#check_graph",
    "sym:scripts/sdd/check_task_graph.py#Finding",
    "sym:scripts/sdd/check_task_graph.py#GraphReport",
    "sym:scripts/sdd/check_task_graph.py#_Task",
    "sym:scripts/sdd/check_task_graph.py#parse_declared_files",
    "sym:scripts/sdd/check_task_graph.py#main"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
The `legacy-semantics` block (`check_task_graph.py:200-208`): a header flag decides the
severity; absence of the flag degrades to a warning so old indexes keep passing.

### Key Constraints
- `check_task_graph.py` must not import `parrot` — load `test_scope` by path.
- Keep `check_graph`'s signature and existing findings unchanged; existing 6 tests must keep passing (only the shared `_TASK` fixture text may change).
- Operand extraction: skip argv[0] (`pytest`) and flags (`-…`, and the value after `-m`, `-k`, `-o`, `-p`, `-c`, `--rootdir`);
  strip `::node` suffix before filesystem checks.
- Google docstrings, type hints, no `print` outside `main`.

### References in Codebase
- `scripts/sdd/check_task_graph.py:200-208` — header-flag pattern
- `tests/sdd_scripts/test_check_task_graph.py:22-46` — `_repo` fixture builder to extend

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-3304's `test_scope/contract.py` exists — *why*: the lint reuses its parser so lint and guard agree.
2. Add the path loader + constant under the imports of `check_task_graph.py` — *why*: importing `parrot` chdirs and is slow.
3. Add `_check_validation_contract` and call it just before `return report` — *why*: one pass after all graph findings.
4. Extend the module docstring's Errors/Warnings lists with the four codes — *why*: the docstring is the lint's user doc.
5. Add tests; then update both sdd-task command copies identically — *why*: the two copies are kept in sync by convention.

### `scripts/sdd/check_task_graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^PARALLEL_SEMANTICS = "exclusive"$' scripts/sdd/check_task_graph.py)
# AFTER — insert below `PARALLEL_SEMANTICS = "exclusive"` (verified: scripts/sdd/check_task_graph.py:41)
VALIDATION_CONTRACT = "required"
_KERNEL_DIR = Path(__file__).resolve().parents[2] / "packages/ai-parrot/src/parrot/flows/dev_loop"
_FLAG_WITH_VALUE = frozenset({"-m", "-k", "-o", "-p", "-c", "--rootdir", "--confcutdir"})


def _load_contract():
    """Import ``test_scope.contract`` by path (top-level name), never via ``parrot``.

    Returns:
        The ``test_scope.contract`` module.
    """
    import importlib
    import sys

    if str(_KERNEL_DIR) not in sys.path:
        sys.path.insert(0, str(_KERNEL_DIR))
    return importlib.import_module("test_scope.contract")


def _pytest_operands(argv: list[str]) -> list[str]:
    """Positional operands of a pytest argv, ``::node`` suffix stripped."""
    # FILL IN: walk argv[1:], skip flags and the value following any flag in _FLAG_WITH_VALUE,
    # return operands with `.split("::", 1)[0]` — bounded by spec §3 M9 (files or node ids only)
    raise NotImplementedError


def _check_validation_contract(tasks: dict[str, _Task], root: Path, required: bool) -> list[Finding]:
    """Emit the four validation-contract findings for every task.

    Args:
        tasks: Parsed tasks (``text`` and ``files`` populated).
        root: Repository root for existence checks.
        required: True when the index header declares ``"validation_contract": "required"``.

    Returns:
        Findings: missing-validation-commands, broad-validation-command,
        directory-validation-target, validation-path-unknown.
    """
    contract = _load_contract()
    findings: list[Finding] = []
    for tid, task in tasks.items():
        if not task.text:
            continue
        commands = contract.parse_validation_commands(task.text)
        # FILL IN: no commands → missing-validation-commands (error if required else warning);
        # per command: is_broad_pytest → broad-validation-command (error);
        # operand is an existing dir under root → directory-validation-target (error);
        # operand neither exists nor in task.files → validation-path-unknown (warning) — bounded by AC7
    return findings
```
**Why this shape**: the loader keeps the script parrot-free and reuses the kernel parser (one
format for lint and guard). Severity of `missing-validation-commands` follows the header flag
exactly like `legacy-semantics`, so every pre-FEAT-563 index keeps exiting 0.

```python
# occurrences: 1 (verified: grep -c '^    return report$' scripts/sdd/check_task_graph.py)
# BEFORE — insert above `    return report` (verified: scripts/sdd/check_task_graph.py:300)
    report.findings.extend(
        _check_validation_contract(tasks, root, data.get("validation_contract") == VALIDATION_CONTRACT)
    )
```
**Why**: runs after all graph checks; `data` and `root` are already in scope in `check_graph`.

### `tests/sdd_scripts/test_check_task_graph.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def test_missing_dependency_and_legacy_semantics_warned' tests/sdd_scripts/test_check_task_graph.py)
# AFTER — append at end of file (after test_missing_dependency_and_legacy_semantics_warned, L116-122)
def _with_validation(tmp_path: Path, commands: list[str], required: bool, files: dict | None = None):
    """One-task repo whose task file carries a Validation Commands section."""
    # FILL IN: build via _repo(...) with header {"parallel_semantics": "exclusive", **({"validation_contract": "required"} if required else {})},
    # then append "\n## Validation Commands\n" + bullets "- `<cmd>`" to the task file — bounded by M9 section format
    raise NotImplementedError


def test_missing_validation_commands_error_when_required(tmp_path): ...  # FILL IN
def test_missing_validation_commands_warning_on_legacy_header(tmp_path): ...  # FILL IN
def test_broad_validation_command_is_error(tmp_path): ...  # FILL IN: `pytest packages/x/tests -q`
def test_directory_validation_target_is_error(tmp_path): ...  # FILL IN: mkdir tests/sub, `pytest tests/sub -q`
def test_unknown_validation_path_is_warning(tmp_path): ...  # FILL IN: neither exists nor declared
def test_declared_or_existing_file_passes(tmp_path): ...  # FILL IN: declared CREATE test file + node id → no contract findings
```
**Why**: covers every code and both header modes (AC7). Existing tests stay unchanged; they have
no `validation_contract` flag so they only gain *warnings* — assert with `_codes` filtering where
an existing test asserts an exact code list (FILL IN: check `test_evidence_free_chain_is_flagged`,
`test_justified_edges_pass` and `test_missing_dependency_and_legacy_semantics_warned`, which assert exact findings; make them pass by adding a valid
`## Validation Commands` to `_TASK` OR filtering contract codes — prefer adding the section to `_TASK`).

### `.claude/commands/sdd-task.md` (MODIFY)
````markdown
# occurrences: 1 (verified: grep -c '^#### Complexity Contract (mandatory, per task)$' .claude/commands/sdd-task.md)
# BEFORE — insert above `#### Complexity Contract (mandatory, per task)` (verified: .claude/commands/sdd-task.md:336)
#### Validation Commands (mandatory, per task — FEAT-563)

Every generated task MUST carry a `## Validation Commands` section placed right
after `## Acceptance Criteria`: one bullet per command, each a backticked
`pytest` invocation whose operands are **test files or node ids** — never a
directory, never `tests/` or `packages/<dist>/tests`, never a bare `pytest`.

```markdown
## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_mirror.py -q`
- `pytest tests/sdd_scripts/test_check_task_graph.py::test_validation_contract_findings -q`
```

This is what the sdd-coder guard rewrites a broad pytest to. New per-spec index
headers MUST include `"validation_contract": "required"`; `check_task_graph`
then reports `missing-validation-commands`, `broad-validation-command` and
`directory-validation-target` as errors (`validation-path-unknown` warns).
````
Also: add `  "validation_contract": "required",` on the line after the verified anchor
`  "parallel_semantics": "exclusive",` (L273, 1 occurrence), and append to the §4b bullet list
(after the `- **Every warning is resolved, not ignored**` bullet, L377) one bullet naming the
four validation-contract codes.
**Why**: `/sdd-task` is the writer of the section and the header flag; without both the lint cannot escalate to errors.

### `.agent/workflows/sdd-task.md` (MODIFY)
Same three insertions, verified anchors: `#### Complexity Contract (mandatory, per task)` at L340,
`  "parallel_semantics": "exclusive",` at L277, `- **Every warning is resolved, not ignored**` at L381
(1 occurrence each). Text must be byte-identical to the `.claude` copy's inserted text.
**Why**: the two copies are consumed by different hosts and must not drift.

### FILL IN checklist
- [ ] `check_task_graph.py::_pytest_operands` — flag/value skipping; bounded by M9 (files or node ids)
- [ ] `check_task_graph.py::_check_validation_contract` — four codes & severities; bounded by AC7
- [ ] `test_check_task_graph.py::_with_validation` + six tests; bounded by AC7
- [ ] keep existing exact-findings tests green (add a valid section to `_TASK`)

---

## Orchestrator follow-up (NOT part of the coder diff)

The sdd-coder fidelity gate rejects any change under `sdd/` (`sdd_coder/fidelity.py:60`), so
the orchestrator (`sdd-worker`, owner of SDD state) applies this when closing TASK-3315:

- Edit `sdd/templates/task.md`: insert a `## Validation Commands` section immediately after the
  `## Acceptance Criteria` section (currently at `sdd/templates/task.md:266`, before
  `## Test Specification` at L276), with the same two example bullets as the command doc and a
  one-line note "file-level pytest only — no directories, no package roots".
- Commit it with the task's SDD state update (`sdd: …`).

---

## Acceptance Criteria

- [ ] AC7 — `check_task_graph.py` reports `missing-validation-commands` (error with `"validation_contract": "required"`, warning otherwise), `broad-validation-command` (error), `directory-validation-target` (error), `validation-path-unknown` (warning)
- [ ] AC7 — both `/sdd-task` copies require the section and the header flag, with identical inserted text
- [ ] Existing `test_check_task_graph.py` tests still pass
- [ ] `check_task_graph.py` does not import `parrot` (`grep -n "import parrot\|from parrot" scripts/sdd/check_task_graph.py` empty)
- [ ] `ruff check scripts/sdd/check_task_graph.py tests/sdd_scripts/test_check_task_graph.py` clean

## Validation Commands
- `pytest tests/sdd_scripts/test_check_task_graph.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_check_task_graph.py (additions)
def test_broad_validation_command_is_error(tmp_path):
    index = _with_validation(tmp_path, ["pytest packages/x/tests -q"], required=True)
    report = check_graph(index, tmp_path)
    assert "broad-validation-command" in _codes(report)
    assert main([str(index), "--root", str(tmp_path)]) == 1


def test_missing_validation_commands_warning_on_legacy_header(tmp_path):
    index = _repo(tmp_path, [{"id": "TASK-1", "files": {"pkg/a.py": "CREATE"}}])
    report = check_graph(index, tmp_path)
    missing = [f for f in report.findings if f.code == "missing-validation-commands"]
    assert missing and missing[0].level == "warning"
```

```bash
diff <(grep -A14 '^#### Validation Commands' .claude/commands/sdd-task.md) \
     <(grep -A14 '^#### Validation Commands' .agent/workflows/sdd-task.md)   # empty
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
7. **Move this file** to `tasks/completed/TASK-3315-task-validation-contract-lint.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (sonnet, sequential fallback — `complex_model_unavailable`, same
systemic roster gap as prior tasks; user-authorized direct implementation)
**Date**: 2026-09-17
**Notes**: Added `VALIDATION_CONTRACT`, `_KERNEL_DIR`, `_FLAG_WITH_VALUE`, `_load_contract`
(path-loads `test_scope.contract`, never `parrot`), `_pytest_operands` (flag/value skipping
per the given `_FLAG_WITH_VALUE` set), and `_check_validation_contract` (all four finding
codes) to `scripts/sdd/check_task_graph.py`; wired into `check_graph` right before
`return report`; extended the module docstring's Errors/Warnings lists. Extended
`tests/sdd_scripts/test_check_task_graph.py`: gave `_TASK`/`_repo` an optional per-task
`validation` list (rendered as a real `## Validation Commands` section only when provided —
absence means no section at all, needed for `test_missing_validation_commands_warning_on_legacy_header`
to fire correctly), added `_with_validation` and six new tests covering all four codes and
both header modes, and added a self-referencing `validation` command (the task's own generated
`.md` file — always exists, never broad, never a directory) to the three pre-existing
exact-findings tests (`test_evidence_free_chain_is_flagged`, `test_justified_edges_pass`,
`test_missing_dependency_and_legacy_semantics_warned`) so they stay green under the new
`missing-validation-commands` warning. All 12 tests pass, `ruff check` clean, no `import
parrot`/`from parrot` in the script (grep empty), and the two `.claude`/`.agent` sdd-task.md
copies verified byte-identical for the inserted `#### Validation Commands` block (`diff`
empty).

**Orchestrator follow-up applied** (separate commit, per this task's own instruction that the
sdd-coder fidelity gate rejects any `sdd/` change): edited `sdd/templates/task.md` to insert a
`## Validation Commands` section (with a one-line "file-level pytest only" note and the same
two example bullets as the command docs) immediately after `## Acceptance Criteria`, before
`## Test Specification`.

**Deviations from spec**: none — only the four listed coder-diff files plus the
orchestrator-owned `sdd/templates/task.md` follow-up were touched.

**Deviations from spec**: none | describe if any
