# TASK-5648: `parrot sdd install` builds the procedure index

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5643, TASK-5647
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (install half), goal G7 and spec rev 0.3 decision 3. After the assets are
deployed, the installer builds the plane so the guards work right after an install. The install is
plan-driven: a step exists only if `plan_install` lists it. A build failure never fails the
install.

---

## Scope

- Add the plan action `"procedure-index"`: the `PlanAction` literal, one `PlannedAction` at the end
  of `plan_install`, the `_install_procedure_index_step` function and its `elif` branch in
  `install_sdd_integration`.
- Add the install tests to `tests/sdd/test_procedure_assets.py`.

**NOT in scope**: uninstall (the plane lives under the git-ignored `.parrot/`; nothing is recorded
in the receipt), the manifest content, the guard registration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | New plan action and its step |
| `packages/ai-parrot/tests/sdd/test_procedure_assets.py` | MODIFY | Install tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). `procedure.build` comes from TASK-5643; the manifest asset
> from TASK-5647.

### Verified Imports
```python
from parrot.sdd.installer import install_sdd_integration, plan_install     # sdd/installer.py:1515, :896
# inside the new step only (lazy): import asyncio; from parrot.sdd.scripts import procedure
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/installer.py
PlanAction = Literal[                                                    # :146
    ...
    "toolkits",                                                          # :165
    "toolkits-remove",
    ...
]
def plan_install(root: Path, hosts: Sequence[str], *, keep_edits: bool = False, hook: str = GUARD_HOOK_LINE,
                 base_branch: str | None = None, dangerous_guard: bool = True, sdd_coder: bool = True,
                 agy_permissions: bool = True) -> list[PlannedAction]:   # :896
    ...
    if sdd_coder:
        plan.append(PlannedAction(action="toolkits", target=", ".join(SDD_TOOLKITS)))  # C34   # :949
    return plan                                                          # :950
def _install_ledger_hooks_step(root: Path, receipt: dict[str, Any]) -> list[str]: ...   # :1282 — the step shape to copy (lazy imports, returns action lines)
def install_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",), *, keep_edits: bool = False,
                            dry_run: bool = False, portable: bool | None = None, base_branch: str | None = None,
                            push_base: bool = False, hotfix_base: str | None = None, dangerous_guard: bool = True,
                            sdd_coder: bool = True, agy_permissions: bool = True) -> list[str]:   # :1515
    ...
    if dry_run:
        return [str(step) for step in plan]                              # :1598-:1599
    ...
        elif step.action == "toolkits":                                  # :1622
            actions.extend(_install_toolkits_step(root, hosts, receipt, portable=portable))   # :1623
    _save_receipt(root, receipt)                                         # :1624

# packages/ai-parrot/src/parrot/sdd/scripts/procedure.py  (TASK-5643)
async def build(root: Path) -> dict[str, int]      # {'pages', 'edges', 'sources'}; raises ValueError on graph errors

# packages/ai-parrot/tests/sdd/test_sdd_cli.py
def test_install_status_uninstall_roundtrip(tmp_path: Path) -> None: ...   # :21 — how a tmp repo is prepared and installed in tests
```

### Does NOT Exist
- ~~A `"procedure-index"` plan action~~ — this task adds it.
- ~~A receipt entry for the plane~~ — none; the plane is derived and git-ignored.
- ~~A module-level import of `parrot.sdd.scripts.procedure` or `asyncio` in `installer.py`~~ — keep
  both inside the step function.
- ~~A raised exception from the step~~ — it returns `procedure index: skipped (<reason>)`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_procedure_assets.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#plan_install",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_ledger_hooks_step"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- The step is planned for **every** host set and is the **last** plan entry, so the manifest asset
  is already deployed when it runs.
- FEAT-887 (not merged) also edits `installer.py`; if it landed first, re-locate the anchors and
  keep its changes.
- `asyncio.run` raises `RuntimeError` inside a running event loop; the `except Exception` turns
  that into the `skipped` line, which is the intended behavior.
- Update the plan-vocabulary comment at `installer.py:141-145` to name the new action.

---

## Implementation Blueprint

### Steps (in order)
1. Add the literal — *why*: `PlannedAction.action` is typed by it.
2. Add the plan entry, the step function and the `elif` — *why*: a step that is not planned never
   runs and is invisible in `--dry-run`.
3. Add the tests.

### `packages/ai-parrot/src/parrot/sdd/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "toolkits",' packages/ai-parrot/src/parrot/sdd/installer.py)
# AFTER — insert below `    "toolkits",` (verified: packages/ai-parrot/src/parrot/sdd/installer.py:165), inside the PlanAction Literal
    "procedure-index",

