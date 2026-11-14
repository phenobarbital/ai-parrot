# TASK-5651: Pilot end-to-end test and the wheel-only smoke scenario

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5644, TASK-5645, TASK-5646, TASK-5648
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests", §3 Module 12 (release smoke) and design research S10. Two things
prove the pilot works as a whole: an end-to-end test over a temporary repository that uses the
**packaged** manifest and both guards, and a `procedure` entry in the wheel-only foreign-repo
smoke, which is what the release pipeline runs from an installed wheel.

---

## Scope

- Add `test_pilot_flow_end_to_end` to `tests/sdd/test_procedure_guards.py`.
- Add `SCENARIOS["procedure"]` and `test_wheel_only_procedure` to
  `tests/sdd/test_wheel_only_foreign_repo.py`.

**NOT in scope**: production code. If a test exposes a defect in another task's code, report it
in the Completion Note (and open a ledger issue); do not patch files this task does not list.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/sdd/test_procedure_guards.py` | MODIFY | End-to-end pilot test |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | `procedure` scenario and a dedicated smoke test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). The procedure modules are dependency-provided (TASK-5643 /
> 5644 CLI, TASK-5645 / 5646 guards, TASK-5647 packaged manifest, TASK-5648 install step).

### Verified Imports
```python
import parrot.sdd                                                 # Path(parrot.sdd.__file__).parent / "_assets" / "sdd" / "procedures" / "sdd-workflow.yaml"
from parrot.sdd.scripts import dangerous_actions, procedure, worktree_environment
from parrot.sdd.cli import VERBS                                  # already imported by the smoke test
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py
def _seed_feature(clone: Path) -> None: ...                       # :126 — spec + per-spec index + one active task, committed and pushed
@dataclass
class Scenario:                                                   # :341
    placeholders: dict[str, str]; prepare: Callable[[Path], None]; expect_exit: tuple[int, ...] = (0,)
    tools: tuple[str, ...] = ("git",); stdin: ...; expect_stdout: str = ""; prose: tuple[str, ...] = (); drop_flags: ...
_ANY_CLEAN = (0, 1, 2)                                            # :361
SCENARIOS: dict[str, Scenario] = {                                # :363 — keyed by the helper MODULE name
    ...
    "migrate_index": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),   # :461 (last entry)
}
def wheel(tmp_path_factory) -> Path: ...                          # :477 fixture — uses $PARROT_WHEEL_PATH or runs `uv build --wheel`
def managed_home(...) -> Path: ...                                # :487 fixture
def tools_dir(...) -> Path: ...                                   # :499 fixture
def _env(managed_home, tools_dir, ...) -> dict[str, str]: ...     # :508
def foreign_repo(...) -> tuple[Path, Path]: ...                   # :520 fixture — (working clone, bare origin)
def _install_all_hosts(repo: Path, env: dict[str, str]) -> None: ...   # :593 — `parrot sdd install` for the three hosts, then commit+push
def test_install_then_every_documented_helper_invocation(...): ...     # :601 — every documented helper needs a SCENARIOS entry

# packages/ai-parrot/tests/sdd/test_procedure_guards.py  (TASK-5646)
def _payload(root: Path, command: str) -> dict                   # {"cwd", "tool_name": "Bash", "tool_input": {"command"}}

# Guards (dependency-provided):
#   dangerous_actions: `python -m parrot.sdd.scripts.dangerous_actions --hook` reads the payload on stdin, writes one JSON line
#   worktree_environment.hook_response(payload, *, backend=...) -> {"hookSpecificOutput": {...}}
#   procedure.main(["build"]) / procedure.main(["next", "--feature", <slug>, "--task", <id>, "--no-remote", "--json"])
```

### Does NOT Exist
- ~~A `conftest.py` fixture `procedure_repo` / `built_plane`~~ — fixtures are local to each test
  file (spec rev 0.3 decision 9); define the helper in `test_procedure_guards.py`.
- ~~A fast path for the wheel smoke~~ — it builds a wheel (`uv build`) unless `PARROT_WHEEL_PATH`
  points at one; that is why it is an acceptance step and not a validation command.
- ~~A hand-written manifest in the end-to-end test~~ — it must copy the **packaged** asset.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_guards.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#Scenario",
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#_seed_feature",
    "sym:packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py#_install_all_hosts"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **End-to-end repository**: `tmp_path/repo` with `.git/HEAD` on `ref: refs/heads/feat-FEAT-1-demo`,
  `sdd/config.json` (`{}`), the packaged `sdd-workflow.yaml` copied to `sdd/procedures/`,
  `sdd/specs/demo.spec.md`, `sdd/tasks/index/demo.json` (`feature: demo`, `feature_id: FEAT-1`,
  tasks `TASK-1` in-progress and `TASK-2` pending with `depends_on: ["TASK-1"]`) and the two files
  under `sdd/tasks/active/`. `monkeypatch.chdir` into it; clear `PARROT_ALLOW_PROCEDURE`,
  `PARROT_ALLOW_DANGEROUS` and the two launcher markers from the environment.
- The four assertions of spec §4, in order: (1) after `build`, `next` for `TASK-2` reports
  `sdd:start`; (2) `git mv sdd/tasks/active/TASK-1-demo.md sdd/tasks/completed/` is denied by
  **both** guards with a reason naming `parrot sdd task close`; (3) `parrot sdd task close TASK-2
  demo verified` (a pending task) is denied by both; (4) `parrot sdd task close TASK-1 demo
  verified` produces no procedure output from either guard.
- For the dangerous-actions guard call the module the way the hook does (subprocess, payload on
  stdin, `cwd` in the payload). For the worktree guard call `hook_response` with the backend
  TASK-5646's tests use.
- **Scenario placeholder**: `<task.md>` maps to the task file `_seed_feature` creates
  (`sdd/tasks/active/TASK-001-demo-task.md`), so a documented `procedure brief --task-file
  <task.md>` line resolves once TASK-5650 adds it.

---

## Implementation Blueprint

### Steps (in order)
1. Add the end-to-end helper and test — *why*: it is the only test that exercises producer, plane,
   index, resolver and both guards together.
2. Add the scenario entry — *why*: a documented helper without a scenario fails the release smoke.
3. Add the dedicated smoke test.
4. Run the validation command, then the acceptance run of the smoke.

### `packages/ai-parrot/tests/sdd/test_procedure_guards.py` (MODIFY)
```python
# Append at the end of the file TASK-5646 created. Anchor (re-verify): `def test_control_files_include_advice(tmp_path: Path) -> None:`
# occurrences: 1 expected (verify: grep -c 'def test_control_files_include_advice' packages/ai-parrot/tests/sdd/test_procedure_guards.py)
# Add to the imports: os, shutil, subprocess, sys; import parrot.sdd; from parrot.sdd.scripts import procedure

