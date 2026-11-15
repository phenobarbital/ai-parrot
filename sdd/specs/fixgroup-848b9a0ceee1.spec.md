---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, procedure-graph, guards, bugfix]
docs:
  policy: none
---

# Feature Specification: Procedure guards and plane — FEAT-891 review follow-ups

**Feature ID**: FEAT-899
**Date**: 2026-11-15
**Author**: Jesus Lara
**Status**: approved
**Discovered-from**: `issue:bab5aa4a8d70` (opened from `spec:FEAT-891`)

---

## 1. Motivation & Business Requirements

### Problem Statement

The FEAT-891 code review left ten minor notes on the procedure guards and plane, filed together as
`issue:bab5aa4a8d70`. Each was re-checked against `origin/dev` at `0366aaabf8`. Six are real defects,
one is a spec omission, and three are not defects (see Non-Goals).

| # | Review note | Verdict | Handled by |
|---|---|---|---|
| 1 | `match_guards` matches `path_globs` against the raw argument, so `cd sdd/tasks/active && mv X ../completed/`, `git -C sdd/tasks/active mv X ...` and an absolute path all evade the mandatory `task-close` bypass guard | real | M1 |
| 2 | `flow.base_allowed` denies `gh pr create --base main` on `fix-*` branches | **not a defect** | Non-Goals |
| 3 | `evaluate_command` cuts the whole message at 600 chars, which can remove the `PARROT_ALLOW_PROCEDURE=1` hint | real | M2 |
| 4 | `task.depends_done` accepts only `done`; `feature.tasks_done` accepts `done-with-issues` too, so a dependent of a `done-with-issues` task is denied at task close | real | M3 |
| 5 | `branch.pushed` returns `False` on any `git rev-list` failure; a failed read is unknown, not "not pushed" | real | M3 |
| 6 | `op_procedure_next` catches only `ValueError`/`OSError`; any other error escapes the MCP tool | real | M4 |
| 7 | `test_wheel_only_foreign_repo.py` carries ~60 lines of unrelated `black` reformatting | no action | Non-Goals |
| 8 | `cli.py` adds `shell_prefix` to `_UNMOUNTED` (drive-by) | no action | Non-Goals |
| 9 | the installer builds the plane even when `procedure.enabled` is false (and calls `asyncio.run` in a sync step) | half real | M5 |
| 10 | `ProcedureManifest.uncovered_ok` is not in the FEAT-891 spec §2 | spec omission | M6 |

### Goals

- G1: a bypass guard matches the path a command really acts on — after a `cd` segment, with `git -C <dir>`,
  and for an absolute path inside the checkout.
- G2: a deny message always ends with the deliberate-exception hint, and never exceeds `MAX_ADVICE_CHARS`.
- G3: `task.depends_done` and `feature.tasks_done` agree on what a closed task is.
- G4: `branch.pushed` reports unknown (`None`) when git cannot answer.
- G5: `op_procedure_next` never raises; an unexpected error becomes an error result.
- G6: `parrot sdd install` does not build the procedure plane when `procedure.enabled` is false.
- G7: the FEAT-891 spec lists `ProcedureManifest.uncovered_ok`.

### Non-Goals (explicitly out of scope)

- **Note 2 — rejected with evidence.** `brief_worktree_plan` picks the branch prefix from the base:
  `prefix = "hotfix" if base_branch == cfg.hotfix_base else "fix"` (`parrot/sdd/scripts/brief_meta.py:197`).
  A `fix-*` branch is therefore never based on the hotfix base; a brief that targets `main` is named
  `hotfix-*`, which `flow.base_allowed` already allows. No change to the probe.
- **Note 7.** Reverting formatting that `black` produced is itself churn and the file is formatter-clean.
- **Note 8.** `shell_prefix.main()` replaces the current process, so it is correctly unmounted. The
  related gap (`worker_notification`) is tracked separately as `issue:bdc696964162`.
- **Note 9, `asyncio.run` half.** The installer is a synchronous CLI path and already calls `asyncio.run`
  for the roster probe (`installer.py:1690`); the step's `except Exception` turns a running-loop
  `RuntimeError` into a `skipped` action. No change.
