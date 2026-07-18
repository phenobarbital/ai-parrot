# TASK-1813: Port DataSerializer with JSON default (brokers/serializers.py)

**Feature**: FEAT-316 — EventBus Brokers Port
**Spec**: `sdd/specs/eventbus-brokers-port.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

> **Repo**: work happens in `/home/jesuslara/proyectos/navigator-eventbus`
> (worktree `.claude/worktrees/feat-FEAT-316-eventbus-brokers-port`, branched
> from `feat-FEAT-312-eventbus-core-extraction`). All file paths below are
> relative to that worktree. The spec lives in ai-parrot's SDD tree.

---

## Context

Spec §3 Module 2. `navigator/brokers/pickle.py` hard-imports `jsonpickle`,
`msgpack`, and `cloudpickle` at module top. The port renames it to
`brokers/serializers.py` (avoiding confusion with stdlib `pickle`), switches the
default wire format to JSON via the existing `navigator_eventbus.serialization`
module (orjson-backed `JSONContent`), and makes the three heavy deps lazy
opt-ins. Every other brokers module instantiates `DataSerializer`, so this task
is the root of the dependency graph.

---

## Scope

- Create `src/navigator_eventbus/brokers/__init__.py` (minimal docstring; full
  re-exports land in TASK-1814).
- Create `src/navigator_eventbus/brokers/serializers.py` porting `DataSerializer`
  (and `ModelHandler`) from `navigator/brokers/pickle.py`:
  - `encode`/`decode` (JSON path) use `navigator_eventbus.serialization.dumps/loads`
    by default; `jsonpickle` (+ `ModelHandler` registration for
    `datamodel.Model`/`BaseModel`) becomes an opt-in path, lazy-imported.
  - `serialize`/`unserialize` (cloudpickle path) lazy-import `cloudpickle` inside
    the method, raising an actionable `RuntimeError` if missing.
  - `pack`/`unpack` (msgpack path) lazy-import `msgpack` the same way.
- Write unit tests in `tests/brokers/test_serializers.py`.

**NOT in scope**: BaseConnection/producer/consumer/wrapper (TASK-1814); any
redis/rabbitmq/sqs module; pyproject extras (TASK-1818).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `src/navigator_eventbus/brokers/__init__.py` | CREATE | Package init (docstring only for now) |
| `src/navigator_eventbus/brokers/serializers.py` | CREATE | `DataSerializer` + `ModelHandler`, JSON default |
| `tests/brokers/__init__.py` | CREATE | Test package init |
| `tests/brokers/test_serializers.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified 2026-07-18 against both repos. Use these VERBATIM.

### Verified Imports

```python
# Destination package (already exists — FEAT-312 branch):
from navigator_eventbus.serialization import dumps, loads   # src/navigator_eventbus/serialization.py:18,30
from datamodel import Model, BaseModel                      # dep already in core

# Source being ported (repo /home/jesuslara/proyectos/navigator):
# navigator/brokers/pickle.py:1-9 — jsonpickle, jsonpickle.handlers.BaseHandler,
# jsonpickle.unpickler.loadclass, msgpack, cloudpickle, base64,
# dataclasses.dataclass — ALL become lazy in the port except base64/dataclass.
```

### Existing Signatures to Use

```python
# navigator/brokers/pickle.py:12 (source to port)
class ModelHandler(BaseHandler):
    def flatten(self, obj, data): ...        # :17
    def restore(self, obj): ...              # :21
# jsonpickle.handlers.registry.register(BaseModel, ModelHandler, base=True)  # :30
# — this module-level registration must move inside the lazy jsonpickle path.

# navigator/brokers/pickle.py (source class):
class DataSerializer:                        # dataclass-style utility
    # methods: encode / decode (jsonpickle+base64), serialize / unserialize
    # (cloudpickle), pack / unpack (msgpack) — read the 92-line file in the
    # navigator repo before porting.

# Lazy-import error pattern to copy (destination repo):
# src/navigator_eventbus/serialization.py:56-62
#   try: import cloudpickle
#   except ImportError as exc:
#       raise RuntimeError(
#           "cloudpickle is required for pickle serialization. "
#           "Install it with: pip install navigator-eventbus[pickle]"
#       ) from exc
```

### Does NOT Exist

- ~~`navigator_eventbus.brokers`~~ — does NOT exist yet; this task creates it.
- ~~`navigator_eventbus.brokers.pickle`~~ — will NOT exist; the module is
  `serializers.py` by design.
- ~~`serialization.JSONContent` re-export~~ — the destination module exposes
  `dumps`/`loads` (and `dumps_pickle`/`loads_pickle`), not the raw `JSONContent`
  instance; do not import `JSONContent` from `navigator_eventbus.serialization`.

---

## Implementation Notes

### Pattern to Follow

- Copy the lazy-import + actionable-`RuntimeError` pattern from
  `src/navigator_eventbus/serialization.py:56-62` for cloudpickle, msgpack, and
  jsonpickle (`[pickle]` extra for cloudpickle; `[serializer]` for msgpack/jsonpickle).
