# TASK-2156: Recipient ingestion — JSON / multipart / base64 → normalized rows

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. The sender accepts recipients through three transports
(inline JSON, `multipart/form-data`, base64-embedded file). This task
normalizes all three into a single `list[RecipientIn]` so every downstream
module sees one shape.

It also owns the two hard ceilings: **50 MB** upload and **10 000** recipients.

Leaf task — no in-spec dependencies.

---

## Scope

- Implement `RecipientIn` (datamodel `BaseModel`) and the ingestion service.
- Support all three transports; produce identical rows from each.
- Normalize column names: case-insensitive, trimmed, alias-mapped.
- Parse Excel/CSV with pandas **off the event loop** via `asyncio.to_thread`.
- Enforce the 50 MB and 10 000-row caps.
- Reject files with none of the canonical columns, and empty files.
- Warn when an uploaded file uses a **reserved** column name.
- Unit tests including an event-loop-blocking guard.

**NOT in scope**:
- HTTP request handling / content-type dispatch (TASK-2159).
- Provider resolution or contact-field validation (TASK-2157).
- Rendering (TASK-2157).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/services/comm_center/__init__.py` | CREATE | Package init |
| `packages/ai-parrot-server/src/parrot/services/comm_center/models.py` | CREATE | `RecipientIn`, `SkippedRow` |
| `packages/ai-parrot-server/src/parrot/services/comm_center/ingest.py` | CREATE | Ingestion + normalization + caps |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_ingest.py` | CREATE | Unit tests + fixtures |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06 (`pandas 2.2.3`, `openpyxl 3.1.5` importable in `.venv`).

### Verified Imports

```python
import asyncio
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas                                  # verified: 2.2.3
from datamodel import BaseModel, Field         # verified: core dep
```

### Existing Signatures to Use

```python
# navigator.views.base.BaseHandler — VERIFIED live introspection
# The handler (TASK-2159) calls this and hands the resulting paths to us.
async def handle_upload(self, request: Optional[web.Request] = None,
                        form_key: Optional[str] = None, ext: str = '.csv',
                        preserve_filenames: bool = True
                        ) -> Tuple[Dict[str, List[dict]], dict]: ...
# Returns (files_grouped_by_field_name, form_fields).
# Raises HTTPUnsupportedMediaType on non-multipart. Streams parts to temp files.
# ⇒ DO NOT hand-roll multipart parsing.
```

```python
# packages/ai-parrot-server/src/parrot/handlers/datasets.py:40 — size cap convention
MAX_FILE_SIZE = 50 * 1024 * 1024
# usage at datasets.py:335-340:
#   if len(data) > MAX_FILE_SIZE:
#       ... f"Maximum size is {MAX_FILE_SIZE // (1024 * 1024)}MB"

# packages/ai-parrot-server/src/parrot/handlers/infographic_render.py:63
DEFAULT_MAX_BODY_SIZE = 50 * 1024 * 1024  # 50 MB
```

### Does NOT Exist

- ~~A generic Excel/CSV → recipients parser anywhere in `parrot`~~ — none exists.
  `DatasetManager` file loading is dataset-oriented, not a recipient normalizer.
  Write this from scratch.
- ~~`parrot.services.comm_center`~~ — the package does not exist yet.
- ~~`pandas.read_excel` being safe to call directly in an async handler~~ — it is
  **blocking**. It MUST go through `asyncio.to_thread`.
- ~~`RecipientIn` / `SkippedRow`~~ — do not exist yet; this task creates them.

---

## Implementation Notes

### `RecipientIn` shape (spec §2 Data Models)

```python
class RecipientIn(BaseModel):
    name: str                        # only mandatory field
    username: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    provider: Optional[str]          # per-record override
    extra: dict                      # every non-canonical column, verbatim
```

### Column normalization
Lower-case, strip surrounding whitespace, then apply the alias map:

| Alias | Canonical |
|---|---|
| `e-mail`, `e mail`, `correo` | `email` |
| `nombre` | `name` |
| `teléfono`, `telefono`, `mobile`, `cell` | `phone` |
| `user`, `usuario` | `username` |
| `direccion`, `dirección` | `address` |