- Subshell forms such as `(cd dir && mv ...)` and `pushd`/`popd` tracking. The guard stays a
  best-effort, stdlib-only parser.
- Any change to the procedure manifest (`sdd-workflow.yaml`), the index schema or the resolver.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:446d68b7fc30be0a91e40233a28865b20251180af95d953e2abf6e56de7bdec9 evaluation_digest=sha256:f50f65b66341c42944306f6f1677f926d3d9b01d88e70f4eba5a7bf9a0da5b42 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

All changes are local corrections inside existing functions. `procedure_advice.py` stays stdlib-only and
never raises (it is loaded by the hook guards as a script sibling).

**M1 — path resolution in `match_guards`.** `match_guards` gains two optional keyword arguments,
`checkout` and `cwd`. It walks the command segments in order and keeps an *effective directory*,
expressed relative to the checkout root:

- it starts as `cwd` relative to `checkout` (empty when either is missing or `cwd` is outside `checkout`);
- a segment whose executable is `cd` with exactly one non-option argument replaces it with that target
  (joined to the current effective directory when relative, made checkout-relative when absolute);
- for a `git` segment, leading global `-C <dir>` options are removed from the argv before `argv_prefix`
  is compared, and the last `-C` directory applies to that segment only.

Each remaining argument is then normalised before the glob test: an absolute path inside the checkout
becomes checkout-relative; a relative path is joined to the segment's effective directory and
`normpath`-ed. A path that resolves outside the checkout keeps its `..` prefix or absolute form and so
matches no repository glob. With both keyword arguments omitted the effective directory starts empty and
absolute paths are left as they are, so a command with no `cd` segment and no `git -C` option matches
exactly as today; `cd` and `git -C` are tracked in every case.
`evaluate_command` passes `checkout=checkout, cwd=Path(cwd)`.

**M2 — bounded message.** A helper builds the message from a fixed prefix, a variable middle and a fixed
suffix, and truncates only the middle (ending it with `…`) so the total is at most `MAX_ADVICE_CHARS` and
the suffix always survives. A message already within the limit is byte-for-byte what it is today.

**M3 — probe semantics.** One module constant, `CLOSED_STATUSES = frozenset({"done", "done-with-issues"})`,
is used by both `_probe_task_depends_done` and `_probe_feature_tasks_done`. `SddProbeRunner._branch_pushed`
returns `None` when `git rev-list` exits non-zero.

**M4 — `op_procedure_next`.** The handler catches `Exception` and returns
`OperationResult(text="<ExcType>: <message>", is_error=True)`. `ValueError`/`OSError` keep their current
text (`str(exc)`).

**M5 — installer.** `_install_procedure_index_step` reads `load_sdd_config(root).procedure`; when it is
set and `enabled` is false the step returns `["procedure index: skipped (procedure.enabled is false)"]`
without importing or building anything.

**M6 — spec text.** One line added to the `ProcedureManifest` model in
`sdd/specs/procedural-graph-plane.spec.md` §2.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `procedure_advice.evaluate_command` | calls | passes `checkout`/`cwd` to `match_guards`; builds text through the bounded helper |
| `dangerous_actions` hook guard | unchanged caller | reaches the change only through `evaluate_command` |
| `SddProbeRunner` | modifies | `_branch_pushed` only |
| `wiki_procedure_next` MCP tool / `parrot_tools.wiki.procedure` | unchanged callers | receive an error result instead of an exception |

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: guard path resolution | yes | signatures and resolution rules fixed below | — |
| M2: bounded message | yes | helper signature, `…` marker, suffix text fixed | — |
| M3: probe semantics | yes | constant name and return values fixed | — |
| M4: `op_procedure_next` errors | yes | catch clause and result text fixed | — |
| M5: installer `enabled` | yes | action text fixed | — |
| M6: spec text | yes | exact line fixed | — |

