---
type: Wiki Overview
title: 'TASK-1210: `configure()`-time prefix and collision validation'
id: doc:sdd-tasks-completed-task-1210-configure-time-prefix-and-collision-checks-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-171 made `_compute_active_tools` prefix-aware and added a
relates_to:
- concept: mod:parrot.bots.database.agent
  rel: mentions
- concept: mod:parrot.bots.database.models
  rel: mentions
- concept: mod:parrot.bots.database.toolkits._internal
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
---

# TASK-1210: `configure()`-time prefix and collision validation

**Feature**: FEAT-172 — Mandatory `tool_prefix` + Eager Collision Detection
**Spec**: `sdd/specs/databaseagent-mandatory-prefix-collision.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1208 (FEAT-171)
**Assigned-to**: unassigned

---

## Context

FEAT-171 made `_compute_active_tools` prefix-aware and added a
deduped runtime warning for collisions. FEAT-172 is the next
defensive layer: validate at `DatabaseAgent.configure()` so a
misconfigured agent never reaches a usable state. Three checks at
`configure()` time:

1. **Prefix presence** — reject `tool_prefix in (None, "")`.
2. **Prefix shape** (Q2) — reject anything not matching
   `^[A-Za-z][A-Za-z0-9_]*$`.
3. **Collision** — reject two toolkits exposing the same
   fully-qualified tool name.

Also: tighten FEAT-171's runtime warning message to note it is a
defensive fallback post-FEAT-172.

Implements **Module 1 + Module 2** of the spec.

---

## Scope

- Add a module-level compiled regex in `agent.py`:
  ```python
  _TOOL_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
  ```
- Insert three validation passes inside
  `DatabaseAgent.configure()` (agent.py:134), **after** the
  existing `for tk in self.toolkits` loop that calls
  `tk.start()` (ends at agent.py:178) and **before**
  `self._internal_toolkit = DatabaseAgentToolkit()` (agent.py:180):
  - Pass A — prefix presence (raise `ValueError` per §2 spec
    text for empty / `None`).
  - Pass B — prefix shape against `_TOOL_PREFIX_PATTERN`
    (raise `ValueError` per §2 spec text).
  - Pass C — collision detection: walk
    `tk.list_tool_names()` for each toolkit; accumulate in
    `Dict[str, type]`; raise `ValueError` per §2 spec text on
    second occurrence of any name.
- Update the `configure()` docstring (agent.py:135-140) to list
  the new failure modes:
  - `ValueError` if a toolkit's `tool_prefix` is empty.
  - `ValueError` if a toolkit's `tool_prefix` is not
    identifier-safe.
  - `ValueError` if two toolkits collide on a fully-qualified
    tool name.
- **Module 2** — update the runtime collision warning emitted by
  `_compute_active_tools` (introduced by FEAT-171 / TASK-1208) so
  the message ends with:
  `... This should have been caught at configure() time — please file a bug.`
  No behaviour change; semantic change only in the log string.
- Reuse and extend the `MockDatabaseToolkit` factory from FEAT-171's
  conftest (`tests/unit/bots/database/conftest.py`).
- Unit tests in
  `packages/ai-parrot/tests/unit/bots/database/test_configure_validation.py`
  (CREATE):
  - `test_configure_rejects_none_prefix`
  - `test_configure_rejects_empty_prefix`
  - `test_configure_rejects_non_identifier_prefix` (parametrized
    over `"my-db"`, `"db "`, `"123db"`, `"db.foo"`)
  - `test_configure_accepts_valid_prefix`
  - `test_configure_accepts_identifier_prefixes` (parametrized
    over `"db"`, `"pg"`, `"bq"`, `"influx"`, `"elastic_v2"`, `"X1"`)
  - `test_configure_rejects_collision_same_prefix`
  - `test_configure_rejects_collision_idempotent_naming`
  - `test_configure_accepts_distinct_prefixes_same_logical_name`
  - `test_runtime_collision_warning_post_configure` — force a
    runtime collision by mutating `self.toolkits` after
    `configure()`; assert the warning fires and ends with the
    new "should have been caught" suffix.
  - `test_failed_validation_leaves_internal_toolkit_none` —
    after a `ValueError` from `configure()`, assert
    `agent._internal_toolkit is None`.

**NOT in scope**:
- Integration smoke test (`test_sql_analyst_unchanged_after_feat_172`)
  — that lives in TASK-1211.
- `tool_prefix` validation on `AbstractToolkit` globally
  (explicit non-goal in spec §1).
- Migrating `DatabaseAgentToolkit` (FEAT-173).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/database/agent.py` | MODIFY | Add `_TOOL_PREFIX_PATTERN`; insert three validation passes in `configure()`; update docstring; tighten runtime warning message |
| `packages/ai-parrot/tests/unit/bots/database/conftest.py` | MODIFY | Extend the FEAT-171 `mock_toolkit_factory` so it accepts `tool_prefix` literally (including `None` / `""` / arbitrary strings) for negative-path tests |
| `packages/ai-parrot/tests/unit/bots/database/test_configure_validation.py` | CREATE | Unit tests for all checks + warning-suffix change |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# bots/database/agent.py — already imports
import logging
import re                                              # ← ADD this import
import warnings                                         # ← added by TASK-1208
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from parrot.bots.database.toolkits._internal import DatabaseAgentToolkit
from parrot.bots.database.toolkits.base import DatabaseToolkit
from parrot.bots.database.models import OutputComponent
```

### Existing Class Signatures (verified at HEAD on dev, 2026-05-15)
```python
# packages/ai-parrot/src/parrot/bots/database/agent.py
class DatabaseAgent(BasicAgent):                              # line 85
    self.toolkits: List[DatabaseToolkit]                      # set in __init__:120
    self._toolkit_map: Dict[str, DatabaseToolkit]             # set in __init__:127
    self._internal_toolkit: Optional[DatabaseAgentToolkit]    # set in __init__:128

    async def configure(self, app: Any = None) -> None:       # line 134
        # Current flow:
        #   141-152  : compute primary_schema, allowed_schemas; create router
        #   154-178  : per-toolkit: register in _toolkit_map, wire
        #              cache_partition, retry_config, call tk.start()
        #   180      : self._internal_toolkit = DatabaseAgentToolkit()
        #   182-186  : log info
        # >>> INSERT VALIDATION PASSES BETWEEN line 178 AND line 180 <<<

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit:
    tool_prefix: Optional[str] = None                          # line 242
    prefix_separator: str = "_"                                 # line 245
    def list_tool_names(self) -> List[str]:                    # line 448
        """Triggers _generate_tools() lazily on first call."""

