---
type: Wiki Overview
title: 'TASK-1240: `load_from_directory` per-file tenant resolution (YAML wins, kwarg
  default, skip-with-warning)'
id: doc:sdd-tasks-completed-task-1240-formregistry-load-from-directory-tenant-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Module 2 of the spec: makes `FormRegistry.load_from_directory`'
---

# TASK-1240: `load_from_directory` per-file tenant resolution (YAML wins, kwarg default, skip-with-warning)

**Feature**: FEAT-183 — FormRegistry Multi-Tenancy
**Spec**: `sdd/specs/formregistry-multi-tenancy.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1239
**Assigned-to**: unassigned

---

## Context

Implements Module 2 of the spec: makes `FormRegistry.load_from_directory`
tenant-aware. Per the spec's resolved Open Question, tenant resolution per
YAML file is:

1. If the YAML declares a top-level `tenant:` field, that value wins (and is
   recorded on the constructed `FormSchema.tenant`).
2. Otherwise the `tenant=` kwarg passed to `load_from_directory` supplies it.
3. If both are missing AND `self._require_tenant=True`, the file is **skipped
   with a `WARNING` log** (NOT a hard failure). This preserves today's
   best-effort-per-file semantics in `registry.py:312-315`.

The `YamlExtractor` integration (`registry.py:289-290`) likely already
populates `FormSchema.tenant` if the YAML declares it (since `FormSchema`
has `tenant` as a regular field). This task verifies that and adds the
kwarg-default-and-skip-with-warning behavior on top.

---

## Scope

- Add a kwarg-only `tenant: str | None = None` parameter to
  `load_from_directory` (line 269).
- Update docstring with the resolution rule and skip-with-warning policy.
- For each YAML file successfully parsed by `YamlExtractor`:
  - If `form.tenant is None` and `tenant` kwarg is not `None`, set
    `form = form.model_copy(update={"tenant": tenant})` before calling
    `self.register()`.
  - If `form.tenant is None` AND `tenant` kwarg is `None` AND
    `self._require_tenant`, log a `WARNING` ("skipping <path>: no tenant
    declared in YAML and no fallback kwarg supplied") and continue without
    registering. Do NOT count the file in the return value.
  - Otherwise (form has a tenant, or `require_tenant=False`), call
    `await self.register(form, overwrite=overwrite)` as today.
- The return value remains "number of forms successfully registered".
- Verify (by reading the YAML extractor) that `tenant:` declared in YAML
  flows through to `FormSchema.tenant`. If it does not, file a finding —
  but do NOT modify the extractor here; that would be out of scope. Surface
  the gap in the Completion Note instead.
- Add three unit tests to `tests/unit/test_registry_multi_tenancy.py`:
  - `test_load_from_directory_yaml_tenant_wins`
  - `test_load_from_directory_kwarg_default_used`
  - `test_load_from_directory_skip_with_warning_on_missing`

**NOT in scope**:
- Modifying `YamlExtractor`. If it doesn't surface `tenant:`, raise that as
  a separate concern; this task documents but does not fix.
- Changing the YAML files themselves (handled by TASK-1241 / TASK-1242).
- Updating `load_from_storage` — it's already tenant-aware and falls under
  TASK-1239's scope.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py` | MODIFY | Add `tenant=` kwarg to `load_from_directory`; implement per-file resolution + skip-with-warning. |
| `packages/parrot-formdesigner/tests/unit/test_registry_multi_tenancy.py` | MODIFY | Add the three `test_load_from_directory_*` tests. |
| `packages/parrot-formdesigner/tests/unit/fixtures/yaml_forms_mixed/` | CREATE (if needed) | YAML fixture files: one with `tenant:`, one without. Used by the new tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# In registry.py — already present:
from pathlib import Path                                                  # line 20
# Lazy import (line 289-290):
from ..extractors.yaml import YamlExtractor

# Path the agent must use for FormSchema:
from parrot_formdesigner.core.schema import FormSchema                    # core/schema.py:154
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py:269
async def load_from_directory(
    self,
    path: str | Path,
    *,
    recursive: bool = True,
    overwrite: bool = False,
) -> int: ...

# Inside the method (line 290):
#   extractor = YamlExtractor()
#   form = extractor.extract_from_file(str(yaml_file))      # line 308
#   await self.register(form, overwrite=overwrite)          # line 309

