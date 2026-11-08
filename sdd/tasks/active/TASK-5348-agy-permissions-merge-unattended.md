# TASK-5348: Merge `agy_verdict` into the AGY permission hook, file tools and unattended mode

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5347
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `agy_permissions.evaluate` (PR #2040, on `dev`) is the single entry point of the
`parrot-sdd-permissions` hook. Today it returns a neutral `ask` for every tool other than `run_command`
(so `write_file`/`edit_file` pass unchecked), it cannot rewrite commands, and its `force_ask` answers do not
stop anything under `--dangerously-skip-permissions` (verified on agy 1.5.3). This task:
- merges `worktree_environment.agy_verdict()` (TASK-5347) into `evaluate` (`deny` > `force_ask` > `ask`),
- adds `overwrite` to `Decision`/`_render`,
- adds the unattended mode (`PARROT_SDD_AGY_UNATTENDED=1`): every `force_ask` becomes `deny` (reason prefixed
  `unattended:`), including parse failures, malformed payloads and the `scripts/sdd/agy_hook.sh` fallback.

---

## Scope

- `agy_permissions.py`: `UNATTENDED_ENV`; `Decision.overwrite`; `evaluate` handles `write_file`/`edit_file`
  through `agy_verdict` and merges `agy_verdict` into `run_command` decisions; unattended mapping;
  `_render` emits `overwrite` for non-deny results; `main` failure answer is `deny` in unattended mode.
- `scripts/sdd/agy_hook.sh`: `unavailable()` answers `deny` (reason prefixed `unattended:`) when
  `PARROT_SDD_AGY_UNATTENDED=1`, `force_ask` otherwise.
- Tests in `test_agy_permissions.py`.

**NOT in scope**: the installer and the tracked `.agents/hooks.json` matcher (TASK-5349); the launcher that
exports the variable (TASK-5351…5354); changing PR #2040's command policy or allow-rules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py` | MODIFY | `UNATTENDED_ENV`, `Decision.overwrite`, merge + file tools + unattended in `evaluate`/`_render`/`main` |
| `scripts/sdd/agy_hook.sh` | MODIFY | unattended fallback answers `deny` |
| `packages/ai-parrot/tests/sdd/test_agy_permissions.py` | MODIFY | merge, overwrite, file-tool, unattended and launcher-fallback tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09), after the PR #2040 merge (`b0d8602a2e`).

### Verified Imports
```python
# agy_permissions.py, lines 28-40 (module imports): argparse, glob, json, os, re, shlex, sys,
#   dataclasses.dataclass/field, pathlib.Path, typing.Any/Literal/Sequence, and
from parrot.sdd.scripts import dangerous_actions            # line 40
# ADD next to it (same sibling-import pattern, spec §7):
from parrot.sdd.scripts import worktree_environment          # agy_verdict from TASK-5347
# tests (test_agy_permissions.py:20-28):
from parrot.sdd.scripts import agy_permissions
from parrot.sdd.scripts.agy_permissions import GIT_SUBCOMMANDS, SDD_ALLOW_RULES, Decision, evaluate, rule_covers, workspace_roots
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py
@dataclass(frozen=True)
class Decision:                                              # line 119
    decision: Literal["deny", "force_ask", "ask"]            # line 122
    reason: str = ""                                         # line 123
_ASK = Decision("ask")                                       # line 126
def workspace_roots(workspace_paths: Sequence[str], fallback: Path | None) -> list[Path]:   # line 519
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Decision:                    # line 1358
    #   returns _ASK when toolCall is not a dict or name != "run_command" (line 1373), or CommandLine empty (line 1378)
    #   then dangerous_actions deny -> parse failure force_ask -> ctx.deny -> risks force_ask -> _ASK
def _render(decision: Decision) -> dict[str, str]:                                           # line 1414
def main(argv: Sequence[str] | None = None) -> None:                                         # line 1421
    #   failure branch (lines 1433-1438, `"decision": "force_ask"` at 1435): {"decision": "force_ask", "reason": "agy-permissions: checks failed (...)"}
# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py (TASK-5347)
def agy_verdict(payload: dict[str, Any], *, root: Path, backend: str, unattended: bool
                ) -> tuple[Literal["deny", "ask"], str, dict[str, str] | None]:
# scripts/sdd/agy_hook.sh — line 7-10:
#   unavailable() {
#       printf '%s\n' "{\"decision\": \"force_ask\", \"reason\": \"agy permission hook unavailable ($1); confirm each command\"}"
#       exit 0
#   }
# packages/ai-parrot/tests/sdd/test_agy_permissions.py
def ws(tmp_path: Path) -> Path:                              # line 43 fixture (git repo on branch fix-x)
def _payload(command: str, workspace: Path, **args: str) -> dict:   # line 48
def _decide(command: str, workspace: Path, **args: str) -> Decision: # line 57
def _run_hook(stdin: str) -> subprocess.CompletedProcess[str]:      # line 431
REPO_ROOT = Path(__file__).resolve().parents[4]              # line 481
LAUNCHER = REPO_ROOT / "scripts" / "sdd" / "agy_hook.sh"     # line 482
def test_other_payloads_are_neutral(payload: dict) -> None:   # line 422 — must keep passing (view_file, empty run_command, non-dict toolCall, {})
def test_cwd_argument_outside_workspace(ws: Path, tmp_path: Path) -> None:  # line 384 — must keep "force_ask" / "ask"
```