Unrecognized columns are preserved verbatim into `extra` — they become valid
pass-2 placeholders downstream.

### Reserved-column warning
If an uploaded file has a column named `recipient`, `message` or `subject`,
these shadow Notify's own bindings. Emit a warning in the ingestion result
(`self.logger.warning` + a `warnings` list) — do not silently accept.

### Caps and rejections
| Condition | Outcome |
|---|---|
| Payload/file > **50 MB** | raise a typed error → handler maps to `413` |
| Rows > **10 000** | raise a typed error → handler maps to `400` |
| 0 rows after parsing | typed error → `400` ("0 recipients") |
| None of `name/username/email/phone` present | typed error → `400` |

Define module-level `MAX_FILE_SIZE = 50 * 1024 * 1024` and
`MAX_RECIPIENTS = 10_000` following the repo constant convention.

### Key Constraints
- Async throughout; **all** pandas calls wrapped in `asyncio.to_thread`.
- `.xlsx` via the openpyxl engine; `.csv` via `read_csv`.
- Blank/NaN cells → `None`, never the string `"nan"`.
- `self.logger` for warnings; no `print`.
- Google-style docstrings + full type hints.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/handlers/datasets.py:40,335-340` — size cap
- `packages/ai-parrot-server/src/parrot/handlers/infographic_render.py:63` — constant convention

---

## Acceptance Criteria

- [ ] All three transports produce **identical** `RecipientIn` lists for the same data
- [ ] Column aliases normalized per the table above; extras preserved in `extra`
- [ ] NaN/blank cells become `None`
- [ ] `> 50 MB` and `> 10 000 rows` raise typed errors
- [ ] Empty file and no-known-columns raise typed errors
- [ ] Reserved column names produce a warning
- [ ] **Every** pandas call goes through `asyncio.to_thread` (asserted by test)
- [ ] Tests pass: `pytest packages/ai-parrot-server/tests/handlers/test_comm_center_ingest.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
import asyncio, base64
from pathlib import Path
import pytest

from parrot.services.comm_center.ingest import (
    ingest_recipients, MAX_RECIPIENTS, MAX_FILE_SIZE,
)


@pytest.fixture
def messy_csv(tmp_path) -> Path:
    p = tmp_path / "r.csv"
    p.write_text("Nombre, E-Mail ,Teléfono,user,department\n"
                 "Ana Gomez,ana@example.com,+34600000000,agomez,Sales\n")
    return p