### Module 1: Guard path resolution
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py`
- **Responsibility**: match bypass guards against the path a segment acts on (G1).
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # modifies packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py
  def _change_directory(tokens: list[str]) -> str | None:
      """Return the target of a plain ``cd <dir>`` segment, or None for any other segment."""

  def _git_directory(argv: list[str]) -> tuple[list[str], str | None]:
      """Strip leading git global ``-C <dir>`` options; return (remaining argv, last directory or None)."""

  def _relative_directory(base: str, target: str, checkout: Path | None) -> str:
      """Return ``target`` as a checkout-relative POSIX directory, joined to ``base`` when relative."""

  def _normalise_path(value: str, *, base: str = "", checkout: Path | None = None) -> str:  # verified: procedure_advice.py:208
      """Normalize a guard argument to a POSIX-style checkout-relative path.

      A relative ``value`` is joined to ``base``; an absolute ``value`` inside ``checkout`` is made relative.
      """

  def match_guards(  # verified: procedure_advice.py:216
      index: Mapping[str, Any],
      command: str,
      *,
      checkout: Path | None = None,
      cwd: Path | None = None,
  ) -> list[dict[str, Any]]:
      """Return index guards matching any command segment, preserving index order. Never raises."""
  ```

### Module 2: Bounded advice message
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py`
- **Responsibility**: keep the escape hint when a message is truncated (G2).
- **Depends on**: — (shares the file with M1 and M3)
- **Interface Skeleton**:
  ```python
  def _bounded_text(prefix: str, variable: str, suffix: str = "", *, limit: int = MAX_ADVICE_CHARS) -> str:  # MAX_ADVICE_CHARS verified: procedure_advice.py:259
      """Return ``prefix + variable + suffix`` within ``limit``, truncating only ``variable`` (marked with ``…``)."""
  ```
  Deny message parts — prefix `Procedure {id} is mandatory: `, variable `{reason}. Use: {use}`, suffix
  `. (Deliberate exception: ask the user to re-run with PARROT_ALLOW_PROCEDURE=1.)`.
  Advise message parts — prefix `Procedure {id}: `, variable `{reason}. {advice_text}`, no suffix.

### Module 3: Probe semantics
- **Paths**: `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py`,
  `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py`
- **Responsibility**: G3 and G4.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  # procedure_advice.py
  CLOSED_STATUSES: frozenset[str] = frozenset({"done", "done-with-issues"})

  def _probe_task_depends_done(checkout, scope, args) -> bool | None:  # verified: procedure_advice.py:389
      """Return whether all dependencies of the scoped task are closed (``CLOSED_STATUSES``)."""

  # procedure_probes.py
  class SddProbeRunner:
      def _branch_pushed(self, checkout, scope, args) -> bool | None:  # verified: procedure_probes.py:70
          """Return whether HEAD is not ahead of its upstream; None when git cannot answer."""
  ```

### Module 4: `op_procedure_next` error boundary
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py`
- **Responsibility**: G5.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  async def op_procedure_next(store: Any, params: ProcedureNextInput, **context: Any) -> OperationResult:  # verified: operations.py:90
      """Resolve the next valid procedure step(s); never raises — any failure is an ``is_error`` result."""
  ```

### Module 5: Installer honours `procedure.enabled`
- **Path**: `packages/ai-parrot/src/parrot/sdd/installer.py`
- **Responsibility**: G6.
- **Depends on**: —
- **Interface Skeleton**:
  ```python
  def _install_procedure_index_step(root: Path, receipt: dict[str, Any]) -> list[str]:  # verified: installer.py:1284
      """Build the procedure plane unless ``procedure.enabled`` is false; never fails the install."""
  ```