### Does NOT Exist
- ~~`Decision.overwrite`, `UNATTENDED_ENV`~~ — created here.
- ~~An `allow` answer from `agy_permissions`~~ — PR #2040 never answers `allow`; keep it that way.
- ~~`worktree_environment.agy_verdict` reading the environment~~ — this task reads `UNATTENDED_ENV` and `PARROT_SDD_SANDBOX_BACKEND` and passes them in.
- ~~A second named hook~~ — FEAT-847 extends the single `parrot-sdd-permissions` hook.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py", "action": "MODIFY"},
    {"path": "scripts/sdd/agy_hook.sh", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_agy_permissions.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py#Decision",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py#evaluate",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py#_render",
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py#main"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Merge rule (spec §3 M1): `deny` beats `force_ask`, which beats `ask`; `overwrite` is carried only when the
  merged result is not `deny`. When both sides deny, keep the first non-empty reason.
- Unattended mapping is applied **last** (after merging), so every `force_ask` source is covered.
- `PARROT_ALLOW_DANGEROUS=1` keeps its PR #2040 meaning (returns `ask`); do not add an unattended exception to it.
- Do not run `agy_verdict` when there is nothing to judge (empty `CommandLine`, non-dict `toolCall`, other
  tools such as `view_file`) — `test_other_payloads_are_neutral` must still pass.
- `root` may be `None`; for a file tool or a non-empty `run_command`, `None` cannot be validated → `deny`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the import, `UNATTENDED_ENV`, the `overwrite` field and the rank table — *why*: the spec §2 interface.
2. Rename the current `evaluate` body to `_policy(payload, *, root)` unchanged, and write a new `evaluate` around it — *why*: keeps PR #2040's tested policy intact and adds the merge in one place.
3. Update `_render` and the `main` failure branch — *why*: overwrite + unattended rendering.
4. Patch `unavailable()` in `agy_hook.sh` — *why*: the launcher fallback is a `force_ask` source too.
5. Write the tests.

### `packages/ai-parrot/src/parrot/sdd/scripts/agy_permissions.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.sdd.scripts import dangerous_actions' agy_permissions.py) — line 40
# AFTER — insert below it:
from parrot.sdd.scripts import worktree_environment

UNATTENDED_ENV = "PARROT_SDD_AGY_UNATTENDED"
_RANK = {"ask": 0, "force_ask": 1, "deny": 2}

# occurrences: 1 (verified: grep -c '    reason: str = ""' agy_permissions.py) — line 123, inside class Decision
# AFTER — insert below `    reason: str = ""`:
    overwrite: dict[str, str] | None = None

# occurrences: 1 (verified: grep -c 'def evaluate(payload: dict\[str, Any\], \*, root: Path | None) -> Decision:') — line 1358
# REPLACE the `def evaluate(...)` line with `def _policy(payload: dict[str, Any], *, root: Path | None) -> Decision:`
#   (body unchanged; adjust its docstring first line to "PR #2040 command policy for one run_command payload."),
# then INSERT this new evaluate directly above `def _policy(`:
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Decision:
    """Policy + dangerous-actions + agy_verdict; deny > force_ask > ask; unattended maps force_ask to deny."""
    unattended = os.environ.get(UNATTENDED_ENV) == "1"
    call = payload.get("toolCall")
    name = call.get("name") if isinstance(call, dict) else None
    if os.environ.get(dangerous_actions.ESCAPE_ENV) == "1":
        return _ASK
    if name in worktree_environment.AGY_FILE_TOOLS:
        decision = _verdict(payload, root=root, unattended=unattended)
    else:
        decision = _policy(payload, root=root)
        # FILL IN: when name == "run_command" and args.CommandLine is a non-empty str, merge with
        #   _verdict(payload, root=root, unattended=unattended) via _merge — bounded by spec §3 M1 merge rule and
        #   test_other_payloads_are_neutral (no verdict for empty/absent commands).
    return _unattended(decision) if unattended else decision


def _verdict(payload: dict[str, Any], *, root: Path | None, unattended: bool) -> Decision:
    """The worktree-environment verdict as a Decision (a None root cannot be validated: deny)."""
    if root is None:
        return Decision("deny", "agy-permissions: no checkout root for this workspace")
    backend = os.environ.get("PARROT_SDD_SANDBOX_BACKEND", "")
    decision, reason, overwrite = worktree_environment.agy_verdict(
        payload, root=root, backend=backend, unattended=unattended
    )
    return Decision(decision, reason, overwrite)


def _merge(policy: Decision, verdict: Decision) -> Decision:
    """deny > force_ask > ask; the overwrite survives only a non-deny result."""
    # FILL IN: pick the higher _RANK decision (ties keep `policy`), reason = first non-empty of the winner's then the
    #   other's, overwrite = verdict.overwrite unless the result is "deny" — bounded by spec §3 M1.
    return policy


def _unattended(decision: Decision) -> Decision:
    """Unattended mode: force_ask runs under --dangerously-skip-permissions, so it becomes deny."""
    if decision.decision != "force_ask":
        return decision
    return Decision("deny", f"unattended: {decision.reason}".rstrip())

# occurrences: 1 (verified: grep -c 'def _render(decision: Decision) -> dict\[str, str\]:') — line 1414
# REPLACE `_render` with:
def _render(decision: Decision) -> dict[str, Any]:
    out: dict[str, Any] = {"decision": decision.decision}
    if decision.reason:
        out["reason"] = decision.reason
    if decision.overwrite and decision.decision != "deny":
        out["overwrite"] = dict(decision.overwrite)
    return out

# In main(), failure branch (lines 1433-1438, `"decision": "force_ask"` at 1435): FILL IN — when os.environ.get(UNATTENDED_ENV) == "1" write
#   {"decision": "deny", "reason": "unattended: agy-permissions: checks failed (...)"}; else keep the force_ask text
#   unchanged — bounded by spec §4 "hook main error path ... force_ask, or deny in unattended mode".
```
**Why this shape**: renaming the PR #2040 body to `_policy` keeps every existing policy test meaningful,
while the new `evaluate` is the single place where sources combine — the spec forbids relying on AGY to merge
answers from several hooks.

### `scripts/sdd/agy_hook.sh` (MODIFY)
```sh
# occurrences: 1 (verified: grep -c 'unavailable() {' scripts/sdd/agy_hook.sh) — line 7
# REPLACE the body of unavailable() (lines 8-9) with:
unavailable() {
    if [ "${PARROT_SDD_AGY_UNATTENDED:-}" = "1" ]; then
        printf '%s\n' "{\"decision\": \"deny\", \"reason\": \"unattended: agy permission hook unavailable ($1)\"}"
    else
        printf '%s\n' "{\"decision\": \"force_ask\", \"reason\": \"agy permission hook unavailable ($1); confirm each command\"}"
    fi
    exit 0
}
# Also update the header comment (lines 5-6) to mention the unattended deny.
```

### `packages/ai-parrot/tests/sdd/test_agy_permissions.py` (MODIFY)
```python
# AFTER — append at end of file
@pytest.fixture
def unattended(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(agy_permissions.UNATTENDED_ENV, "1")


def test_agy_permissions_unattended_force_ask_is_deny(ws: Path, unattended: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agy_permissions.worktree_environment.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setenv("PARROT_SDD_SANDBOX_BACKEND", "bubblewrap")
    decision = _decide("cat 'unterminated", ws)
    assert decision.decision == "deny" and decision.reason.startswith("unattended:")


# FILL IN tests (one function each):
#  - same payload without the variable -> "force_ask" (unchanged PR #2040 behaviour)
#  - test_agy_permissions_merge_and_overwrite: in a ws with packages/core/src, "git status" -> ask with an
#    overwrite whose CommandLine starts with "PYTHONPATH="; "uv sync" -> deny without overwrite; a policy
#    force_ask command keeps the verdict overwrite; _render({deny + overwrite}) has no "overwrite" key
#  - test_agy_permissions_file_tools: write_file {Path, Content, Overwrite} inside ws -> ask; outside / "../x" /
#    symlink escape / shared env -> deny; edit_file without Path -> deny; root=None -> deny
#  - unattended + bubblewrap: a routine command's overwrite contains "bwrap"; with which -> None -> deny
#  - main error path: _run_hook("not json") with UNATTENDED_ENV=1 in env -> {"decision": "deny", ...}
#    (one JSON object, never {} or hookSpecificOutput); without it -> force_ask (existing test)
#  - test_agy_hook_sh_unattended_fallback: copy LAUNCHER outside a checkout (like
#    test_launcher_outside_a_checkout_asks_for_every_command) and run with PARROT_SDD_AGY_UNATTENDED=1 -> "deny",
#    reason starts with "unattended:"; without it -> "force_ask"
```

### FILL IN checklist
- [ ] new `evaluate` — run_command merge guard; bounded by spec §3 M1 + `test_other_payloads_are_neutral`
- [ ] `_merge` — rank/reason/overwrite rule; bounded by spec §3 M1
- [ ] `main` unattended failure answer; bounded by spec §4
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] `evaluate` merges policy, dangerous-actions and `agy_verdict` (`deny` > `force_ask` > `ask`) and checks `write_file`/`edit_file`.
- [ ] `_render` emits `overwrite` only for non-deny results; the hook still prints exactly one JSON object with `decision`.
- [ ] With `PARROT_SDD_AGY_UNATTENDED=1` no path answers `force_ask` (policy, parse failure, malformed payload, `agy_hook.sh` fallback).
- [ ] All pre-existing tests in `test_agy_permissions.py` still pass, except the tracked-matcher assertion that TASK-5349 updates (it must still pass here: the matcher is unchanged in this task).
- [ ] `ruff check` is clean on the Python files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_agy_permissions.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint; each `FILL IN` bullet is one test function reusing `ws`,
`_payload`, `_decide`, `_run_hook` and `LAUNCHER`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5348 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
