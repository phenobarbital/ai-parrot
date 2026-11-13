# TASK-5642: Lint pack `procedure`

**Feature**: FEAT-891 — Procedural Graph Plane
**Spec**: `sdd/specs/procedural-graph-plane.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5635, TASK-5636, TASK-5641
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (lint half), goal G6 and spec rev 0.3 decision 4. `wikitoolkit lint` gains one
rule that runs the graph validator over the repository's procedure manifests. The rule is a no-op
in a repository without manifests, so every existing lint run is unchanged.

---

## Scope

- Create `packs/procedure.py` with `ProcedureGraphRule` and `PROCEDURE_RULES`.
- Register the pack in `default_rules`.
- Add the lint tests to `test_validate.py`.

**NOT in scope**: `uncovered-command` (it needs the packaged command list; only the CLI `check`
verb passes `known_commands`), any fix (`fix()` returns `None`), the validator itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/procedure.py` | CREATE | The rule |
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` | MODIFY | Add the pack to `default_rules` |
| `packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py` | MODIFY | Two lint tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `9a3a611b0c` (dev). `manifest_specs` (TASK-5635), `validate_graph` (TASK-5636)
> and `PROBE_COSTS` (TASK-5641) are dependency-provided — re-check them after they land.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, Severity      # lint/models.py:14, :26, :10
from parrot.knowledge.lint.rule import make_fingerprint                    # lint/rule.py:15
from parrot.knowledge.lint.context import LintContext                      # lint/context.py:13 (TYPE_CHECKING only)
from parrot.knowledge.wiki.procedure.producers import MANIFEST_DIR, manifest_specs   # TASK-5635 (lazy, inside check)
from parrot.knowledge.wiki.procedure.validate import validate_graph                  # TASK-5636 (lazy, inside check)
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS                          # TASK-5641 (lazy, inside check)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/lint/rule.py
def make_fingerprint(rule_id: str, subjects: Sequence[str]) -> str: ...     # :15
class LintRule(Protocol):                                                   # :22
    rule_id: str; pack: str; default_severity: Severity
    async def check(self, ctx: "LintContext") -> list[Finding]: ...         # :29 — MUST NOT mutate the store
    async def fix(self, ctx: "LintContext", finding: Finding) -> FixResult | None: ...   # :33

# packages/ai-parrot/src/parrot/knowledge/lint/models.py
class Finding(BaseModel):                                                   # :14
    rule_id: str; severity: Severity; subjects: list[str]; message: str
    fixable: bool = False; fingerprint: str; data: dict[str, Any]

# packages/ai-parrot/src/parrot/knowledge/lint/context.py
class LintContext:                                                          # :13
    root: Path | None      # the project root, or None

# packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py
def default_rules(options: "LintOptions") -> list["LintRule"]:              # :12
    from parrot.knowledge.lint.packs.plane_fix import PLANE_FIX_RULES       # :18
    rules: list[LintRule] = [
        cls() for cls in (*PLANE_RULES, *PLANE_FIX_RULES, *EXPORT_RULES, *ADR_RULES, *MEMORY_RULES)   # :21
    ]
```

### Does NOT Exist
- ~~`parrot.knowledge.lint.packs.procedure`~~ — this task creates it.
- ~~A module-level import of `parrot.sdd` or of the procedure package in the pack~~ — import them
  inside `check()`, so `default_rules` stays cheap for repositories without manifests.
- ~~A `fixable` finding~~ — this rule never fixes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/procedure.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/lint/rule.py#LintRule",
    "sym:packages/ai-parrot/src/parrot/knowledge/lint/rule.py#make_fingerprint",
    "sym:packages/ai-parrot/src/parrot/knowledge/lint/models.py#Finding",
    "sym:packages/ai-parrot/src/parrot/knowledge/lint/context.py#LintContext",
    "sym:packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py#default_rules"
  ]
}
```

---

## Implementation Notes

- In a worktree prefix tests with `PYTHONPATH=packages/ai-parrot/src`.
- `packages/ai-parrot/tests/knowledge/lint/test_default_rules.py` checks only that some rule ids
  are present; it needs no change, but run it.
- A manifest that fails to load (`ValueError` from `manifest_specs`) becomes one `error` finding
  with subject `sdd/procedures` and the exception text; it must not raise out of `check()`.

---

## Implementation Blueprint

### Steps (in order)
1. Write the rule — *why*: plain class satisfying the `LintRule` protocol, like the other packs.
2. Register it — *why*: `default_rules` is the only place rules are instantiated.
3. Add the tests.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/procedure.py` (CREATE)
```python
"""Lint pack `procedure`: graph checks over sdd/procedures manifests (FEAT-891)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from parrot.knowledge.lint.models import Finding, FixResult, Severity
from parrot.knowledge.lint.rule import make_fingerprint

if TYPE_CHECKING:
    from parrot.knowledge.lint.context import LintContext


class ProcedureGraphRule:
    """Report broken edges, requires-cycles, unknown probes and the other graph errors."""

    rule_id = "procedure-graph"
    pack = "procedure"
    default_severity: Severity = "error"

    async def check(self, ctx: "LintContext") -> list[Finding]:
        """One Finding per GraphFinding; [] when the project has no procedure manifest."""
        root = ctx.root
        if root is None:
            return []
        from parrot.knowledge.wiki.procedure.producers import MANIFEST_DIR, manifest_specs

        if not any((root / MANIFEST_DIR).glob("*.yaml")):
            return []
        from parrot.knowledge.wiki.procedure.validate import validate_graph
        from parrot.sdd.scripts.procedure_probes import PROBE_COSTS

        try:
            specs, _sources = manifest_specs(root)
        except ValueError as exc:
            subjects = [MANIFEST_DIR.as_posix()]
            return [Finding(rule_id=self.rule_id, severity="error", subjects=subjects, message=str(exc),
                            fingerprint=make_fingerprint(self.rule_id, ["load", *subjects]))]
        return [
            Finding(
                rule_id=self.rule_id,
                severity=finding.severity,
                subjects=finding.subjects,
                message=f"{finding.code}: {finding.message}",
                fingerprint=make_fingerprint(self.rule_id, [finding.code, *finding.subjects]),
                data={"code": finding.code},
            )
            for finding in validate_graph(specs, known_probes=PROBE_COSTS)
        ]

    async def fix(self, ctx: "LintContext", finding: Finding) -> FixResult | None:
        """This rule never fixes."""
        return None


PROCEDURE_RULES: tuple[type, ...] = (ProcedureGraphRule,)
```
**Why this shape**: `rule_id`, `pack` and `default_severity` are fixed by spec §3 M3. The
fingerprint includes the finding code so two different problems on the same node stay distinct.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    from parrot.knowledge.lint.packs.plane_fix import PLANE_FIX_RULES' packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py)
# AFTER — insert below `    from parrot.knowledge.lint.packs.plane_fix import PLANE_FIX_RULES` (verified: packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py:18)
    from parrot.knowledge.lint.packs.procedure import PROCEDURE_RULES