# Loop structure (lines 302-315):
for yaml_file in list(dir_path.glob(pattern)) + list(dir_path.glob(yml_pattern)):
    try:
        form = extractor.extract_from_file(str(yaml_file))
        await self.register(form, overwrite=overwrite)
        count += 1
        self.logger.debug("Loaded form %s from %s", form.form_id, yaml_file)
    except Exception as exc:
        self.logger.warning("Failed to load form from %s: %s", yaml_file, exc)

# FormSchema.tenant field used to detect "declared in YAML":
class FormSchema(BaseModel):
    tenant: str | None = None                                              # core/schema.py:187
# If YAML had `tenant: epson`, the extractor will populate this field.
```

### Does NOT Exist

- ~~`YamlExtractor.extract_with_tenant()`~~ — do not invent. Use the existing
  `extract_from_file()` and inspect `form.tenant`.
- ~~`FormSchema.set_tenant()`~~ — use `form.model_copy(update={"tenant": ...})`
  (Pydantic v2).
- ~~A separate `_per_file_tenant` field~~ — there is no per-file metadata
  beyond what `FormSchema` already carries.
- ~~Raising on missing tenant~~ — this task implements skip-with-warning,
  NOT fail-hard. See spec §8 resolved Open Question.

---

## Implementation Notes

### Pattern to Follow

```python
async def load_from_directory(
    self,
    path: str | Path,
    *,
    recursive: bool = True,
    overwrite: bool = False,
    tenant: str | None = None,
) -> int:
    """... existing docstring ...
    
    Tenant resolution per file:
      1. YAML's own ``tenant:`` field wins (carried on ``FormSchema.tenant``).
      2. Otherwise the ``tenant=`` kwarg supplies a default.
      3. Otherwise, if ``require_tenant=True``, the file is skipped with a
         WARNING log; if ``require_tenant=False``, the form is sealed to
         the registry's ``default_tenant`` at register time.
    """
    # ... existing setup ...

    for yaml_file in list(dir_path.glob(pattern)) + list(dir_path.glob(yml_pattern)):
        try:
            form = extractor.extract_from_file(str(yaml_file))

            # Tenant resolution (per spec §2 Overview)
            if form.tenant is None and tenant is not None:
                form = form.model_copy(update={"tenant": tenant})

            if form.tenant is None and self._require_tenant:
                self.logger.warning(
                    "Skipping %s: no tenant declared in YAML and no fallback "
                    "tenant= kwarg supplied (require_tenant=True)",
                    yaml_file,
                )
                continue

            await self.register(form, overwrite=overwrite)
            count += 1
            self.logger.debug("Loaded form %s (tenant=%s) from %s",
                              form.form_id, form.tenant, yaml_file)
        except Exception as exc:
            self.logger.warning(
                "Failed to load form from %s: %s", yaml_file, exc
            )

    self.logger.info("Loaded %d forms from %s", count, dir_path)
    return count