# packages/ai-parrot/src/parrot/bots/database/toolkits/base.py
class DatabaseToolkit(AbstractToolkit, ABC):                   # line 78
    tool_prefix: str = "db"                                     # line 93
```

### Audit Reference (already done — Q1 of FEAT-172)
Every concrete `DatabaseToolkit` subclass in the parrot repo
inherits the default `tool_prefix = "db"`. None set `None` or `""`.

| Toolkit | File | Prefix |
|---|---|---|
| `SQLToolkit` | `toolkits/sql.py:61` | `"db"` (inherits) |
| `PostgresToolkit` | `toolkits/postgres.py:28` | `"db"` (inherits) |
| `BigQueryToolkit` | `toolkits/bigquery.py:19` | `"db"` (inherits) |
| `InfluxDBToolkit` | `toolkits/influx.py:15` | `"db"` (inherits) |
| `ElasticToolkit` | `toolkits/elastic.py:15` | `"db"` (inherits) |
| `DocumentDBToolkit` | `toolkits/documentdb.py:15` | `"db"` (inherits) |

### Does NOT Exist
- ~~`AbstractDatabaseToolkit`~~ — the class is named `DatabaseToolkit`
  (verified 2026-05-15). Do not import or reference any
  `AbstractDatabaseToolkit` symbol.
- ~~`ToolNameCollisionError`~~ — that name exists in parrot but is
  raised by `ToolManager.register_tool`. This task uses plain
  `ValueError`.
- ~~`DatabaseAgent.validate_toolkits()`~~ — does not exist.
  Validation lives inline in `configure()`.

---

## Implementation Notes

### Exact error messages (spec §2, after Q2 resolution)
```python
# Pass A — missing / empty prefix
raise ValueError(
    f"DatabaseToolkit subclasses must declare a non-empty "
    f"tool_prefix; {type(tk).__name__} has tool_prefix={tk.tool_prefix!r}. "
    f"Set `tool_prefix` on the toolkit class (e.g. \"db\", \"bq\")."
)

