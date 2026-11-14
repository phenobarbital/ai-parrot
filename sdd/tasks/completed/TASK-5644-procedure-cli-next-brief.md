# TASK-5644: `parrot sdd procedure` — next and brief

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5643
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (second half), goals G4 and G9. `next` answers "which procedures apply to this
state and which step is valid next"; `brief` renders the short block a task start receives. Both
are deterministic and make no LLM call.

---

## Scope

- Add `render_brief` and the verbs `next` and `brief` to `parrot/sdd/scripts/procedure.py`.
- Extend the `procedure` noun in `VERBS` with `next` and `brief`.
- Extend `tests/sdd/test_procedure_cli.py`.

**NOT in scope**: delivering the block through the briefing path (TASK-5650); the MCP tool
(TASK-5649); changes to the resolver or the probes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure.py` | MODIFY | `render_brief`, `next`, `brief` |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Add the two verbs to the noun |
| `packages/ai-parrot/tests/sdd/test_procedure_cli.py` | MODIFY | Tests for both verbs |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Everything in `procedure.py` and the `VERBS` line comes from
> TASK-5643 — re-read both files after it lands and correct this section if a name differs.

### Verified Imports
```python
from parrot.knowledge.wiki.procedure.models import Resolution                     # TASK-5633
from parrot.knowledge.wiki.procedure.resolver import resolve                      # TASK-5641
from parrot.sdd.scripts.procedure_advice import checkout_root                     # TASK-5637
from parrot.sdd.scripts.procedure_probes import SddProbeRunner, scope_for         # TASK-5641
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/procedure.py  (TASK-5643)
def _settings(root: Path) -> ProcedureSettings          # .enabled .brief_max_lines .remote_probe_timeout_seconds
def _load_specs(root: Path) -> tuple[list[ProcedureSpec], bool]     # (specs, stale)
def _parser() -> argparse.ArgumentParser                 # subparsers with set_defaults(func=...)
def main(argv: Sequence[str] | None = None) -> int

# packages/ai-parrot/src/parrot/sdd/cli.py  (TASK-5643)
    "procedure": {
        v: ("procedure", (v,), f"Procedure graph: {v}") for v in ("build", "list", "show", "check")
    },

# Dependency-provided:
def resolve(specs, scope, runner, *, allow_remote: bool = True, stale: bool = False) -> Resolution
class SddProbeRunner: def __init__(self, checkout: Path, *, timeout: int = 5) -> None
def scope_for(checkout: Path, *, feature: str | None = None, task: str | None = None) -> dict[str, str]
class Resolution(BaseModel): scope: dict[str, str]; stale: bool; next: list[ResolvedProcedure]; mandatory: list[ProcedureSpec]
class ResolvedProcedure(BaseModel): spec: ProcedureSpec; done: bool | None; ready: bool; preconditions: list[ProbeResult]
class ProbeResult(BaseModel): check: ProbeCheck; value: bool | None; cost: ProbeCost; detail: str

# Task file header (sdd/templates/task.md:1-9), the lines `brief` parses:
#   # TASK-<NNN>: <Title>
#   **Spec**: `sdd/specs/<feature-slug>.spec.md`
# Task file name: TASK-<NNN>-<slug>.md  (a brief task: HOTFIX-<KEY>-<N>-<slug>.md)
```

### Does NOT Exist
- ~~A `render_brief` anywhere~~ — this task creates it.
- ~~`parrot sdd task start`~~ — not a CLI verb; starting a task is workflow prose.
- ~~An LLM call in either verb~~ — forbidden (spec §5).
- ~~A non-zero exit from `brief`~~ — `brief` always exits 0 once its arguments parse; a briefing
  must never break a task start.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/cli.py#VERBS"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Two roots**: specs come from the primary checkout (`find_shared_root`, through `_load_specs`);
  state is probed in the current checkout, `checkout_root(Path.cwd())` (fall back to the primary
  root).
- **`next [--feature X] [--task T] [--no-remote] [--json]`**: `scope_for(checkout, ...)` →
  `SddProbeRunner(checkout, timeout=settings.remote_probe_timeout_seconds)` → `resolve(specs,
  scope, runner, allow_remote=not args.no_remote, stale=stale)`. Text output: a `scope:` line, one
  line per next node (`<id>  <mode>  <command>` plus `  unmet: <checks>` when any precondition is
  not `True`), then `mandatory:` lines. `--json` prints `resolution.model_dump_json(indent=2)`.
  Exit 0.
- **`brief --task-file <task.md> [--max-lines N]`**: the task id is the leading
  `TASK-<digits>` or `HOTFIX-…-<digits>` of the file name; the feature is the slug in the
  `**Spec**:` line; local probes only (`allow_remote=False`). Print `render_brief(...)` and
  nothing else. Print nothing when `procedure.enabled` is false, when no plane exists, when the
  plane is stale and could not be rebuilt, or when the file cannot be read.
- **`render_brief(resolution, *, max_lines)`**: a Markdown block
  ```
  ### Procedure
  Position: feature `<slug>`, task `<TASK>`.
  Next: <title> — `<command>`
  Mandatory:
  - <title>: `<command>` (never by hand; use `<use_instead>`)
  ```
  One `Next:` line per next node (append ` (unmet: <checks>)` when a precondition is false or
  unknown); the `(never by hand…)` part only when `use_instead` is set; the `Mandatory:` section
  only when there is at least one mandatory node. Return `""` when there is neither a next node
  nor a mandatory node. Truncate to `max_lines` lines.
- A check is rendered as `<probe>` plus `=<expect>` when `expect` is a string.

---

## Implementation Blueprint

### Steps (in order)
1. Add `render_brief` — *why*: pure, shared by `brief` and by TASK-5650.
2. Add the two `_cmd_*` functions and their subparsers — *why*: same structure as the four verbs.
3. Extend the `VERBS` tuple.
4. Add the tests.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure.py` (MODIFY)
```python
# Add the four imports listed under "Verified Imports" to the module's import block.

# occurrences: 1 expected (verify: grep -c 'def _parser() -> argparse.ArgumentParser:' packages/ai-parrot/src/parrot/sdd/scripts/procedure.py)
# BEFORE — insert above `def _parser() -> argparse.ArgumentParser:`
def render_brief(resolution: Resolution, *, max_lines: int) -> str:
    """Markdown block: one line of position, the next valid step(s), then 'Mandatory:' rules
    (command + use_instead). '' when there is nothing to say."""
    # FILL IN: per Implementation Notes "render_brief".


def _scope_from_task_file(path: Path) -> tuple[str | None, str | None]:
    """(feature slug, task id) read from a task file's name and its `**Spec**:` line; (None, None) on failure."""
    # FILL IN


def _cmd_next(args: argparse.Namespace) -> int:
    # FILL IN: per Implementation Notes "next".
    ...


def _cmd_brief(args: argparse.Namespace) -> int:
    # FILL IN: per Implementation Notes "brief"; always return 0.
    ...


# Inside `_parser()`, after the `check` subparser block and before `return parser`:
# occurrences: 1 expected (verify: grep -c '    p_check.set_defaults(func=_cmd_check)' packages/ai-parrot/src/parrot/sdd/scripts/procedure.py)
# AFTER — insert below `    p_check.set_defaults(func=_cmd_check)`
    p_next = sub.add_parser("next", help="Applicable procedures and the valid next step(s).")
    p_next.add_argument("--feature")
    p_next.add_argument("--task")
    p_next.add_argument("--no-remote", action="store_true")
    p_next.add_argument("--json", action="store_true")
    p_next.set_defaults(func=_cmd_next)
    p_brief = sub.add_parser("brief", help="Print the task-start procedure block.")
    p_brief.add_argument("--task-file", type=Path, required=True)
    p_brief.add_argument("--max-lines", type=int, default=None)
    p_brief.set_defaults(func=_cmd_brief)
```
**Why**: `render_brief`'s signature is fixed by spec §3 M7. Also update the `main` docstring to
name the six verbs.

