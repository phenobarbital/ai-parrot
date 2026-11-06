# TASK-5239: Capped body reader and 413 response helpers in `a2ui_wire`

**Feature**: FEAT-822 — Enforce A2UI request body-size limits before parsing
**Spec**: `sdd/specs/fixgroup-adbf411ace18.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:bf978b6bae8a`

---

## Context

`issue:bf978b6bae8a` (major, from the FEAT-650 review, items I2 + S3): every
A2UI body-size limit in `parrot_formdesigner/api/handlers.py` is advisory. All
four existing guards are spelled
`if request.content_length is not None and request.content_length > a2ui_wire.A2UI_MAX_BODY_BYTES:`
(handlers.py:1265, 1425, 1629, 2073), which fails open for
`Transfer-Encoding: chunked` (where `content_length` is `None`), and three of
the four run *after* `await request.json()` has already buffered and parsed the
body.

This task builds the single enforcement primitive the handlers will use. It
touches **only** `a2ui_wire.py` and its new test file; migrating the handlers is
TASK-5240 and the `translate_form` input validation is TASK-5241.

## Scope

- Add `OverSizedBody`, `read_capped_body`, `read_capped_json`,
  `oversized_json_response`, `oversized_a2ui_response`, `is_a2ui_content_type`
  and the `A2UI_MAX_SCHEMA_DEPTH` constant to
  `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py`.
- Create `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py`
  with the M1 unit tests.

**NOT in scope**:
- Any edit to `handlers.py` (TASK-5240 / TASK-5241).
- Changing the value or env-var name of `A2UI_MAX_BODY_BYTES`.
- Multipart / file-upload limits.
- `issue:e963c78a05de` (CLI blocking Path calls, export filename sanitisation).

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` | MODIFY |
| `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` | CREATE |

---

## Codebase Contract (Anti-Hallucination)

> Verified at `HEAD=ca4b0fc523`.

### Verified Imports

```python
from __future__ import annotations   # a2ui_wire.py:21 — already present
import os                            # a2ui_wire.py:23 — already present
from typing import Any               # a2ui_wire.py:24 — already present
from aiohttp import web              # a2ui_wire.py:26 — already present
```

`json` is **not** currently imported in `a2ui_wire.py` — this task adds
`import json` to the stdlib import block.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py
A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))  # line 39, occurrences: 1
def is_a2ui_surface_body(request: web.Request, body: Any) -> bool: ...  # line 126, occurrences: 1
def is_a2ui_request(request: web.Request, body: Any) -> bool: ...       # line 140, occurrences: 1
def a2ui_response(envelopes: list[dict[str, Any]], *, status: int) -> web.Response: ...  # line 293, occurrences: 1
```

`is_a2ui_surface_body` already uses the literal `"application/a2ui+json"`
without importing `parrot.*` (line 136) — `is_a2ui_content_type` follows the
same no-parrot-import rule, because `parrot.outputs.a2ui` is an OPTIONAL
dependency of this package (module docstring, a2ui_wire.py:12-17).

The A2UI error envelope is built via a **lazy local import** (the pattern used
at handlers.py:1630):

```python
from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope
```

### Does NOT Exist

Verified absent across `packages/parrot-formdesigner/src` and
`packages/parrot-formdesigner/tests` (combined grep → 0 hits):

- `read_capped_body`, `read_capped_json`, `OverSizedBody`,
  `oversized_json_response`, `oversized_a2ui_response`,
  `is_a2ui_content_type`, `A2UI_MAX_SCHEMA_DEPTH` — **all created here**.
- `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` — new.
- There is **no** existing shared body-reading helper in this package; every
  handler calls `await request.json()` directly (21 occurrences in
  `handlers.py`).
- There is no `a2ui_wire.MAX_BODY`, no `a2ui_wire.read_body`, no
  `BodyTooLarge` exception — do not reference them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#a2ui_response",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#is_a2ui_surface_body",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py#is_a2ui_request"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Resolve the cap at call time, not import time.** `A2UI_MAX_BODY_BYTES` is
  read from the environment at module import, and the tests monkeypatch the
  module attribute. So `limit=None` must resolve via
  `globals()`/module attribute lookup inside the function body, never as a
  default argument value (`limit: int = A2UI_MAX_BODY_BYTES` would freeze it).
- **`read(limit + 1)` is the whole trick.** Asking the stream for one byte more
  than the cap proves an over-cap body without trusting `Content-Length` and
  without buffering the rest. A body of exactly `limit` bytes must be accepted.