# Pass B — non-identifier-safe prefix (Q2)
raise ValueError(
    f"DatabaseToolkit subclasses must declare an identifier-safe "
    f"tool_prefix matching {_TOOL_PREFIX_PATTERN.pattern!r}; "
    f"{type(tk).__name__} has tool_prefix={tk.tool_prefix!r}. "
    f"Use only ASCII letters, digits, and underscores, starting "
    f"with a letter."
)

# Pass C — collision
raise ValueError(
    f"Tool name collision while configuring DatabaseAgent: "
    f"{full_name!r} is exposed by both {prior_owner.__name__} and "
    f"{type(tk).__name__}. Two toolkits must not register the same "
    f"fully-qualified tool name. Change one toolkit's tool_prefix or "
    f"remove the duplicate from one of the toolkits."
)
```

Use these strings **verbatim** — acceptance criteria pin them.

### Validation-pass insertion shape
```python
# bots/database/agent.py — between line 178 and line 180

# --- FEAT-172 Pass A: prefix presence ---
for tk in self.toolkits:
    if not tk.tool_prefix:
        raise ValueError(...)  # see above

# --- FEAT-172 Pass B: identifier-safe shape ---
for tk in self.toolkits:
    if not _TOOL_PREFIX_PATTERN.fullmatch(tk.tool_prefix):
        raise ValueError(...)

# --- FEAT-172 Pass C: collision detection ---
fully_qualified_owners: Dict[str, type] = {}
for tk in self.toolkits:
    for full_name in tk.list_tool_names():
        if full_name in fully_qualified_owners:
            prior_owner = fully_qualified_owners[full_name]
            raise ValueError(...)
        fully_qualified_owners[full_name] = type(tk)

# Continue with existing line 180:
self._internal_toolkit = DatabaseAgentToolkit()
```

Order matters: A before B before C. If A fails, B and C never run
(they can't safely access a missing prefix). If B fails, C never
runs (a malformed prefix may produce nonsense full-names).

### Runtime warning suffix (Module 2)
TASK-1208 introduced a `logger.warning(...)` in
`_compute_active_tools` for runtime collisions. Modify the message
to end with:

```
... This should have been caught at configure() time — please file a bug.
```

Keep the deduping logic from TASK-1208 unchanged.

### `list_tool_names` side-effect awareness
`list_tool_names()` lazily triggers `_generate_tools()` on first
call. After Pass C, the toolkit's tool cache is populated. This is
fine — `_compute_active_tools` will hit a warm cache via
`tk.get_tool(...)`. No additional latency on the request path.

### Test isolation
`DatabaseAgent.configure()` mutates `self._toolkit_map` and
`self.query_router` **before** the new validation passes. On
validation failure, those have partial state, but
`self._internal_toolkit` is still `None`. The
`test_failed_validation_leaves_internal_toolkit_none` test pins
this invariant. Document the partial-state caveat in the
docstring so callers don't reuse a failed agent — they should
construct a fresh `DatabaseAgent` instance.

### Mock fixture extension
The FEAT-171 conftest (created by TASK-1208) provides
`MockDatabaseToolkit(DatabaseToolkit)` and a
`mock_toolkit_factory` accepting `tool_prefix`. For FEAT-172, the
factory must allow passing arbitrary strings (and `None`/`""`)
without coercion so negative-path tests can exercise each
validation pass. If the FEAT-171 factory already accepts arbitrary
values, no change needed; otherwise extend it.

### Collision tests — idempotent naming edge case
The `_generate_tools()` prefix rewrite is idempotent: a method
named `db_foo` on a toolkit with `tool_prefix="db"` is registered
as `db_foo` (not `db_db_foo`). Test:

```python
# Two MockDatabaseToolkit instances:
#   tk_a: tool_prefix="db", method `db_search_schema`  → full name "db_search_schema"
#   tk_b: tool_prefix="db", method `search_schema`     → full name "db_search_schema"
# configure() must reject this pair.
```

---

## Acceptance Criteria

- [ ] `_TOOL_PREFIX_PATTERN` exists at module scope in `agent.py`
      with the pattern `^[A-Za-z][A-Za-z0-9_]*$`.
- [ ] `configure()` raises `ValueError` with the documented
      message format when any toolkit's `tool_prefix` is `None` or
      `""`.
- [ ] `configure()` raises `ValueError` with the documented
      message format when any toolkit's `tool_prefix` does not
      match the regex.
- [ ] `configure()` raises `ValueError` with the documented
      message format when two toolkits register the same
      fully-qualified tool name.
- [ ] On any validation failure, `agent._internal_toolkit` is
      `None` (no partial-state agent leaks).
- [ ] The runtime warning emitted by `_compute_active_tools` ends
      with `"This should have been caught at configure() time —
      please file a bug."`.