### Module 6: FEAT-891 spec text
- **Path**: `sdd/specs/procedural-graph-plane.spec.md`
- **Responsibility**: G7 — add, after the `procedures:` line of `ProcedureManifest`:
  `    uncovered_ok: list[str] = []            # /sdd-* commands deliberately left without a procedure node`

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_match_guards_resolves_effective_directory` | M1 | `cd sdd/tasks/active && mv T.md ../completed/`, `git -C sdd/tasks/active mv T.md ../completed/`, and an absolute path under the checkout each match the bypass guard; `cd docs && mv a b` does not |
| `test_match_guards_default_arguments_unchanged` | M1 | without `checkout`/`cwd` the existing results of `test_match_guards_every_segment` hold |
| `test_evaluate_command_denies_cd_bypass` | M1 | `evaluate_command` denies `cd sdd/tasks/active && mv ...` in a checkout with the mandatory guard |
| `test_deny_text_keeps_escape_hint` | M2 | with a `use_instead` longer than 600 chars the deny text is ≤ 600 chars and ends with the `PARROT_ALLOW_PROCEDURE=1.)` hint |
| `test_depends_done_accepts_done_with_issues` | M3 | a dependency in `done-with-issues` satisfies `task.depends_done`; `in-progress` does not |
| `test_branch_pushed_unknown_on_git_failure` | M3 | a non-zero `git rev-list` yields `None`; exit 0 with `0` yields `True`, with `2` yields `False` |
| `test_operation_reports_unexpected_error` | M4 | a `RuntimeError` raised while resolving returns `is_error=True` with `RuntimeError:` in the text |
| `test_install_skips_procedure_index_when_disabled` | M5 | with `{"procedure": {"enabled": false}}` the step returns the `skipped (procedure.enabled is false)` action and writes no index |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_procedure_advice.py
- packages/ai-parrot/tests/sdd/test_procedure_guards.py
- packages/ai-parrot/tests/sdd/test_procedure_cli.py
- packages/ai-parrot/tests/sdd/test_procedure_assets.py
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py
markers: none

---

## 5. Acceptance Criteria

- [ ] AC1: every test in the Validation Contract passes, including the eight new tests above.
- [ ] AC2: for a command with no `cd` segment and no `git -C` option, `match_guards(index, command)` with no
  keyword arguments returns what it returns today.
- [ ] AC3: `procedure_advice.py` still imports only the standard library (`test_advice_stdlib_only` passes).
- [ ] AC4: no deny or advise text exceeds `MAX_ADVICE_CHARS`; a deny text always ends with the escape hint.
- [ ] AC5: `ruff check` is clean on every changed file.
- [ ] AC6: `sdd-workflow.yaml`, the index schema and `_probe_flow_base_allowed` are unchanged.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.sdd.scripts import procedure_advice          # tests import it as `advice` (tests/sdd/test_procedure_advice.py)
from parrot.sdd.scripts.procedure_probes import SddProbeRunner, scope_for   # verified: procedure.py:21
from parrot.sdd.config import ProcedureSettings, SddConfigError, load_sdd_config   # verified: procedure.py:19
from parrot.knowledge.wiki.procedure.operations import op_procedure_next   # verified: operations.py:90
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (stdlib only)
def command_segments(command: str) -> list[list[str]]:                       # line 130
def _clean(tokens: list[str]) -> tuple[str, list[str]]:                      # line 165 — returns ("", []) for a `cd` segment
def _normalise_path(value: str) -> str:                                      # line 208
def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:   # line 216
MAX_ADVICE_CHARS = 600                                                       # line 259
def _probe_task_depends_done(checkout, scope, args) -> bool | None:          # line 389
def _probe_feature_tasks_done(checkout, scope, args) -> bool | None:         # line 405
def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:   # line 536

# packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py
class SddProbeRunner:
    def __init__(self, checkout: Path, *, timeout: int = 5) -> None:         # line 35
    def _branch_pushed(self, checkout, scope, args) -> bool | None:          # line 70

# packages/ai-parrot/src/parrot/sdd/config.py
class ProcedureSettings(BaseModel):                                          # line 25
    enabled: bool = True
class SddConfig(BaseModel):
    procedure: ProcedureSettings | None = None                               # line 57
```

### Does NOT Exist (Anti-Hallucination)

- ~~`op_procedure_next` in `parrot/sdd/scripts/procedure.py`~~ — it lives in `parrot/knowledge/wiki/procedure/operations.py`.
- ~~`match_guards(..., cwd=...)` today~~ — the keyword arguments are added by M1.
- ~~a sync `procedure.build`~~ — `procedure.build` is `async def` (`procedure.py:37`).
- ~~`procedure_advice` importing `parrot.*`~~ — forbidden; the module is stdlib-only.

### Edit Sites (Blueprint Anchors)