- **Never import `parrot.*` at module level** — the package's optional-extra
  rule (a2ui_wire.py:12-17). `oversized_a2ui_response` imports
  `error_envelope` locally inside the function.
- `aiohttp`'s `StreamReader.read(n)` returns *up to* `n` bytes and may return
  fewer per call, so loop until either `limit + 1` bytes are collected or the
  stream is exhausted.

### References in Codebase

- `a2ui_wire.a2ui_response` (line 293) — the framing helper for A2UI replies.
- `handlers.py:1630-1637` — the existing A2UI 413 envelope shape to preserve.
- `handlers.py:1266` — the existing plain-JSON 413 body shape to preserve.

---

## Implementation Blueprint

### Steps (in order)

1. Add `import json` to the stdlib block of `a2ui_wire.py` — the capped reader
   decodes JSON itself instead of calling `request.json()`, because
   `request.json()` reads the whole stream before we can bound it.
2. Add `A2UI_MAX_SCHEMA_DEPTH` next to `A2UI_MAX_BODY_BYTES` — it belongs with
   the other caps, and TASK-5241 imports it from here; keeping every cap in one
   module means one place to audit.
3. Add `OverSizedBody` and the five helpers at the end of the module — appending
   avoids touching any existing function and keeps the diff reviewable.
4. Write the M1 unit tests with a fake request object, because the helpers only
   need `.content.read` and `.content_type` and a real aiohttp server would make
   the "never reads the whole stream" assertion impossible to make precisely.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` (MODIFY) — import block

```python
# occurrences: 1 (verified: grep -c 'import os' a2ui_wire.py)
# AFTER — insert below `import os` (verified: a2ui_wire.py:23)
import json
```

**Why**: the capped reader must decode the bytes it read itself; calling
`request.json()` would re-read (and fully buffer) the stream, which is the bug.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` (MODIFY) — cap constant

```python
# occurrences: 1 (verified: grep -c 'A2UI_MAX_BODY_BYTES = int(' a2ui_wire.py)
# AFTER — insert below `A2UI_MAX_BODY_BYTES = int(os.environ.get("A2UI_MAX_DATA_MODEL_BYTES", str(1024 * 1024)))` (verified: a2ui_wire.py:39)

#: Maximum nesting depth accepted for an inbound JSON Schema in
#: ``translate_form`` (FEAT-822 / issue:bf978b6bae8a S3). Checked iteratively,
#: so a hostile schema cannot exhaust the Python stack while being validated.
A2UI_MAX_SCHEMA_DEPTH = int(os.environ.get("A2UI_MAX_SCHEMA_DEPTH", "32"))
```

**Why**: TASK-5241 needs this cap and `a2ui_wire` is already the module that
owns `A2UI_MAX_BODY_BYTES`; putting it here keeps TASK-5241 confined to
`handlers.py` so the two tasks never edit the same file region.

### `packages/parrot-formdesigner/src/parrot_formdesigner/api/a2ui_wire.py` (MODIFY) — helpers