# occurrences: 1 (verified: grep -c '        cls() for cls in (\*PLANE_RULES, \*PLANE_FIX_RULES, \*EXPORT_RULES, \*ADR_RULES, \*MEMORY_RULES)' packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py)
# REPLACE the line `        cls() for cls in (*PLANE_RULES, *PLANE_FIX_RULES, *EXPORT_RULES, *ADR_RULES, *MEMORY_RULES)`
# (verified: packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py:21) with:
        cls()
        for cls in (*PLANE_RULES, *PLANE_FIX_RULES, *EXPORT_RULES, *ADR_RULES, *MEMORY_RULES, *PROCEDURE_RULES)
```
**Why**: the pack module itself imports nothing heavy, so listing it unconditionally is cheap.

### `packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py` (MODIFY)
```python
# Append at the end of the file TASK-5636 created. Anchor (re-verify): `def test_findings_sorted_and_stable() -> None:`
# occurrences: 1 expected (verify: grep -c 'def test_findings_sorted_and_stable' packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py)
# Add: from pathlib import Path; from types import SimpleNamespace;
#      from parrot.knowledge.lint.models import LintOptions; from parrot.knowledge.lint.packs import default_rules;
#      from parrot.knowledge.lint.packs.procedure import ProcedureGraphRule

async def test_lint_rule_noop_without_manifest(tmp_path: Path) -> None:
    """ProcedureGraphRule.check returns [] with no root and with a root that has no manifest."""
    rule = ProcedureGraphRule()
    assert await rule.check(SimpleNamespace(root=None)) == []
    assert await rule.check(SimpleNamespace(root=tmp_path)) == []


async def test_lint_rule_reports_graph_errors(tmp_path: Path) -> None:
    """A manifest with a broken edge and an unknown probe yields error findings; a bad file yields one."""
    # FILL IN: write sdd/procedures/x.yaml (graph: sdd; one node with next: [missing] and a precondition
    # probe "nope"); assert the finding data codes include "broken-edge" and "unknown-probe", every
    # fingerprint is unique, and fix() returns None. Then write an invalid YAML manifest -> one finding.


def test_procedure_rule_is_a_default_rule() -> None:
    """default_rules includes the procedure pack."""
    assert "procedure-graph" in {rule.rule_id for rule in default_rules(LintOptions())}
```

### FILL IN checklist
- [ ] `test_validate.py::test_lint_rule_reports_graph_errors` — bounded by its docstring
- [ ] Use the same async test marking the file's sibling tests use (check `pytest.ini` / `pyproject.toml` `asyncio_mode`)

---

## Acceptance Criteria

- [ ] `ProcedureGraphRule.check` returns `[]` when `ctx.root` is `None` or no manifest exists.
- [ ] With a manifest, it returns one finding per `GraphFinding`, with stable, distinct fingerprints.
- [ ] `default_rules(LintOptions())` contains `procedure-graph`.
- [ ] `packs/procedure.py` imports the procedure package and `parrot.sdd` only inside `check()`.
- [ ] `pytest packages/ai-parrot/tests/knowledge/lint/test_default_rules.py -q` still passes (acceptance run; not a validation command).

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug procedural-graph-plane --feature-id FEAT-891`), never on `dev`.
2. Check TASK-5635, TASK-5636 and TASK-5641 are `done` in `sdd/tasks/index/procedural-graph-plane.json`.
3. Verify the Codebase Contract before writing code; if an entry is stale, fix it in this file first.
4. Implement only the files listed above; complete every `FILL IN`.
5. Run `ruff check --fix` on the touched files and the Validation Commands.
6. Commit the code, then close with `parrot sdd task close TASK-5642 procedural-graph-plane verified` and fill in the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*