Verified against: `0366aaabf8`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | `def _normalise_path(value: str) -> str:` | `procedure_advice.py:208` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | `def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:` | `procedure_advice.py:216` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | `    return all(statuses.get(dependency) == "done" for dependency in dependencies)` | `procedure_advice.py:402` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | `        matches = match_guards(index, command)` | `procedure_advice.py:550` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | `        return Advice(decision, text[:MAX_ADVICE_CHARS])` | `procedure_advice.py:619` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py` | MODIFY | `        if completed.returncode != 0:` followed by `            return False` | `procedure_probes.py:88` | 1 (the `pr.open` twin at line 115 is indented 12 spaces and returns `None`) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/operations.py` | MODIFY | `    except (ValueError, OSError) as exc:` | `operations.py:118` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `        counts = asyncio.run(procedure.build(root))` | `installer.py:1295` | 1 |
| `sdd/specs/procedural-graph-plane.spec.md` | MODIFY | `    procedures: list[ProcedureSpec] = []    # ids written without the prefix; the producer adds it` | `procedural-graph-plane.spec.md:298` | 1 |
| `packages/ai-parrot/tests/sdd/test_procedure_advice.py` | MODIFY | `def test_match_guards_every_segment() -> None:` | `test_procedure_advice.py:66` | 1 |
| `packages/ai-parrot/tests/sdd/test_procedure_cli.py` | MODIFY | `def test_next_no_remote_marks_remote_probes_unknown(` | `test_procedure_cli.py:160` | 1 |
| `packages/ai-parrot/tests/sdd/test_procedure_assets.py` | MODIFY | append at end of file | — | — |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py` | MODIFY | `async def test_operation_without_plane_is_not_an_error(tmp_path: Path) -> None:` | `test_mcp_tool.py:94` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `procedure_advice.py`: stdlib only, every public helper wrapped so it never raises (existing
  `try/except` style in the file).
- Tests follow the existing fixtures in each test file; no new fixtures module.

### Known Risks / Gotchas

- **Concurrent edits.** `feat-FEAT-887-sdd-experience-memory` and `feat-FEAT-892-agent-memory-mixin` have
  live workers. The FEAT-887 line touched `procedure_advice.py` for TASK-5650, already merged through
  PR #2130; a later merge conflict in that file is possible and is resolved at `/sdd-done`.
- `os.path.normpath` collapses `..`; a path escaping the checkout must not be turned into a
  checkout-relative match. Keep the leading `..`.
- `git -C` may repeat; later relative values are relative to earlier ones (git semantics). Joining them in
  order is sufficient.
- The `…` marker counts toward the limit.

### External Dependencies

None.

---

## Worktree Strategy

- **Isolation**: one feature worktree, `feat-FEAT-899-fixgroup-848b9a0ceee1`.
- **Module dependency graph**: no import edges between modules. M1, M2 and M3 share
  `procedure_advice.py` and `test_procedure_advice.py`, so their work is serialized in one task chain;
  M4, M5 and M6 touch disjoint files and can run concurrently with it.
- **Shared files**: `procedure_advice.py`, `tests/sdd/test_procedure_advice.py` (M1, M2, M3).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: none (FEAT-891 is merged).

---

## Consequences

<!-- decision-audit: input_digest=sha256:446d68b7fc30be0a91e40233a28865b20251180af95d953e2abf6e56de7bdec9 evaluation_digest=sha256:f50f65b66341c42944306f6f1677f926d3d9b01d88e70f4eba5a7bf9a0da5b42 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/fixgroup-848b9a0ceee1.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: bugfix, guards, procedure-graph, sdd-tooling
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "bugfix",
      "guards",
      "procedure-graph",
      "sdd-tooling"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/fixgroup-848b9a0ceee1.spec.md"
    }
  ],
  "evaluation_digest": "sha256:f50f65b66341c42944306f6f1677f926d3d9b01d88e70f4eba5a7bf9a0da5b42",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:446d68b7fc30be0a91e40233a28865b20251180af95d953e2abf6e56de7bdec9",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

None.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document — ledger fix group authored by `/sdd-fix`).

---

## 10. Documentation

- **Policy**: `none`. `wiki/sdd-tooling/sdd/procedure-graph.md` already documents `uncovered_ok`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-15 | Jesus Lara | Initial spec from `issue:bab5aa4a8d70` |