```python
# occurrences: 1 (verified: grep -c 'def a2ui_response(' a2ui_wire.py)
# AFTER — append at END OF FILE, below the body of `def a2ui_response(` (verified: a2ui_wire.py:293, last function in the module)

class OverSizedBody(Exception):
    """Raised when a request body exceeds the configured byte cap.

    Attributes:
        limit: The cap, in bytes, that the body exceeded.
    """

    def __init__(self, *, limit: int) -> None:
        super().__init__(f"request body exceeds {limit} bytes")
        self.limit = limit


def is_a2ui_content_type(request: web.Request) -> bool:
    """Return whether the request declares the A2UI media type.

    Headers-only counterpart to :func:`is_a2ui_request`, for the oversize
    branch, which must choose an error shape BEFORE the body is parsed.
    Deliberately has no ``parrot.*`` import so it works without the optional
    A2UI extra installed. Never raises.
    """
    return request.content_type == "application/a2ui+json"


async def read_capped_body(request: web.Request, *, limit: int | None = None) -> bytes:
    """Read the request body, refusing to buffer more than ``limit`` bytes.

    Reads at most ``limit + 1`` bytes from ``request.content``; the extra byte
    is what proves the body is over the cap without trusting the client's
    ``Content-Length``. This works identically for a chunked body, where
    ``request.content_length`` is ``None``.

    Args:
        request: The incoming aiohttp request.
        limit: Byte cap; ``None`` resolves to :data:`A2UI_MAX_BODY_BYTES` at
            call time (so the module attribute stays monkeypatchable).

    Returns:
        The body bytes (at most ``limit``).

    Raises:
        OverSizedBody: when the body exceeds ``limit``.
    """
    cap = A2UI_MAX_BODY_BYTES if limit is None else limit
    chunks: list[bytes] = []
    size = 0
    while size <= cap:
        # FILL IN: choose the per-call read size — bounded by `cap + 1 - size`
        # so the loop can never request more than one byte past the cap.
        chunk = await request.content.read(cap + 1 - size)
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    if size > cap:
        raise OverSizedBody(limit=cap)
    return b"".join(chunks)


async def read_capped_json(request: web.Request, *, limit: int | None = None) -> Any:
    """Read and JSON-decode a request body under a hard size cap.

    The cap is enforced before any parsing, so an over-cap body raises
    :class:`OverSizedBody` even when its bytes are not valid JSON.

    Args:
        request: The incoming aiohttp request.
        limit: Byte cap; ``None`` resolves to :data:`A2UI_MAX_BODY_BYTES`.

    Returns:
        The decoded JSON value.

    Raises:
        OverSizedBody: when the body exceeds ``limit``.
        json.JSONDecodeError: when the capped bytes are not valid JSON.
    """
    raw = await read_capped_body(request, limit=limit)
    # FILL IN: decide the empty-body behaviour — bounded by AC6 (call sites keep
    # their existing `except (json.JSONDecodeError, ValueError): 400` branch, so
    # an empty body must reach that branch rather than returning None).
    return json.loads(raw)


def oversized_json_response(limit: int) -> web.Response:
    """Return the plain-JSON 413 used by non-A2UI routes.

    Shape preserved verbatim from the guard this replaces (handlers.py:1266).
    """
    return web.json_response({"error": "body too large", "max_bytes": limit}, status=413)


def oversized_a2ui_response(surface_id: str, message: str = "body too large") -> web.Response:
    """Return the A2UI-enveloped 413 used by A2UI routes.

    Shape preserved verbatim from the guard this replaces (handlers.py:1630).
    """
    from parrot.outputs.a2ui.runtime.models import A2UIErrorCode, error_envelope

    return a2ui_response(
        [error_envelope(A2UIErrorCode.INTERNAL, message, surface_id=surface_id)],
        status=413,
    )
```

**Why this shape**: `read_capped_body` is the only place that touches the
stream, so there is exactly one enforcement point to audit; `read_capped_json`
layers parsing on top so a call site can swap `await request.json()` for it
one-for-one. The two response helpers exist so TASK-5240 preserves each route's
current error body (spec AC5) without duplicating the envelope construction at
six sites. `is_a2ui_content_type` is headers-only because the oversize branch
runs before a body exists.

### `packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py` (CREATE)

```python
"""Unit tests for the FEAT-822 capped body reader (issue:bf978b6bae8a).

Spec: ``sdd/specs/fixgroup-adbf411ace18.spec.md`` §4.
"""

from __future__ import annotations

import json

import pytest

from parrot_formdesigner.api import a2ui_wire


class _FakeContent:
    """Minimal ``StreamReader`` stand-in that records every read size."""

    def __init__(self, payload: bytes, *, chunk_size: int | None = None) -> None:
        self._payload = payload
        self._pos = 0
        self._chunk_size = chunk_size
        self.requested: list[int] = []

    async def read(self, n: int = -1) -> bytes:
        self.requested.append(n)
        # FILL IN: return at most `n` bytes from `self._payload`, honouring
        # `self._chunk_size` when set — bounded by the requirement that the
        # reader must tolerate short reads (aiohttp may return fewer than n).
        ...


class _FakeRequest:
    """Minimal ``web.Request`` stand-in for the reader helpers."""

    def __init__(self, payload: bytes, *, content_type: str = "application/json", chunked: bool = False) -> None:
        self.content = _FakeContent(payload)
        self.content_type = content_type
        #: chunked requests report no declared length — the bypass this fixes
        self.content_length = None if chunked else len(payload)


@pytest.fixture
def tiny_cap(monkeypatch):
    """Shrink the cap so tests never allocate megabytes."""
    monkeypatch.setattr(a2ui_wire, "A2UI_MAX_BODY_BYTES", 1024)
    return 1024


async def test_read_capped_body_accepts_exactly_limit(tiny_cap):
    """AC1: a body of exactly `limit` bytes is returned intact."""
    # FILL IN: assert the returned bytes equal the payload — bounded by AC6.
    ...


async def test_read_capped_body_rejects_over_limit(tiny_cap):
    """AC1: `limit + 1` bytes raises OverSizedBody with the right limit."""
    ...


async def test_read_capped_body_rejects_chunked_over_limit(tiny_cap):
    """AC2: an over-cap body with `content_length is None` still raises."""
    ...


async def test_read_capped_body_never_reads_whole_stream(tiny_cap):
    """AC1: the reader asks for at most `limit + 1` bytes in total."""
    # FILL IN: assert sum(content.requested) <= tiny_cap + 1 — bounded by the
    # requirement that the cap prevents the allocation, not just the response.
    ...


async def test_read_capped_json_raises_before_parse(tiny_cap):
    """AC1/AC3: over-cap invalid JSON raises OverSizedBody, not JSONDecodeError."""
    ...


async def test_read_capped_json_decodes_under_cap(tiny_cap):
    """AC6: an under-cap body decodes exactly as `request.json()` would."""
    ...


def test_is_a2ui_content_type_headers_only():
    """AC5: the predicate is true only for the A2UI media type, never raises."""
    ...


def test_oversized_json_response_shape():
    """AC5: plain 413 keeps `{"error","max_bytes"}`."""
    ...
```

**Why this shape**: the fake request records every requested read size, which
is the only way to assert the reader never buffers the whole stream — the
property that actually fixes the DoS. Real aiohttp test-client coverage of the
routes belongs to TASK-5240.

### FILL IN checklist

- [ ] `read_capped_body`: per-call read size bounded by `cap + 1 - size`.
- [ ] `read_capped_json`: empty-body behaviour reaches the call site's existing
      400 branch (AC6).
- [ ] `_FakeContent.read`: honour short reads and `chunk_size`.
- [ ] All eight test bodies.

---

## Acceptance Criteria

- [ ] `OverSizedBody`, `read_capped_body`, `read_capped_json`,
      `oversized_json_response`, `oversized_a2ui_response`,
      `is_a2ui_content_type`, `A2UI_MAX_SCHEMA_DEPTH` exist in `a2ui_wire.py`.
- [ ] A body of exactly `limit` bytes is accepted; `limit + 1` raises
      `OverSizedBody` (spec AC1).
- [ ] The cap holds when `content_length is None` (spec AC2).
- [ ] `read_capped_json` raises `OverSizedBody` before parsing (spec AC3).
- [ ] No module-level `parrot.*` import is added to `a2ui_wire.py`.
- [ ] `limit=None` resolves `A2UI_MAX_BODY_BYTES` at call time (monkeypatch in
      the `tiny_cap` fixture takes effect).
- [ ] `ruff check` clean on both files (spec AC9).

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py -q`

## Test Specification

The eight tests listed in the blueprint, covering spec §4 rows
`test_read_capped_body_*`, `test_read_capped_json_raises_before_parse`.
Run with `PYTHONPATH=packages/parrot-formdesigner/src:packages/ai-parrot/src`.

## Agent Instructions

Touch only the two files in the table. Do not edit `handlers.py` — that is
TASK-5240 and TASK-5241, which run after this task.

## Completion Note

Implemented as specified. `a2ui_wire.py` gains `A2UI_MAX_SCHEMA_DEPTH`,
`OverSizedBody`, `is_a2ui_content_type`, `read_capped_body`,
`read_capped_json`, `oversized_json_response` and `oversized_a2ui_response`;
`import json` added. No module-level `parrot.*` import was introduced — the
error-envelope import stays local to `oversized_a2ui_response`.

`read_capped_body` reads at most `limit + 1` bytes in a loop that tolerates
short reads, so the cap holds for a chunked body (`content_length is None`)
and fires before any parsing. The cap resolves from the module attribute at
call time, which keeps it monkeypatchable.

Validation: `pytest packages/parrot-formdesigner/tests/unit/api/test_a2ui_body_limits.py -q`
→ **14 passed**. `ruff check` clean on both files. Full package suite on this
branch: 4237 passed, 2 failed — both pre-existing
(`assert '2.1.1' == '1.2.4'` in `test_init_imports_metadata_only.py` and
`test_version_and_docs.py`, from the 2.1.1 release bump, unrelated to this task).

Note for the feature: TASK-5240 was attempted and reverted — see the
AMENDMENT in the spec. These helpers are landed and are required by either
seam, but no handler calls them yet, so the ledger issue stays open.