- [ ] All existing tests still pass (especially TASK-1208's unit
      tests — they construct `DatabaseAgent` directly and may need
      a `tool_prefix` on the Mock).
- [ ] `pytest packages/ai-parrot/tests/unit/bots/database/test_configure_validation.py -v`
      passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/bots/database/test_configure_validation.py
import re
import pytest

from parrot.bots.database.agent import (
    DatabaseAgent,
    _TOOL_PREFIX_PATTERN,
)
from parrot.bots.database.models import OutputComponent


class TestPrefixPresence:
    async def test_rejects_none_prefix(self, mock_toolkit_factory):
        tk = mock_toolkit_factory(tool_prefix=None)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(ValueError, match=r"must declare a non-empty"):
            await agent.configure()

    async def test_rejects_empty_prefix(self, mock_toolkit_factory):
        tk = mock_toolkit_factory(tool_prefix="")
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(ValueError, match=r"must declare a non-empty"):
            await agent.configure()


class TestPrefixShape:
    @pytest.mark.parametrize("bad", ["my-db", "db ", "123db", "db.foo"])
    async def test_rejects_non_identifier_prefix(
        self, mock_toolkit_factory, bad,
    ):
        tk = mock_toolkit_factory(tool_prefix=bad)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(
            ValueError,
            match=re.escape(_TOOL_PREFIX_PATTERN.pattern),
        ):
            await agent.configure()

    @pytest.mark.parametrize(
        "good", ["db", "pg", "bq", "influx", "elastic_v2", "X1"],
    )
    async def test_accepts_identifier_prefixes(
        self, mock_toolkit_factory, good,
    ):
        tk = mock_toolkit_factory(tool_prefix=good)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        await agent.configure()  # must not raise


class TestCollision:
    async def test_rejects_collision_same_prefix(self, mock_toolkit_factory):
        tk_a = mock_toolkit_factory(tool_prefix="dup")
        tk_b = mock_toolkit_factory(tool_prefix="dup")
        agent = DatabaseAgent(name="t", toolkits=[tk_a, tk_b])
        with pytest.raises(ValueError, match=r"Tool name collision"):
            await agent.configure()

    async def test_rejects_collision_idempotent_naming(
        self, mock_toolkit_factory,
    ):
        # tk_a: method `db_search_schema` with prefix `"db"` → full name `db_search_schema`
        # tk_b: method `search_schema` with prefix `"db"` → full name `db_search_schema`
        tk_a = mock_toolkit_factory(
            tool_prefix="db", method_name="db_search_schema",
        )
        tk_b = mock_toolkit_factory(
            tool_prefix="db", method_name="search_schema",
        )
        agent = DatabaseAgent(name="t", toolkits=[tk_a, tk_b])
        with pytest.raises(ValueError, match=r"Tool name collision"):
            await agent.configure()

    async def test_accepts_distinct_prefixes_same_logical_name(
        self, mock_toolkit_factory,
    ):
        tk_a = mock_toolkit_factory(tool_prefix="db")
        tk_b = mock_toolkit_factory(tool_prefix="mk")
        agent = DatabaseAgent(name="t", toolkits=[tk_a, tk_b])
        await agent.configure()  # must not raise