- JSON default: `encode`/`decode` should try plain JSON via
  `navigator_eventbus.serialization.dumps/loads` first; the jsonpickle-based
  encode/decode (which handles arbitrary objects + `ModelHandler`) is used only
  when jsonpickle is installed and the payload is not JSON-safe (or an explicit
  flag is passed). Fallback is ALWAYS JSON via orjson (spec §8, resolved).

### Key Constraints

- Google-style docstrings + strict type hints on every method.
- `self.logger`/module logger — no prints.
- Module must import cleanly with NONE of cloudpickle/msgpack/jsonpickle installed.

### References in Codebase

- `navigator/brokers/pickle.py` (navigator repo) — source of the port (92 LOC).
- `src/navigator_eventbus/serialization.py` — JSON helpers + lazy pattern.

---

## Acceptance Criteria

- [ ] `from navigator_eventbus.brokers.serializers import DataSerializer` works
  without cloudpickle/msgpack/jsonpickle installed.
- [ ] `encode`/`decode` round-trip dicts/lists/strings via JSON (orjson) by default.
- [ ] `serialize`/`unserialize` raise actionable `RuntimeError` mentioning the
  `[pickle]` extra when cloudpickle is missing; work when installed.
- [ ] `pack`/`unpack` same behavior for msgpack (`[serializer]` extra).
- [ ] All tests pass: `pytest tests/brokers/test_serializers.py -v`
- [ ] `ruff check src/navigator_eventbus/brokers/` passes.

---

## Test Specification

```python
# tests/brokers/test_serializers.py
import pytest
from navigator_eventbus.brokers.serializers import DataSerializer


@pytest.fixture
def serializer():
    return DataSerializer()


class TestDataSerializerJSON:
    def test_json_roundtrip_default(self, serializer):
        payload = {"event": "test", "n": 42, "nested": {"a": [1, 2]}}
        encoded = serializer.encode(payload)
        assert serializer.decode(encoded) == payload

    def test_json_is_default_format(self, serializer):
        # encoded output of a plain dict must be valid JSON, not pickle bytes
        import json
        encoded = serializer.encode({"k": "v"})
        assert json.loads(encoded) == {"k": "v"}


class TestOptionalBackends:
    def test_cloudpickle_optional(self, serializer, monkeypatch):
        # simulate missing cloudpickle → actionable error
        import builtins
        real_import = builtins.__import__
        def fake(name, *a, **kw):
            if name == "cloudpickle":
                raise ImportError(name)
            return real_import(name, *a, **kw)
        monkeypatch.setattr(builtins, "__import__", fake)
        with pytest.raises(RuntimeError, match=r"\[pickle\]|cloudpickle"):
            serializer.serialize(object())
```

---

## Agent Instructions

1. **Read the spec** (`sdd/specs/eventbus-brokers-port.spec.md` in ai-parrot) §3 Module 2, §7.
2. **Read the full source** `navigator/brokers/pickle.py` (navigator repo) before porting.
3. **Verify the Codebase Contract** — confirm imports/lines above still hold.
4. **Update status** in `sdd/tasks/index/eventbus-brokers-port.json` → `"in-progress"`.
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-18
**Notes**: Ported `DataSerializer`/`ModelHandler` from `navigator/brokers/pickle.py`
into `src/navigator_eventbus/brokers/serializers.py` (worktree
`.claude/worktrees/feat-FEAT-316-eventbus-brokers-port` in
`navigator-eventbus`, commit `23af2ad`). `encode`/`decode` try
`navigator_eventbus.serialization.dumps/loads` (orjson) first and fall back to
a lazily-imported `jsonpickle` path (with `ModelHandler` registered on first
use for `datamodel.Model`/`BaseModel`) only when JSON fails or
`use_jsonpickle=True`. `serialize`/`unserialize` (cloudpickle) and `pack`/
`unpack` (msgpack) lazy-import their backend inside the method and raise an
actionable `RuntimeError` naming the `[pickle]`/`[serializer]` extra when
missing. Verified the module imports and JSON-roundtrips cleanly with
cloudpickle/msgpack blocked via a mocked `builtins.__import__` (jsonpickle
itself is an existing transitive import of `navconfig.kardex`, unrelated to
this module, so it can't be excluded from the whole-package import — noted
for the record, not a deviation in `brokers.serializers` itself). Added extra
test coverage (cloudpickle/msgpack roundtrips, jsonpickle `ModelHandler`)
beyond the task's Test Specification scaffold; all pass except
`test_msgpack_roundtrip`, which correctly `importorskip`s since `msgpack`
isn't a project dependency yet (added in TASK-1818). `pytest
tests/brokers/test_serializers.py -v` → 6 passed, 1 skipped. `ruff check
src/navigator_eventbus/brokers/` clean.

**Deviations from spec**: none
