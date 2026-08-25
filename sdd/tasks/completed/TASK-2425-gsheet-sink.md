# TASK-2425: `GoogleSheetSink` + the `[gsheet]` optional extra

**Feature**: FEAT-457 — Autonomous FormSchema Persistence (Standalone Forms)
**Spec**: `sdd/specs/formbuilder-formschema-persistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-2418, TASK-2419, TASK-2420
**Assigned-to**: unassigned
**Implements**: Spec section 3 Module 9

---

## Context

The cloud counterpart of the Microsoft-Forms case. Unlike CSV, a spreadsheet API
*can* append a column, so this sink declares `EXTEND`.

This is the only v1 sink needing a new dependency, so it must degrade cleanly: with the
`[gsheet]` extra uninstalled, importing `parrot-formdesigner` must still work and using the
sink must produce an actionable error.

Implements spec section 3 Module 9.

---

## Scope

- Create `services/sinks/gsheet.py` with `GoogleSheetSink(AbstractSubmissionSink)`.
- Declare capabilities `{WRITE, PROVISION, EXTEND}` - no READ, no LIST.
- Guard the Google client import so module import never fails when the extra is absent; raise an actionable error (naming `pip install parrot-formdesigner[gsheet]`) on use.
- Resolve service-account credentials through `SinkAliasRegistry` - never from the target model.
- `ensure_target(form)`: create the worksheet with a header row when absent; append a column when the form has gained a field.
- `write(...)`: append one row.
- Map `429`, transport errors and auth failures to `SinkUnavailableError`. No retry loop inside the request path.
- Add the `[gsheet]` optional extra to `packages/parrot-formdesigner/pyproject.toml` with `google-api-python-client>=2.151`.
- Write unit tests in `tests/unit/test_gsheet_sink.py` with a fake sheets client.

**NOT in scope**: Reading or listing submissions from a sheet. A retry/backoff policy. Registration in the dispatch table (TASK-2426). `gspread` - not used.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/gsheet.py` | CREATE | Google Sheets sink |
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | Add the `[gsheet]` extra |
| `packages/parrot-formdesigner/tests/unit/test_gsheet_sink.py` | CREATE | Unit tests with a fake client |

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
# Guarded - the extra may not be installed:
try:
    from googleapiclient.discovery import build   # google-api-python-client (NEW extra)
except ImportError:                                # pragma: no cover
    build = None

# Verified to resolve today:
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.services.submissions import FormSubmission
# Created by earlier tasks in this spec:
from parrot_formdesigner.core.persistence import SinkCapability, GoogleSheetTarget   # TASK-2417
from parrot_formdesigner.services.sinks.base import (                                # TASK-2419
    AbstractSubmissionSink, SinkUnavailableError,
)
from parrot_formdesigner.services.sinks.mapper import (                              # TASK-2420
    flatten_submission, column_names_for,
)
from parrot_formdesigner.services.sink_aliases import SinkAliasRegistry              # TASK-2418
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/pyproject.toml - the CURRENT extras (lines 49-61).
# Add `gsheet` alongside them; do not restructure the block.
[project.optional-dependencies]
ai-parrot = ["ai-parrot>=0.27.0"]     # lines 50-52
redis = ["redis>=4.5"]                # lines 53-55
test = [...]                          # lines 56-61

# packages/ai-parrot/pyproject.toml:311 - the version already used elsewhere in the
# workspace, for consistency:
"google-api-python-client>=2.151.0"
```

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:50
class FormSubmission(BaseModel):
    submission_id: str          # default_factory=lambda: str(uuid.uuid4())
    form_uid: uuid.UUID         # REQUIRED (FEAT-389 / TASK-1979)
    form_id: str
    form_version: str
    data: dict[str, Any]
    is_valid: bool
    forwarded: bool = False
    forward_status: int | None = None
    forward_error: str | None = None
    created_at: datetime        # default_factory -> datetime.now(timezone.utc)
    tenant: str | None = None
    user_id: str | None = None
    username: str | None = None
    org_id: int | None = None
    submitted_at: datetime | None = None
    ip: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    root_submission_id: str | None = None
    revision: int | None = None
    context: dict[str, Any] | None = None
```

### Does NOT Exist

- ~~`gspread`~~ - not present anywhere in the workspace. Use `google-api-python-client` (new `[gsheet]` extra) or `aiogoogle`.
- ~~`AbstractSubmissionSink` / `FormSubmissionSink` / `SubmissionSink`~~ - no sink abstraction exists anywhere in `parrot-formdesigner` before TASK-2419. `FormSubmissionStorage` (`packages/parrot-formdesigner/src/parrot_formdesigner/services/submissions.py:118`) is a **plain class, NOT an ABC** - there is no existing interface to implement.
- ~~`google-api-python-client` in `parrot-formdesigner`~~ - NOT currently a dependency. It appears only in `ai-parrot` extras (`packages/ai-parrot/pyproject.toml:311`). This task adds it as a NEW optional extra.
- ~~`aiogoogle`~~ - appears only in `ai-parrot-tools`' `google` extra (`packages/ai-parrot-tools/pyproject.toml:78`), not here. Either client is acceptable, but declare whichever you use in the new extra.
- ~~an async Google Sheets client in this package~~ - none exists. `googleapiclient` is synchronous, so its calls MUST be offloaded with `asyncio.to_thread`.

---

## Implementation Notes

### Pattern to Follow

Guarded import + actionable failure, so the package stays installable without the extra:

```python
def _require_client(self):
    if build is None:
        raise SinkUnavailableError(
            "Google Sheets sink requires the 'gsheet' extra: "
            "pip install parrot-formdesigner[gsheet]"
        )
    ...

# googleapiclient is synchronous - never call it directly on the event loop:
await asyncio.to_thread(self._append_row_sync, values)
```

