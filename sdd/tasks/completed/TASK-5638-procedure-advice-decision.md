# TASK-5638: Hook-side advice module — local probes and the guard decision

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5637
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (second half), §2 "Probes" and "Guard decision", and spec rev 0.3 decisions 6 and
7. This task adds the seven local probes, the shared check helper and `evaluate_command`, the
**only** place where the guard decision table lives. The two guards (TASK-5645, TASK-5646) only
render its result.

---

## Scope

- Add to `procedure_advice.py`: `LOCAL_PROBES`, `apply_check`, `evaluate_command`, the two public
  readers `feature_index` and `current_branch`, and their private helpers. Still stdlib only,
  still never raising.
- Implement the decision table, the three escape switches, the staleness check and the two text
  templates.
- Extend `tests/sdd/test_procedure_advice.py`.

**NOT in scope**: remote probes and `PROBE_COSTS` (TASK-5641); calling this from the guards
(TASK-5645, TASK-5646); the manifest (TASK-5647).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | MODIFY | Probes, `apply_check`, `evaluate_command` |
| `packages/ai-parrot/tests/sdd/test_procedure_advice.py` | MODIFY | Decision-table tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). Everything named `advice.*` below is created by TASK-5637 —
> re-read `procedure_advice.py` after it lands and correct this section if a name differs.

### Verified Imports
```python
# Standard library only. Add `import hashlib` and `from typing import Callable` to the module's imports.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py  (TASK-5637)
INDEX_SCHEMA_VERSION = 1; ESCAPE_ENV = "PARROT_ALLOW_PROCEDURE"; LAUNCHER_MARKERS = (...)
@dataclass(frozen=True)
class Advice: decision: Literal["none", "advise", "deny"]; text: str = ""
def checkout_root(cwd: Path) -> Path | None: ...
def shared_root(cwd: Path) -> Path | None: ...
def load_index(root: Path) -> dict[str, Any] | None: ...
def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]: ...   # each match has "argv"

# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py
ESCAPE_ENV = "PARROT_ALLOW_DANGEROUS"          # :26  (copy the literal; do not import)

# packages/ai-parrot/src/parrot/sdd/config.py
class SddConfig(BaseModel): hotfix_base: str = "main"   # :32  — read the raw JSON key here, never the model

# Per-spec index (sdd/tasks/index/<slug>.json): header keys "feature", "feature_id"; "tasks": [{"id", "status",
# "depends_on": [...]}]; status values: pending | in-progress | done | done-with-issues.
# Branch of a checkout without a subprocess: <git dir>/HEAD holds "ref: refs/heads/<branch>\n".
```

### Does NOT Exist
- ~~`parrot.sdd.config.load_sdd_config` usage here~~ — it imports pydantic; read
  `<root>/sdd/config.json` with `json`.
- ~~`SddConfig.procedure`~~ — added by TASK-5643; this module reads the raw `"procedure"` JSON key
  and treats a missing key as defaults (`enabled` true, `enforce` true).
- ~~A probe that runs `git` or `gh`~~ — remote probes are not in this module.
- ~~Honouring `PARROT_ALLOW_PROCEDURE=1` written inside the command text~~ — only the hook process
  environment counts, exactly like `PARROT_ALLOW_DANGEROUS`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_advice.py", "action": "MODIFY"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- **Two roots.** `root = shared_root(cwd)` is where the plane, the sources and `sdd/config.json` are
  read. `checkout = checkout_root(cwd)` is where task state is read (the per-spec index lives on
  the feature branch).
- **Probe signature**: `probe(checkout, scope, args) -> bool | None`; `None` means unknown. A probe
  never raises (wrap each call).

  | Probe | True when | Unknown when |
  |---|---|---|
  | `spec.exists` | `<checkout>/sdd/specs/<feature>.spec.md` is a file | no `feature` in scope |
  | `index.exists` | the per-spec index of `feature` is found | no `feature` in scope |
  | `task.status` | the task's `status` is one of `args["expect"].split("|")` | no index / task not found |
  | `task.depends_done` | every id in the task's `depends_on` has status `done` | no index / task not found |
  | `feature.tasks_done` | every task is `done` or `done-with-issues` | no index |
  | `flow.base_allowed` | not (`branch` starts with `feat-` or `fix-` and `base == hotfix_base`) | no `base` in scope, or branch unknown |
  | `env.not_worker_sandbox` | no `LAUNCHER_MARKERS` variable is set | never |

  Index lookup: try `<checkout>/sdd/tasks/index/<feature>.json`; otherwise scan
  `sdd/tasks/index/*.json` (skip `_orphans.json`) for a header whose `feature` or `feature_id`
  equals the value, or — when only `task` is in scope — a file listing that task id.
  `env.not_worker_sandbox` reads `scope["worker_sandbox"]` (`"1"`/`"0"`) when present, else
  `os.environ`.
