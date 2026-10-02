# TASK-4019: default_rules() + LLMWikiToolkit.lint adapter + WikiLintReport alias

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4010, TASK-4012, TASK-4013, TASK-4014, TASK-4015, TASK-4016, TASK-4017, TASK-4018
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (Python adapter half). Wires every pack and makes `fix` real in the toolkit.

---

## Scope

- `lint/packs/__init__.py`: `default_rules(options) -> list[LintRule]` instantiating plane, plane_fix, export, adr, memory rules; append `build_llm_rule(options)` when `options.llm` and not None.
- `LLMWikiToolkit.lint(wiki_name, fix=False)` delegates to `LintRunner(...).run(LintOptions(fix=fix, ...))`, returns `report.model_dump()`. The legacy keys (`okf_report`, `orphan_sources`, …) are dropped — hard cut per spec Non-Goals.
- `WikiLintReport` in wiki/models.py becomes `WikiLintReport = LintReport` (alias, keep lazy export in wiki/__init__.py:63).
- Update any callers/tests that read old `WikiLintReport` fields.

**NOT in scope**: CLI + MCP (TASK-4020).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` | MODIFY | default_rules() |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | MODIFY | lint() adapter |
| `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` | MODIFY | WikiLintReport alias |
| `packages/ai-parrot/tests/knowledge/lint/test_default_rules.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.lint.runner import LintRunner  # created by TASK-4010
from parrot.knowledge.lint.routing import FindingRouter  # created by TASK-4018
from parrot.knowledge.wiki.models import WikiLintReport  # verified: wiki/models.py:302; lazy export wiki/__init__.py:63
```

### Existing Signatures to Use
```python
# wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):   # :42
    async def lint(self, wiki_name: str, fix: bool = False) -> dict[str, Any]:  # :415 ; builds WikiLintReport at :484; calls self._okf.lint_knowledge_base() at :438
# wiki/models.py:302 class WikiLintReport(BaseModel) (fields okf_report, orphan_sources, stale_sources, uncovered_sources, cross_ref_issues, total_issues; validator compute_total_issues :343)
# FILL IN: locate how the toolkit reaches its store (grep 'self._store\|store' wiki/toolkit.py) before wiring LintRunner
```

### Does NOT Exist
- ~~keeping legacy WikiLintReport fields~~ — hard cut (spec Non-Goals)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_default_rules.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py#LLMWikiToolkit.lint",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/models.py#WikiLintReport"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Grep all readers of `WikiLintReport` / `toolkit.lint(` (`grep -rn 'WikiLintReport\|\.lint(' packages/*/src packages/*/tests`) and update them — *why*: hard cut, no shims (project rule).
2. Keep `default_rules` imports inside the function — *why*: `import parrot.knowledge.lint` must stay cheap.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified after TASK-4009: the file holds only its docstring)
# APPEND below the module docstring
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parrot.knowledge.lint.models import LintOptions
    from parrot.knowledge.lint.rule import LintRule


def default_rules(options: "LintOptions") -> list["LintRule"]:
    """Instantiate every deterministic rule; add the LLM rule only when ``options.llm``."""
    from parrot.knowledge.lint.packs.adr import ADR_RULES
    from parrot.knowledge.lint.packs.export import EXPORT_RULES
    from parrot.knowledge.lint.packs.memory import MEMORY_RULES
    from parrot.knowledge.lint.packs.plane import PLANE_RULES
    from parrot.knowledge.lint.packs.plane_fix import PLANE_FIX_RULES

    rules: list = [cls() for cls in (*PLANE_RULES, *PLANE_FIX_RULES, *EXPORT_RULES, *ADR_RULES, *MEMORY_RULES)]
    if options.llm:
        from parrot.knowledge.lint.packs.llm import build_llm_rule

        llm_rule = build_llm_rule(options)
        if llm_rule is not None:
            rules.append(llm_rule)
    return rules
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def lint(' wiki/toolkit.py)
# REPLACE the BODY of `    async def lint(` (verified: wiki/toolkit.py:415); keep signature, rewrite docstring (fix is now real)
        from parrot.knowledge.lint import LintOptions, LintRunner
        from parrot.knowledge.lint.routing import FindingRouter

        # FILL IN: resolve store/root/config available on self; router = FindingRouter(store, report_dir=None, ledger=None)
        report = await LintRunner(store, root=root, config=config, router=router).run(LintOptions(fix=fix))
        return report.model_dump()
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class WikiLintReport(BaseModel):' wiki/models.py)
# REPLACE the whole `class WikiLintReport(BaseModel):` block (verified: wiki/models.py:302 through its compute_total_issues validator ~:350)
from parrot.knowledge.lint.models import LintReport as WikiLintReport  # noqa: E402 — FEAT-625 hard cut alias
```

**Why this shape**: Spec M9: adapters stay thin. The alias keeps `from parrot.knowledge.wiki import WikiLintReport` importable while the shape is the engine's (hard cut is allowed; update callers in-feature).

### FILL IN checklist
- [ ] toolkit store/root/config resolution
- [ ] caller updates found by grep

---

## Acceptance Criteria

- [ ] `default_rules(LintOptions())` returns all deterministic rules, no llm
- [ ] `LLMWikiToolkit.lint(fix=True)` applies fixes
- [ ] Old WikiLintReport readers updated; their tests pass
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_default_rules.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_default_rules.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_default_rules.py
def test_default_rules_no_llm():
    from parrot.knowledge.lint.models import LintOptions
    from parrot.knowledge.lint.packs import default_rules
    ids = {r.rule_id for r in default_rules(LintOptions())}
    assert "broken-link" in ids and "asymmetric-related" in ids and "contradiction-llm" not in ids
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4019 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