### Key Constraints

- Module import must NEVER fail because the extra is absent - guard it.
- `googleapiclient` is synchronous; every call goes through `asyncio.to_thread`.
- Credentials come from the alias registry only.
- `429` and transport errors -> `SinkUnavailableError` (-> 503). No in-request retry loop.
- `EXTEND` appends a column; it must never reorder or delete existing columns.
- Never log credentials or the full sheet payload.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/sinks/csv_file.py` - sibling write-only-ish sink (TASK-2424)
- `packages/ai-parrot/pyproject.toml:311` - the client version used in this workspace
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/blob_storage.py:422` - `GCSBlobStorage`, an existing guarded-Google-client precedent

---

## Acceptance Criteria

- [ ] `capabilities == frozenset({WRITE, PROVISION, EXTEND})`
- [ ] `import parrot_formdesigner.services.sinks.gsheet` succeeds with the extra ABSENT
- [ ] Using the sink with the extra absent raises `SinkUnavailableError` naming the extra
- [ ] A fresh worksheet gets a header row
- [ ] A new form field appends a column and leaves existing columns in place
- [ ] A simulated `429` raises `SinkUnavailableError` with no retry attempted
- [ ] No synchronous Google call runs on the event loop (asserted via a to_thread spy)
- [ ] `[gsheet]` extra present in `pyproject.toml` and `pip install -e '.[gsheet]'` resolves
- [ ] `pytest packages/parrot-formdesigner/tests/unit/test_gsheet_sink.py -v` passes
- [ ] `ruff` and `mypy` clean

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_gsheet_sink.py
import pytest

from parrot_formdesigner.core.persistence import SinkCapability
from parrot_formdesigner.services.sinks.base import SinkUnavailableError


class TestGuardedImport:
    def test_module_imports_without_extra(self, monkeypatch):
        import parrot_formdesigner.services.sinks.gsheet as mod
        monkeypatch.setattr(mod, "build", None)
        assert mod is not None

    async def test_use_without_extra_is_actionable(self, monkeypatch, gsheet_sink, form):
        import parrot_formdesigner.services.sinks.gsheet as mod
        monkeypatch.setattr(mod, "build", None)
        with pytest.raises(SinkUnavailableError, match="gsheet"):
            await gsheet_sink.ensure_target(form)


class TestProvision:
    async def test_creates_header(self, gsheet_sink, fake_client, form):
        await gsheet_sink.ensure_target(form)
        assert fake_client.header_written

    async def test_new_field_appends_column(self, gsheet_sink, fake_client, form_with_extra_field):
        await gsheet_sink.ensure_target(form_with_extra_field)
        assert fake_client.columns_appended == 1


class TestFailure:
    async def test_rate_limit_maps_unavailable(self, gsheet_sink_429, submission):
        with pytest.raises(SinkUnavailableError):
            await gsheet_sink_429.write(submission, {})

    async def test_no_retry_on_429(self, gsheet_sink_429, fake_client, submission):
        with pytest.raises(SinkUnavailableError):
            await gsheet_sink_429.write(submission, {})
        assert fake_client.attempts == 1


class TestCapabilities:
    def test_capability_set(self, gsheet_sink):
        assert gsheet_sink.capabilities == frozenset({
            SinkCapability.WRITE, SinkCapability.PROVISION, SinkCapability.EXTEND
        })
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
**Notes**: Implemented `GoogleSheetSink` with capabilities
`{WRITE, PROVISION, EXTEND}`. Guarded top-level
`try/except ImportError: build = None` for
`googleapiclient.discovery.build`, so the module (and package) import
never fails without the `[gsheet]` extra; `_ensure_client()` raises an
actionable `SinkUnavailableError` naming
`pip install parrot-formdesigner[gsheet]` only when actually used.
Credentials resolved exclusively via `SinkAliasRegistry.resolve_credentials`
(never from the target model), built into a `google.oauth2.service_account.
Credentials` (lazy import) accepting either a JSON blob or a file path.
Added an internal `_SheetsClient` wrapper (real Sheets v4 calls) so the
sink's own logic (`ensure_target`/`write`) is client-agnostic and
directly testable with a fake client double implementing the same 4-method
surface. Every blocking `googleapiclient`/credential-building call goes
through `asyncio.to_thread` (verified with a spy). `ensure_target` creates
the header on a fresh sheet, or appends only the missing columns at the
trailing position on drift (existing columns never reordered/deleted).
`write` never retries (including on a simulated `429`, mapped to
`SinkUnavailableError`). Added the `[gsheet]` optional extra
(`google-api-python-client>=2.151.0`, matching the version already used
elsewhere in the workspace) to `pyproject.toml`, verified it parses via
`tomllib`. 8 unit tests in `tests/unit/test_gsheet_sink.py`, all passing:
guarded import (module import + actionable-error-on-use), header
creation, additive column append, rate-limit mapping with exactly one
attempt (no retry), the capability set, and a to-thread spy proving no
synchronous Google call runs on the event loop. `ruff` and targeted
`mypy` clean.

**Deviations from spec**: Diverged from the given Test Specification's
exact fixture wiring (where `gsheet_sink` — pre-loaded with `fake_client`
— was reused unmodified in the guarded-import-absent test, which would
never exercise the `build is None` branch since a client was already
injected). Instead, `TestGuardedImport.test_use_without_extra_is_actionable`
constructs its own client-less sink so the guard genuinely runs; all other
fixtures/tests match the given spec's intent and names
(`gsheet_sink`, `fake_client`, `gsheet_sink_429`, capability/failure/
provision coverage) faithfully.