class TestPartialStateSafety:
    async def test_failed_validation_leaves_internal_toolkit_none(
        self, mock_toolkit_factory,
    ):
        tk = mock_toolkit_factory(tool_prefix=None)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(ValueError):
            await agent.configure()
        assert agent._internal_toolkit is None


class TestRuntimeWarningSuffix:
    async def test_runtime_collision_warning_has_new_suffix(
        self, mock_toolkit_factory, caplog,
    ):
        agent = DatabaseAgent(
            name="t",
            toolkits=[mock_toolkit_factory(tool_prefix="db")],
        )
        await agent.configure()
        # Force a runtime collision by appending a second toolkit
        # AFTER configure() — bypasses Pass C.
        agent.toolkits.append(mock_toolkit_factory(tool_prefix="db"))
        agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        msgs = [r.getMessage() for r in caplog.records]
        assert any(
            "should have been caught at configure() time" in m
            for m in msgs
        )
```

---

## Agent Instructions

1. Confirm TASK-1208 (FEAT-171) is in `sdd/tasks/completed/` — this
   feature builds on the two-map split and the runtime warning it
   introduced.
2. Re-verify line numbers in `agent.py` — they may shift after
   TASK-1208 lands.
3. Implement in order: regex constant, three validation passes in
   `configure()`, docstring update, runtime-warning suffix, mock
   factory extension, unit tests.
4. Run `pytest packages/ai-parrot/tests/unit/bots/database/ -v`
   (the new file AND the existing TASK-1208 tests).
5. Run `ruff check packages/ai-parrot/src/parrot/bots/database/agent.py`.
6. Move task file to `sdd/tasks/completed/` and update the
   per-spec index
   `sdd/tasks/index/databaseagent-mandatory-prefix-collision.json`.
7. Fill in the Completion Note.

---

## Completion Note

**Status**: done  
**Completed**: 2026-05-15  
**Agent**: sdd-worker

### What was implemented

1. `_TOOL_PREFIX_PATTERN` added at module scope in `agent.py` (after all imports,
   before the component maps) with pattern `^[A-Za-z][A-Za-z0-9_]*$`.
2. Three validation passes inserted in `configure()` between the `tk.start()` loop and
   `self._internal_toolkit = DatabaseAgentToolkit()` (Pass A: prefix presence, Pass B:
   identifier-safe shape, Pass C: collision detection via `list_tool_names()`).
3. `configure()` docstring updated with new `Raises:` entries and partial-state safety note.
4. Runtime warning suffix added to `_compute_active_tools`: "This should have been caught
   at configure() time — please file a bug."
5. `conftest.py` extended: `database_type` parameter on `MockDatabaseToolkit`, a
   module-level `_MOCK_COUNTER` for unique IDs, and `method_name`/`methods` parameters
   on `mock_toolkit_factory._make` via dynamic class creation.

### Test results
- 17 new unit tests in `test_configure_validation.py` — all passing.
- 8 existing FEAT-171 tests in `test_compute_active_tools.py` — all still passing.
- `ruff check` — clean.

### Key note: unique `database_type`
Each factory call generates `mock_0`, `mock_1`, … as the toolkit's `database_type` to
prevent `CacheManager.create_partition()` namespace collisions in multi-toolkit tests.