```

### Key Constraints

- Skip-with-warning, NOT exception. The `try/except` block already catches
  exceptions; the new skip path is a deliberate `continue` BEFORE
  `register()`.
- Do NOT mutate the YAML file. Only mutate the in-memory `FormSchema` via
  `model_copy`.
- The `register()` call inside the loop does NOT pass `tenant=` — the
  effective tenant is already on `form.tenant` after the resolution above,
  so `register()`'s own resolution logic (kwarg > form.tenant > default)
  picks it up correctly.
- When `require_tenant=False` and both YAML and kwarg are missing,
  `register()` will seal the form to `default_tenant` — this is the
  documented behavior; this task does NOT add a separate logging hook for
  that case.

### References in Codebase

- `services/registry.py:269-318` — the method being modified.
- `core/schema.py:187` — `FormSchema.tenant` field.
- `tests/integration/test_msteams_import_compat.py` and other tests under
  `packages/parrot-formdesigner/tests/` — patterns for YAML fixture
  organization.

---

## Acceptance Criteria

- [ ] `load_from_directory` accepts kwarg-only `tenant: str | None = None`.
- [ ] When a YAML declares `tenant:`, the resulting `FormSchema.tenant`
      reflects it AND wins over the `tenant=` kwarg.
- [ ] When a YAML lacks `tenant:` but the kwarg supplies one, the form is
      registered under the kwarg's tenant.
- [ ] When BOTH are missing AND `require_tenant=True`, the file is skipped
      and a `WARNING` log is emitted; the file does NOT count toward the
      return value.
- [ ] When BOTH are missing AND `require_tenant=False`, the form is sealed
      to `default_tenant` (existing register() behavior; no new logging).
- [ ] All three new unit tests pass.
- [ ] No regression in any existing tests under
      `packages/parrot-formdesigner/tests/`.

---

## Test Specification

```python
class TestLoadFromDirectoryTenant:
    @pytest.fixture
    def yaml_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "yaml_forms_mixed"
        d.mkdir()
        # File with explicit YAML tenant:
        (d / "with_tenant.yaml").write_text(
            "form_id: with-tenant\nversion: '1.0'\n"
            "title: {en: With Tenant}\nsections: []\ntenant: epson\n"
        )
        # File without tenant:
        (d / "no_tenant.yaml").write_text(
            "form_id: no-tenant\nversion: '1.0'\n"
            "title: {en: No Tenant}\nsections: []\n"
        )
        return d

    async def test_load_from_directory_yaml_tenant_wins(self, registry, yaml_dir):
        # kwarg says "navigator", YAML says "epson" — YAML wins
        count = await registry.load_from_directory(yaml_dir, tenant="navigator")
        # Only files with resolvable tenants count; the no_tenant file is skipped
        # because require_tenant=True and the kwarg is overridden by YAML for
        # the with-tenant file only. Wait — kwarg WAS supplied for both files;
        # so the no-tenant file gets sealed to "navigator" via the kwarg, NOT
        # skipped. Verify:
        assert count == 2
        assert await registry.get("with-tenant", tenant="epson") is not None
        assert await registry.get("no-tenant", tenant="navigator") is not None
        # And NOT under the wrong tenants:
        assert await registry.get("with-tenant", tenant="navigator") is None

    async def test_load_from_directory_kwarg_default_used(self, registry, yaml_dir):
        count = await registry.load_from_directory(yaml_dir, tenant="pokemon")
        # YAML's with-tenant still wins; no-tenant gets pokemon
        assert await registry.get("with-tenant", tenant="epson") is not None
        assert await registry.get("no-tenant", tenant="pokemon") is not None
        assert count == 2

    async def test_load_from_directory_skip_with_warning_on_missing(
        self, registry, yaml_dir, caplog
    ):
        caplog.set_level(logging.WARNING)
        # No kwarg, require_tenant=True (default). no-tenant.yaml is skipped.
        count = await registry.load_from_directory(yaml_dir)
        assert count == 1  # only with-tenant
        assert await registry.get("with-tenant", tenant="epson") is not None
        assert await registry.get("no-tenant", tenant="navigator") is None
        # Warning logged:
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("no_tenant" in r.message or "tenant" in r.message.lower()
                   for r in warnings)
```

Adapt the YAML fixture format to whatever `YamlExtractor` actually parses —
verify by reading
`packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py`
before writing fixtures.

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/formregistry-multi-tenancy.spec.md` §2
   (Overview) and §8 (resolved Open Question on skip-with-warning).
2. **Check dependencies**: TASK-1239 must be `done` — the new constructor
   args (`require_tenant`, `default_tenant`) and the nested `_forms` state
   must already exist.
3. **Verify the Codebase Contract** above against the current
   `services/registry.py`. If line numbers drifted, update first.
4. **Read** `packages/parrot-formdesigner/src/parrot_formdesigner/extractors/yaml.py`
   to confirm `YamlExtractor` populates `FormSchema.tenant` from a top-level
   YAML `tenant:` field. If it doesn't, document the gap in the Completion
   Note — do NOT fix the extractor here.
5. **Update status** in the per-spec index.
6. **Implement** the kwarg + resolution per Implementation Notes.
7. **Add the three unit tests** and confirm all pass.
8. **Move this file** to `sdd/tasks/completed/`.
9. **Update index** → `done`.
10. **Fill in the Completion Note** with any extractor-gap finding.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-19
**Notes**: Added tenant= kwarg to load_from_directory. Extractor gap confirmed:
YamlExtractor._parse_schema() does NOT pass the YAML top-level tenant: field
through to FormSchema.tenant. Workaround: load_from_directory reads the raw
YAML dict separately to extract tenant: before registering. The extractor was
NOT modified. Three load_from_directory tests added (yaml_tenant_wins,
kwarg_default_used, skip_with_warning_on_missing) + bonus
require_tenant_false_seals_to_default — all pass.

**Deviations from spec**: Workaround for extractor gap documented above. The
spec said to document the gap and NOT fix the extractor — compliance met.
