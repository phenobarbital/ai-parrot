# TASK-639: Verify ExcelLoader factory registration and loader registry

**Feature**: excelloader-migration
**Spec**: `sdd/specs/excelloader-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-638
**Assigned-to**: unassigned

---

## Context

After TASK-638 modifies `ExcelLoader`, this task verifies that the loader factory
(`parrot_loaders.factory`) and registry (`parrot_loaders.__init__`) still correctly
resolve Excel file extensions to the updated `ExcelLoader`. It also verifies that
`openpyxl` and `tabulate` are declared dependencies in the loaders package.

---

## Scope

- Verify `LOADER_MAPPING` in `factory.py` maps `.xlsx`, `.xlsm`, `.xls` to `ExcelLoader`
- Verify `LOADER_REGISTRY` in `__init__.py` maps `"ExcelLoader"` to `"parrot_loaders.excel.ExcelLoader"`
- Verify `openpyxl>=3.1` is in `pyproject.toml` dependencies (required by `ExcelStructureAnalyzer`)
- Verify `tabulate>=0.9` is in `pyproject.toml` dependencies (required by `df.to_markdown()`)
- If any dependency is missing, add it to `pyproject.toml`
- No code changes to `excel.py` — that's TASK-638

**NOT in scope**: Modifying ExcelLoader code, writing tests (TASK-640)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/pyproject.toml` | MODIFY (if needed) | Add missing dependencies |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Factory mapping - verified: packages/ai-parrot-loaders/src/parrot_loaders/factory.py:17-19
LOADER_MAPPING = {
    '.xlsx': ('excel', 'ExcelLoader'),  # line 17
    '.xlsm': ('excel', 'ExcelLoader'),  # line 18
    '.xls': ('excel', 'ExcelLoader'),   # line 19
}

# Registry - verified: packages/ai-parrot-loaders/src/parrot_loaders/__init__.py:12
LOADER_REGISTRY = {
    "ExcelLoader": "parrot_loaders.excel.ExcelLoader",  # line 12
}
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/src/parrot_loaders/factory.py:50
def get_loader_class(extension: str):
    """Get the loader class for the given extension."""
```

### Does NOT Exist

- ~~`parrot_loaders.factory.register_loader()`~~ — no dynamic registration function exists
- ~~`parrot_loaders.AVAILABLE_LOADERS`~~ — removed (see factory.py:76 comment)

---

## Implementation Notes

### Dependency check

```bash
# Check if openpyxl is already a dependency
grep openpyxl packages/ai-parrot-loaders/pyproject.toml

# Check if tabulate is already a dependency
grep tabulate packages/ai-parrot-loaders/pyproject.toml
```

`openpyxl` is likely already present since pandas uses it for Excel reading.
`tabulate` is required by `pandas.DataFrame.to_markdown()` — verify it's declared.

### Key Constraints

- Do not modify factory.py or __init__.py unless mappings are actually wrong
- Only add dependencies that are genuinely missing

---

## Acceptance Criteria

- [ ] `get_loader_class('.xlsx')` returns `ExcelLoader`
- [ ] `openpyxl>=3.1` is in `pyproject.toml` dependencies
- [ ] `tabulate>=0.9` is in `pyproject.toml` dependencies (or already satisfied)
- [ ] No breaking changes to factory or registry

---

## Test Specification

```python
def test_factory_resolves_excel():
    from parrot_loaders.factory import get_loader_class
    cls = get_loader_class('.xlsx')
    assert cls.__name__ == 'ExcelLoader'

def test_factory_resolves_xlsm():
    from parrot_loaders.factory import get_loader_class
    cls = get_loader_class('.xlsm')
    assert cls.__name__ == 'ExcelLoader'
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/excelloader-migration.spec.md` for full context
2. **Check dependencies** — TASK-638 must be complete
3. **Verify the Codebase Contract** — confirm factory mappings still match
4. **Update status** in `tasks/.index.json` -> `"in-progress"`
5. **Implement** — add any missing deps to pyproject.toml
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/TASK-639-excelloader-factory-registration.md`
8. **Update index** -> `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-04-09
**Notes**: Verified factory mappings (.xlsx, .xlsm, .xls -> ExcelLoader) and registry
(ExcelLoader -> parrot_loaders.excel.ExcelLoader) — both correct, no changes needed.
Added `openpyxl>=3.1` and `tabulate>=0.9` to pyproject.toml dependencies (were missing).

**Deviations from spec**: none