- **`apply_check`** (rev 0.3 decision 6): when `expect` is a string, call the probe with
  `{**args, "expect": expect}` and return its value; when `expect` is a boolean, return
  `value == expect` (unknown stays unknown). An unregistered probe returns `None`.
- **Scope from a guard**: for each key of `guard["scope"]`, `{"argv": N}` takes the N-th element of
  the match's `argv` that does not start with `-`; `{"flag": "--base|-B"}` takes the value after
  any listed flag, in both `--flag value` and `--flag=value` forms. Missing values are simply
  absent from the scope. `evaluate_command` adds `branch` (from HEAD) and `worker_sandbox`.
- **Decision** for one matched guard on node `N` (`index["procedures"][guard["procedure"]]`), using
  only preconditions whose `"cost"` is `"local"`:

  | Node mode | Guard kind | Local preconditions | Result |
  |---|---|---|---|
  | mandatory | bypass | — | deny, reason "do not replace this procedure by hand" |
  | mandatory | entry | at least one is `False` | deny, reason lists the failed checks |
  | mandatory | entry | none `False`, at least one `None` | advise |
  | advisory | entry or bypass | any `False` or `None` (bypass: always) | advise |
  | any | any | all `True` | nothing |

  With several matches: any deny wins, else the first advise, else none.
- **Downgrade**: a deny becomes an advise when `env[ESCAPE_ENV] == "1"`,
  `env["PARROT_ALLOW_DANGEROUS"] == "1"`, or `procedure.enforce` is `false` in `sdd/config.json`.
- **Silence** (`Advice("none")`): no shared root, no index, `procedure.enabled` false, no match, a
  listed source missing or with a different sha1, or any exception. Hash the sources only after a
  guard matched.
- **Templates** (text truncated to 600 characters):
  - deny: `Procedure <id> is mandatory: <reason>. Use: <use_instead or command>. (Deliberate exception: ask the user to re-run with PARROT_ALLOW_PROCEDURE=1.)`
  - advise: `Procedure <id>: <unmet or unknown preconditions>. <advice>`
  A check is rendered as `<probe>` plus `=<expect>` when `expect` is a string, followed by
  ` (unknown)` when its value is `None`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the index/branch/config readers — *why*: every probe needs the same bounded reads.
2. Add `LOCAL_PROBES` and `apply_check` — *why*: `SddProbeRunner` (TASK-5641) reuses both, so the
   hook and the CLI cannot disagree.
3. Add `evaluate_command` — *why*: one decision table, in one function.
4. Add the tests.

### `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` (MODIFY)
```python
# Append AFTER the last function TASK-5637 wrote (`match_guards`); add `import hashlib` and `Callable`
# to the existing imports. Anchor (re-verify, must be unique): `def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:`
# occurrences: 1 expected (verify: grep -c 'def match_guards(' packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py)

Probe = Callable[[Path, Mapping[str, str], Mapping[str, str]], "bool | None"]
MAX_ADVICE_CHARS = 600


def _read_json(path: Path) -> Any:
    """Parsed JSON of ``path`` or None (missing, unreadable, larger than MAX_INDEX_BYTES)."""
    # FILL IN


def feature_index(checkout: Path, scope: Mapping[str, str]) -> dict[str, Any] | None:
    """The per-spec index for scope['feature'] (or the one listing scope['task']); None when not found.

    Public: ``procedure_probes.scope_for`` (TASK-5641) reuses it.
    """
    # FILL IN: per Implementation Notes "Index lookup".


def current_branch(checkout: Path) -> str | None:
    """Branch name read from HEAD of the checkout's git dir (worktree-aware); None when detached/unknown."""
    # FILL IN


def _settings(root: Path) -> dict[str, Any]:
    """{'enabled': bool, 'enforce': bool, 'hotfix_base': str} from <root>/sdd/config.json; defaults on any problem."""
    # FILL IN


# FILL IN: the seven probe functions `_probe_<name>(checkout, scope, args) -> bool | None`, exactly as the
# probe table in the Implementation Notes. `flow.base_allowed` reads args.get("hotfix_base", "main").

LOCAL_PROBES: dict[str, Probe] = {
    "spec.exists": _probe_spec_exists,
    "index.exists": _probe_index_exists,
    "task.status": _probe_task_status,
    "task.depends_done": _probe_task_depends_done,
    "feature.tasks_done": _probe_feature_tasks_done,
    "flow.base_allowed": _probe_flow_base_allowed,
    "env.not_worker_sandbox": _probe_env_not_worker_sandbox,
}


def apply_check(check: Mapping[str, Any], checkout: Path, scope: Mapping[str, str], *,
                probes: Mapping[str, Probe] | None = None) -> bool | None:
    """Whether one index-shaped check ``{"probe", "expect", "args"}`` holds: True, False or None (unknown).

    ``probes`` defaults to LOCAL_PROBES. Never raises.
    """
    # FILL IN: per Implementation Notes "apply_check".


def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:
    """The guard decision table for one Bash command (see the task's Implementation Notes).

    Returns Advice('none') whenever nothing can be decided safely; a deny is downgraded to
    'advise' by ESCAPE_ENV, PARROT_ALLOW_DANGEROUS or procedure.enforce = false.
    """
    try:
        env = os.environ if env is None else env
        # FILL IN: roots -> index -> settings.enabled -> match_guards -> staleness of listed sources ->
        # scope per match (+ branch, worker_sandbox, and args hotfix_base for flow.base_allowed) ->
        # decision per match -> combine -> downgrade -> render template -> truncate.
    except Exception:  # noqa: BLE001 — a hook helper never raises
        return Advice("none")
```
**Why this shape**: `LOCAL_PROBES`, `evaluate_command` and their signatures are fixed by spec §3 M5;
`apply_check` is the shared helper of rev 0.3 decision 6. The `hotfix_base` value is injected into
the check's `args` by `evaluate_command` so the probe stays a pure function of its three inputs.