class TestIngest:
    async def test_columns_normalized(self, messy_csv):
        rows = await ingest_recipients(file_path=messy_csv)
        assert rows[0].name == "Ana Gomez"
        assert rows[0].email == "ana@example.com"
        assert rows[0].phone == "+34600000000"
        assert rows[0].username == "agomez"

    async def test_extra_columns_preserved(self, messy_csv):
        rows = await ingest_recipients(file_path=messy_csv)
        assert rows[0].extra["department"] == "Sales"

    async def test_transports_agree(self, messy_csv):
        via_file = await ingest_recipients(file_path=messy_csv)
        via_b64 = await ingest_recipients(
            file_bytes=base64.b64decode(
                base64.b64encode(messy_csv.read_bytes())), filename="r.csv")
        assert [r.email for r in via_file] == [r.email for r in via_b64]

    async def test_rejects_empty_file(self, tmp_path):
        p = tmp_path / "e.csv"; p.write_text("name,email\n")
        with pytest.raises(ValueError, match="0 recipients|empty"):
            await ingest_recipients(file_path=p)

    async def test_rejects_unknown_columns(self, tmp_path):
        p = tmp_path / "u.csv"; p.write_text("foo,bar\n1,2\n")
        with pytest.raises(ValueError):
            await ingest_recipients(file_path=p)

    async def test_recipient_cap(self, tmp_path):
        p = tmp_path / "big.csv"
        p.write_text("name,email\n" + "".join(
            f"U{i},u{i}@e.com\n" for i in range(MAX_RECIPIENTS + 1)))
        with pytest.raises(ValueError, match="10000|10 000|cap"):
            await ingest_recipients(file_path=p)

    async def test_does_not_block_event_loop(self, messy_csv, monkeypatch):
        """pandas must be called via asyncio.to_thread."""
        called = {}
        real = asyncio.to_thread
        async def spy(fn, *a, **k):
            called["yes"] = True
            return await real(fn, *a, **k)
        monkeypatch.setattr(asyncio, "to_thread", spy)
        await ingest_recipients(file_path=messy_csv)
        assert called.get("yes") is True

    async def test_reserved_column_warns(self, tmp_path):
        p = tmp_path / "res.csv"
        p.write_text("name,email,subject\nAna,a@e.com,Hi\n")
        rows, warnings = await ingest_recipients(file_path=p, return_warnings=True)
        assert any("subject" in w for w in warnings)
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 4
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — confirm the size-cap constants at
   `datasets.py:40` and `infographic_render.py:63` before copying the convention
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** acceptance criteria
7. **Move** to `sdd/tasks/completed/TASK-2156-recipient-ingestion.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-06
**Notes**:
Implemented `RecipientIn`/`SkippedRow` (`services/comm_center/models.py`)
and `ingest_recipients()` (`services/comm_center/ingest.py`) covering all
three transports (inline JSON rows, multipart-uploaded file path, and
base64-decoded bytes), column normalization with the alias map, the
50MB/10 000-row caps (as `FileTooLargeError`/`RecipientCapExceededError`,
both `IngestionError`/`ValueError` subclasses so the handler can map them
to 413/400 respectively), empty-file/no-known-columns rejection, and
reserved-column warnings. All pandas parsing is wrapped in a single
`asyncio.to_thread` call per transport (asserted by
`test_does_not_block_event_loop`). Added a `.xlsx` fixture/test
(`test_ingest_xlsx_via_openpyxl`) beyond this task's own scaffold to match
spec §4's Module 4 test list.

**Important bug found and fixed during implementation** (not scope creep —
a correctness bug in this task's own new code): `pandas.read_csv`/
`read_excel` were letting pandas infer column dtypes, which silently
coerced the `phone` column to a numeric type and stripped the leading `+`
(e.g. `"+34600000000"` -> `"34600000000"`). Fixed by reading every column
as `dtype=str` in both `_dataframe_from_path_sync` and
`_dataframe_from_bytes_sync` — recipient fields must never be
numeric-coerced.

**Second, more far-reaching bug found and fixed**: while debugging a
`TypeError: Expected type, got types.UnionType` raised by
`datamodel`/`asyncdb.models.Model` field validation, confirmed live that
this repo's installed `datamodel` package does **not** support PEP 604
`X | None` union type annotations on `Field`-declared model attributes —
only `typing.Optional[X]` works (verified with a minimal reproduction:
`Optional[str]` field construction succeeds, an equivalent `str | None`
field raises the same `TypeError` once a non-`None` value is actually
assigned). This is a real regression I had introduced earlier in this
session by "modernizing" `Optional[X]` to `X | None` per a ruff `UP045`
suggestion on `NotificationTemplate` (TASK-2153) and
`NotificationBatchRecipient` (TASK-2154), and it also affected this
task's own `RecipientIn`/`SkippedRow`. **Reverted all three files back to
`typing.Optional[X]`** and added a `# ruff: noqa: UP045` file-level
directive with an explanatory comment on each of the three files so a
future lint pass does not silently reintroduce the same runtime break.
`pytest` on this task's own test file (`test_comm_center_ingest.py`) is
unaffected by the pre-existing `navigator_session.vault`/
`navigator_eventbus` environment gaps noted in TASK-2153-2155 and **passes
in full: 10/10**.

**Deviations from spec**: none in the delivered behavior. One added test
(`test_ingest_xlsx_via_openpyxl`) beyond this task's own embedded Test
Specification, matching the broader spec §4 test list.
