# TASK-2418: Sink alias registry - tenant-scoped credential allowlist

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 3

---

## Context

The security boundary of FEAT-457. Because the `persistence:` block lives inside
a `FormSchema` that is authored over the API, a raw DSN in the schema would let anyone who
can create a form write into any database the server can reach. Instead the schema names an
**alias**, and this registry is the operator-controlled allowlist that maps alias -> credential
source. It is a security control, so it is wired explicitly at app construction (spec section 8,
resolved) and is not runtime-mutable.

Implements spec section 3 Module 3.

---

## Scope

- Create `services/sink_aliases.py`.
- Implement `SinkAliasRegistry` with `register(alias, *, tenant, dsn_env=None, base_dir=None, credentials_env=None)`.
- Implement `resolve_dsn(alias, *, tenant) -> str`, `resolve_base_dir(alias, *, tenant) -> Path`, `resolve_credentials(alias, *, tenant) -> str` and `is_allowed(alias, *, tenant) -> bool`.
- Resolve every credential through `core/auth.py:_get_env` (navconfig first, then `os.environ`) - never read `os.environ` directly.
- Raise `ValueError` for an unknown alias, and for an alias registered under a different tenant.
- `resolve_base_dir` returns a resolved `Path`; add a `contain(alias, *, tenant, relative_path) -> Path` helper that joins and rejects any result whose real path escapes the base directory.
- Write unit tests in `tests/unit/test_sink_aliases.py`.

**NOT in scope**: Any sink implementation. Reading the alias off a `FormSchema` (TASK-2421/2426). The aiohttp app-key wiring (TASK-2429). A DB-backed or hot-reloadable allowlist - explicitly rejected in spec section 8.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sink_aliases.py` | CREATE | Alias allowlist + resolvers |
| `packages/parrot-formdesigner/tests/unit/test_sink_aliases.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.
>
> Verified against `dev` on 2026-08-24. All paths are relative to the repo root.
> Line numbers shift as soon as anything above them changes — **re-`grep` before editing**.

### Verified Imports

```python
# Verified to resolve today:
from parrot_formdesigner.core.auth import _get_env   # core/auth.py:22 (module-private
                                                     # but IS the project-standard resolver)
from pathlib import Path
import logging
```

> If you prefer not to import a module-private name, lift `_get_env` into a shared
> helper **without changing its behaviour** and update `core/auth.py` to use the new
> location. Do NOT reimplement env resolution - the navconfig-first ordering matters.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py - THE pattern to copy (discriminated union, env-name only)
AuthConfig = NoAuth | BearerAuth | ApiKeyAuth          # line 145
def _get_env(var_name: str) -> str: ...                # line 22
#   navconfig first (`from navconfig import config`, line 39);
#   falls back to os.environ (line 47); raises ValueError if absent (line 51).
class BearerAuth(BaseModel):                           # line 77
    type: Literal["bearer"] = "bearer"                 # line 90
    token_env: str                                     # line 91
    def resolve(self) -> dict[str, str]: ...
#   -> members store the NAME of an env var, NEVER the secret. Copy this shape.
```

### Does NOT Exist

- ~~`SinkAliasRegistry`~~ - does not exist; this task creates it. There is **no** connection/alias registry anywhere in `parrot-formdesigner` today; the only existing indirection is the per-`AuthConfig`-member `*_env` field name.
- ~~`navconfig` as a direct dependency of `parrot-formdesigner`~~ - NOT in its dependency list. `core/auth.py:39` imports it inside `try/except ImportError` and falls back to `os.environ`. Keep that guarded pattern.
- ~~`python-datamodel`~~ - not a dependency of `parrot-formdesigner` (it belongs to `ai-parrot`). Do not reach for dynamic model generation.
- ~~`parrot_formdesigner.conf`~~ / ~~a settings module~~ - this package has no central config module. Configuration arrives via constructor arguments and env vars.

---

## Implementation Notes

### Pattern to Follow

Resolution must delegate, not duplicate:

```python
# core/auth.py:22 - navconfig first, os.environ second, ValueError if absent.
# Every resolver in SinkAliasRegistry ends in a _get_env() call.
def resolve_dsn(self, alias: str, *, tenant: str) -> str:
    entry = self._require(alias, tenant=tenant)   # raises ValueError if unknown/cross-tenant
    return _get_env(entry.dsn_env)