### `packages/ai-parrot/tests/sdd/test_procedure_advice.py` (MODIFY)
```python
# Append at the end of the file TASK-5637 created. Anchor (re-verify): `def test_load_index_rejects_bad_files(tmp_path: Path) -> None:`
# occurrences: 1 expected (verify: grep -c 'def test_load_index_rejects_bad_files' packages/ai-parrot/tests/sdd/test_procedure_advice.py)

def _repo(tmp_path: Path, *, status: str = "in-progress", config: dict | None = None) -> Path:
    """A repo with .git/HEAD on branch feat-FEAT-1-demo, sdd/config.json, a source manifest file, a per-spec
    index (TASK-1 <status>, TASK-2 pending depends_on TASK-1) and a compiled procedures.json whose
    sources[].sha1 matches the manifest file. Guards/procedures: the §2 v1 table (task-close mandatory with
    entry + `git mv` bypass, pr-create mandatory entry with flow.base_allowed, push advisory)."""
    # FILL IN: write the files by hand with json.dumps / hashlib.sha1; return the root.


def test_guard_decision_table(tmp_path: Path) -> None:
    """Every row of the decision table, including unknown -> no deny."""
    # FILL IN: bypass -> deny naming `parrot sdd task close`; close of a pending task -> deny; close of an
    # in-progress task with deps done -> none; close with an unknown task id -> advise (never deny);
    # `gh pr create --base main` -> deny; `gh pr create -B main` -> deny; without --base -> not deny;
    # `git push` with a launcher marker in env -> advise.


@pytest.mark.parametrize("switch", ["PARROT_ALLOW_PROCEDURE", "PARROT_ALLOW_DANGEROUS", "enforce-false"])
def test_escape_downgrades_deny(tmp_path: Path, switch: str) -> None:
    """Each of the three switches turns a deny into an advisory."""
    # FILL IN


def test_stale_index_is_silent(tmp_path: Path) -> None:
    """A source sha1 mismatch (or a missing source) yields Advice('none')."""
    # FILL IN


def test_disabled_and_absent_plane_are_silent(tmp_path: Path) -> None:
    """procedure.enabled = false, and a repo with no plane, both yield Advice('none')."""
    # FILL IN


def test_apply_check_semantics(tmp_path: Path) -> None:
    """String expect goes to the probe as args['expect'] (with `|` alternatives); bool expect is compared."""
    # FILL IN
```

### FILL IN checklist
- [ ] `procedure_advice.py` — four readers, seven probes, `apply_check`, `evaluate_command`; bounded by the Implementation Notes tables
- [ ] `test_procedure_advice.py` — `_repo` and five test bodies
- [ ] Re-run `test_advice_stdlib_only` (TASK-5637): still no pydantic / yaml / sqlite3

---

## Acceptance Criteria

- [ ] Every row of the decision table behaves as specified; an unknown precondition never causes a denial.
- [ ] `PARROT_ALLOW_PROCEDURE=1`, `PARROT_ALLOW_DANGEROUS=1` and `procedure.enforce: false` each turn a denial into an advisory.
- [ ] Absent plane, stale plane, `procedure.enabled: false` and any internal error return `Advice("none")`.
- [ ] `gh pr create --base main` (and `-B main`) on a `feat-*` branch is denied; without `--base` it is not.
- [ ] The module is still stdlib-only and has no `main()`.
- [ ] Advice text is at most 600 characters.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_advice.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5637 is `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`; never change a signature the blueprint fixes.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5638 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note


- Task: TASK-5638
- Feature: procedural-graph-plane
- Implementation SHA: 8f749cc587fa1021c0bb68f0c0e6a511a5d16920
- Closed at (UTC): 2026-11-13T22:07:17+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-luna · Backend: codex · Model: gpt-5.6-luna · Attempts: 1 · Duration: 420.6s · Tokens: n/a |