# occurrences: 1 (verified: grep -c '        plan.append(PlannedAction(action="toolkits", target=", ".join(SDD_TOOLKITS)))  # C34' packages/ai-parrot/src/parrot/sdd/installer.py)
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/sdd/installer.py:949), DEDENTED to the function body level
# (outside the `if sdd_coder:` block), before `    return plan`:
    plan.append(PlannedAction(action="procedure-index", target=".parrot/procedure/procedures.json"))  # FEAT-891

# occurrences: 1 (verified: grep -c 'def _install_ledger_hooks_step(root: Path, receipt: dict\[str, Any\]) -> list\[str\]:' packages/ai-parrot/src/parrot/sdd/installer.py)
# BEFORE — insert above `def _install_ledger_hooks_step(root: Path, receipt: dict[str, Any]) -> list[str]:` (verified: packages/ai-parrot/src/parrot/sdd/installer.py:1282)
def _install_procedure_index_step(root: Path, receipt: dict[str, Any]) -> list[str]:
    """FEAT-891: build the procedure plane from the deployed manifests; return a one-line action.

    Never fails the install: an error becomes the action text ``procedure index: skipped (<reason>)``.
    ``receipt`` is unused — the plane is derived state under the git-ignored ``.parrot/``.
    """
    try:
        import asyncio

        from parrot.sdd.scripts import procedure

        counts = asyncio.run(procedure.build(root))
    except Exception as exc:  # noqa: BLE001 — a derived index must never block an install
        return [f"procedure index: skipped ({type(exc).__name__}: {exc})"]
    return [f".parrot/procedure/procedures.json — built ({counts['pages']} procedures)"]


# occurrences: 1 (verified: grep -c '            actions.extend(_install_toolkits_step(root, hosts, receipt, portable=portable))' packages/ai-parrot/src/parrot/sdd/installer.py)
# AFTER — insert below that line (verified: packages/ai-parrot/src/parrot/sdd/installer.py:1623), as the next branch of the same if/elif chain
        elif step.action == "procedure-index":
            actions.extend(_install_procedure_index_step(root, receipt))
```
**Why**: the function name and its never-fail contract are fixed by spec §3 M9. Planning it last
is what guarantees the manifest is on disk.

### `packages/ai-parrot/tests/sdd/test_procedure_assets.py` (MODIFY)
```python
# Append at the end of the file TASK-5647 created. Anchor (re-verify): `def test_asset_manifest_lists_the_graph() -> None:`
# occurrences: 1 expected (verify: grep -c 'def test_asset_manifest_lists_the_graph' packages/ai-parrot/tests/sdd/test_procedure_assets.py)
# Add: from parrot.sdd.installer import install_sdd_integration, plan_install; from parrot.sdd.scripts import procedure

def _git_repo(tmp_path: Path) -> Path:
    """An initialized git repository the installer accepts (copy the setup of
    packages/ai-parrot/tests/sdd/test_sdd_cli.py::test_install_status_uninstall_roundtrip)."""
    # FILL IN


def test_install_plans_and_builds_index(tmp_path: Path) -> None:
    """The plan ends with procedure-index; install leaves a fresh procedures.json listing the SDD nodes."""
    # FILL IN: plan_install(root, ["claude"])[-1].action == "procedure-index"; run install_sdd_integration with
    # dangerous_guard=False, sdd_coder=False, agy_permissions=False; assert the index exists, its "procedures"
    # has "sdd:task-close", and one action line starts with ".parrot/procedure/procedures.json — built".


def test_install_survives_a_build_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing build does not fail the install; the action says it was skipped."""
    # FILL IN: monkeypatch.setattr(procedure, "build", <async function raising ValueError("boom")>);
    # install returns normally and an action starts with "procedure index: skipped (ValueError: boom".


def test_dry_run_lists_the_step_and_writes_nothing(tmp_path: Path) -> None:
    """--dry-run names the step and creates no plane."""
    # FILL IN
```

### FILL IN checklist
- [ ] `test_procedure_assets.py` — `_git_repo` and three test bodies
- [ ] The plan-vocabulary comment near `installer.py:141` names `procedure-index`

---

## Acceptance Criteria

- [ ] `parrot sdd install` deploys the manifest and leaves a fresh `procedures.json`.
- [ ] A build failure does not fail the install and is reported as `procedure index: skipped (…)`.
- [ ] `--dry-run` lists the `procedure-index` step and writes nothing.
- [ ] No hook registration is added; the settings entries written by the installer are unchanged.
- [ ] `installer.py` imports `asyncio` and `parrot.sdd.scripts.procedure` only inside the step.

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_procedure_assets.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5643 and TASK-5647 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5648 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