### `packages/ai-parrot/src/parrot/sdd/cli.py` (MODIFY)
```python
# occurrences: 1 expected (verify: grep -c 'for v in ("build", "list", "show", "check")' packages/ai-parrot/src/parrot/sdd/cli.py)
# REPLACE the tuple in that line (written by TASK-5643) so it reads:
        v: ("procedure", (v,), f"Procedure graph: {v}") for v in ("build", "list", "show", "next", "check", "brief")
```
**Why**: the final verb set of spec §3 M7.

### `packages/ai-parrot/tests/sdd/test_procedure_cli.py` (MODIFY)
```python
# Append at the end of the file TASK-5643 created. Anchor (re-verify): `def test_sdd_config_procedure_section() -> None:`
# occurrences: 1 expected (verify: grep -c 'def test_sdd_config_procedure_section' packages/ai-parrot/tests/sdd/test_procedure_cli.py)

def _seed_feature(root: Path, *, status: str = "pending") -> Path:
    """Write sdd/specs/demo.spec.md, sdd/tasks/index/demo.json (TASK-1 <status>) and
    sdd/tasks/active/TASK-1-demo.md (with the `**Spec**:` header line); return the task file."""
    # FILL IN


def test_next_reports_the_valid_step(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """With a spec and no index, `next --feature demo --json` lists sdd:task as next; two runs are equal."""
    # FILL IN: main(["build"]); write only the spec; run twice; compare the two JSON documents.


def test_next_no_remote_marks_remote_probes_unknown(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--no-remote never runs git or gh (patch subprocess.run in procedure_probes to fail the test if called)."""
    # FILL IN


def test_brief_prints_block_or_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`brief --task-file` prints the block for a seeded task, and nothing when disabled or without a plane."""
    # FILL IN: assert exit code 0 in all three cases; the block starts with "### Procedure".


def test_render_brief_limits_lines() -> None:
    """render_brief truncates to max_lines and returns '' for an empty resolution."""
    # FILL IN
```

### FILL IN checklist
- [ ] `procedure.py::render_brief`, `_scope_from_task_file`, `_cmd_next`, `_cmd_brief`
- [ ] `test_procedure_cli.py` — `_seed_feature` and four test bodies
- [ ] Update `test_cli_verbs` (TASK-5643) to expect the six verbs in `VERBS["procedure"]`

---

## Acceptance Criteria

- [ ] `parrot sdd procedure next` gives the same answer on two runs with unchanged state and makes no LLM call.
- [ ] `--no-remote` runs no subprocess for remote probes and reports them as unknown.
- [ ] `brief` exits 0 and prints either the block or nothing; it prints nothing when `procedure.enabled` is false.
- [ ] `render_brief` returns `""` for an empty resolution and never exceeds `max_lines` lines.
- [ ] `VERBS["procedure"]` has exactly `build`, `list`, `show`, `next`, `check`, `brief`.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5643 is `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN` and replace every `...` placeholder.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5644 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5644
- Feature: procedural-graph-plane
- Implementation SHA: f4c309c82d59d7bb08857e416e28dd7bc762a3c3
- Closed at (UTC): 2026-11-13T23:11:44+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 409.5s · Tokens: n/a |