```

Containment for file-backed aliases:

```python
def contain(self, alias: str, *, tenant: str, relative_path: str) -> Path:
    base = self.resolve_base_dir(alias, tenant=tenant).resolve()
    candidate = (base / relative_path).resolve()
    if not candidate.is_relative_to(base):     # Python 3.9+; package targets >=3.11
        raise ValueError(...)
    return candidate
```

### Key Constraints

- Tenant scoping is mandatory: an alias registered for tenant A must NOT resolve for tenant B.
- Never log a resolved credential. Log the alias name only.
- The registry holds no secrets in memory beyond what a resolve call returns.
- Containment must use resolved real paths, so a symlink cannot escape the base dir.
- Google-style docstrings, strict type hints, `self.logger`.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/core/auth.py:22` - `_get_env`, the resolver to delegate to
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:159` - `_resolve_schema`, the existing tenant-resolution idiom

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry` works
- [ ] An unregistered alias raises `ValueError`
- [ ] An alias registered for tenant `a` raises `ValueError` when resolved for tenant `b`
- [ ] A registered DSN alias resolves through a monkeypatched env var
- [ ] `contain()` rejects `../../etc/passwd`, an absolute path, and a symlink escaping the base dir
- [ ] No test asserts on a logged credential value (nothing secret is logged)
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_sink_aliases.py -v` passes
- [ ] `ruff` and `mypy` clean on the new module

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_sink_aliases.py
import pytest
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEY_DB_DSN", "postgresql://u:p@localhost/surveys")
    reg = SinkAliasRegistry()
    reg.register("survey_db", tenant="navigator", dsn_env="SURVEY_DB_DSN")
    reg.register("exports", tenant="navigator", base_dir=str(tmp_path))
    return reg


class TestSinkAliasRegistry:
    def test_unknown_alias_raises(self, registry):
        with pytest.raises(ValueError):
            registry.resolve_dsn("survey_db2", tenant="navigator")

    def test_alias_is_tenant_scoped(self, registry):
        with pytest.raises(ValueError):
            registry.resolve_dsn("survey_db", tenant="other")

    def test_resolves_via_get_env(self, registry):
        assert registry.resolve_dsn("survey_db", tenant="navigator").startswith("postgresql://")

    @pytest.mark.parametrize("bad", ["../escape.csv", "/etc/passwd"])
    def test_contain_rejects_escape(self, registry, bad):
        with pytest.raises(ValueError):
            registry.contain("exports", tenant="navigator", relative_path=bad)

    def test_contain_allows_inside(self, registry, tmp_path):
        got = registry.contain("exports", tenant="navigator", relative_path="nps.csv")
        assert got.parent == tmp_path.resolve()
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context.
2. **Check dependencies** - verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** - before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source).
   - Confirm every class/method in "Existing Signatures" still has the listed attributes.
   - If anything has changed, update the contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract without
     verifying it exists.
4. **Update status** in `sdd/tasks/index/formbuilder-formschema-persistency.json` ->
   `"in-progress"` with your session ID.
5. **Implement** following the scope, codebase contract, and notes above.
6. **Verify** all acceptance criteria are met.
7. **Move this file** to `sdd/tasks/completed/`.
8. **Update index** -> `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-24
**Notes**: Implemented `services/sink_aliases.py` with `SinkAliasRegistry`
(`register`, `resolve_dsn`, `resolve_base_dir`, `resolve_credentials`,
`is_allowed`, `contain`). All credential resolution delegates to
`core/auth.py:_get_env` (navconfig-first, os.environ fallback) — no direct
`os.environ` reads. `contain()` resolves real paths so a symlink cannot
escape the base dir. 11 unit tests in `tests/unit/test_sink_aliases.py`,
all passing, including a symlink-escape case and a check that no resolved
credential appears in captured log output. `ruff` and targeted `mypy`
clean.

**Deviations from spec**: none