def _pilot_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The end-to-end repository of the task's Implementation Notes, built with the PACKAGED manifest; cwd is its root."""
    # FILL IN


def _dangerous(root: Path, command: str) -> dict:
    """Output of the dangerous-actions hook for one Bash command run from ``root``."""
    # FILL IN: subprocess.run([sys.executable, "-m", "parrot.sdd.scripts.dangerous_actions", "--hook"], input=json.dumps(
    # _payload(root, command)), capture_output=True, text=True, cwd=root, env=<scrubbed env>); json.loads(stdout).


def test_pilot_flow_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """build -> next reports start; a hand `git mv` and a close of a pending task are denied by both guards;
    a close of an in-progress task with its dependencies done emits nothing."""
    root = _pilot_repo(tmp_path, monkeypatch)
    assert procedure.main(["build"]) == 0
    # FILL IN: the four assertions of the Implementation Notes, for both guards.
```

### `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "migrate_index": Scenario(prepare=_seed_feature, expect_exit=_ANY_CLEAN),' packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py)
# AFTER — insert below that line (verified: packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py:461), inside SCENARIOS
    # FEAT-891: the procedure graph; `check` may refuse cleanly, a traceback is never accepted
    "procedure": Scenario(
        prepare=_seed_feature,
        expect_exit=_ANY_CLEAN,
        placeholders={"<task.md>": "sdd/tasks/active/TASK-001-demo-task.md"},
    ),

# Append at the END of the file (after the last test function):
def test_wheel_only_procedure(managed_home: Path, tools_dir: Path, foreign_repo: tuple[Path, Path]) -> None:
    """FEAT-891: from the wheel alone, install deploys the SDD graph and builds the index; `check` and `next` run."""
    repo, _ = foreign_repo
    env = _env(managed_home, tools_dir)
    _install_all_hosts(repo, env)
    assert (repo / "sdd/procedures/sdd-workflow.yaml").is_file()
    assert (repo / ".parrot/procedure/procedures.json").is_file()
    for argv, expected in ((["check"], 0), (["next", "--no-remote"], 0), (["list"], 0)):
        result = subprocess.run(["parrot", "sdd", "procedure", *argv], cwd=repo, env=env, capture_output=True, text=True)
        assert result.returncode == expected, f"{argv}: {result.stdout[-400:]}\n{result.stderr[-600:]}"
        assert "Traceback" not in result.stderr, result.stderr[-600:]
```
**Why**: the scenario key is the helper module name (`procedure`), like every other entry. The
dedicated test asserts the install-built index exists, which the generic invocation loop does not.

### FILL IN checklist
- [ ] `test_procedure_guards.py` — `_pilot_repo`, `_dangerous`, and the four assertions for both guards
- [ ] Confirm the task file name `_seed_feature` writes (`test_wheel_only_foreign_repo.py:126-150`) and adjust the placeholder value if it differs

---

## Acceptance Criteria

- [ ] `test_pilot_flow_end_to_end` passes and uses the packaged manifest.
- [ ] `SCENARIOS` has a `procedure` entry.
- [ ] Acceptance run (not a validation command — it builds a wheel, several minutes):
      `pytest packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py -q` passes, including
      `test_wheel_only_procedure`.
- [ ] No production file is modified by this task.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_guards.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5644, TASK-5645, TASK-5646 and TASK-5648 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run `ruff check --fix` on the touched files, the Validation Commands, and the acceptance run.
6. Commit the code, then close with `parrot sdd task close TASK-5651 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5651
- Feature: procedural-graph-plane
- Implementation SHA: e95afcb29bb25de4bd5e95aa34e1622752392cc6
- Closed at (UTC): 2026-11-13T23:23:14+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 345.8s · Tokens: n/a |
