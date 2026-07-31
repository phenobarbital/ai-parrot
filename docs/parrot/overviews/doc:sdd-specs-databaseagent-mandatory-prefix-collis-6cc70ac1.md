---
type: Wiki Overview
title: 'Feature Specification: Mandatory `tool_prefix` + Eager Collision Detection'
id: doc:sdd-specs-databaseagent-mandatory-prefix-collision-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: merged first. This feature assumes the two-map split
relates_to:
- concept: mod:parrot.bots.database.toolkits._internal
  rel: mentions
- concept: mod:parrot.bots.database.toolkits.base
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Mandatory `tool_prefix` + Eager Collision Detection

**Feature ID**: FEAT-172
**Date**: 2026-05-14
**Author**: Juan Francisco Ruffato
**Status**: approved
**Target version**: next

**Depends on**: FEAT-171 (`databaseagent-prefix-aware-tools`) — must be
merged first. This feature assumes the two-map split
(`_INTERNAL_TOOLS_BY_COMPONENT` / `_TOOLKIT_TOOLS_BY_COMPONENT`) and
the prefix-aware resolution path are already in place.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-171 makes `DatabaseAgent` prefix-aware at the resolution layer:
toolkits with different prefixes (`db`, `bq`, `influx`, etc.) coexist
correctly and runtime collisions are logged. That handles the visible
symptoms.

But two underlying weaknesses remain:

1. **`tool_prefix` is still optional**. `AbstractToolkit.tool_prefix`
   defaults to `None` (`tools/toolkit.py:242`), and the framework
   documents (lines 240-241) that this is a *"transitional escape
   hatch and will become mandatory in a future release."* A
   `DatabaseAgent` consumer can attach a database toolkit with
   `tool_prefix=None`, in which case FEAT-171's prefix-aware lookup
   falls back to "treat logical name as full name" — graceful, but
   masks misconfiguration. By contract, every database toolkit
   should have a prefix.

2. **Collisions are caught lazily**. FEAT-171 detects collisions on
   every call to `_compute_active_tools` and emits a warning. The
   first time that warning fires might be the 500th LLM turn in
   production, at which point the operator has already been
   running with a degraded tool set for hours. The maintainer's
   explicit preference, as conveyed during the PR #866 review:

   > "Dos tools no se deberían llamar igual."

   The right semantics for a misconfiguration like "two toolkits
   with the same fully-qualified tool name" is to **fail fast at
   `configure()` time** with a clear error, not to warn at every
   request thereafter.

### Goals

- Enforce non-empty `tool_prefix` for every `DatabaseToolkit`
  attached to a `DatabaseAgent`. Validation runs at
  `DatabaseAgent.configure()`, not at toolkit `__init__`, so direct
  toolkit instantiation (tests, scripts) is unaffected.
- Detect tool-name collisions at `configure()` time: walk every
  attached toolkit's `list_tool_names()` and build a
  `dict[fully_qualified_name → toolkit_class]`. On the second
  insertion of any name, raise `ValueError` naming both classes.
- Demote FEAT-171's runtime collision warning to a defensive
  log-only fallback — it should now be effectively unreachable in a
  well-configured agent.

### Non-Goals (explicitly out of scope)

- Making `tool_prefix` mandatory on `AbstractToolkit` globally.
  This feature only enforces it for `DatabaseToolkit`
  subclasses, since `DatabaseAgent` is the only consumer that
  controls toolkit attachment in a centralized way.
- Auto-fixing or auto-renaming colliding tools. Collision is a
  configuration bug owned by the consumer; the agent reports and
  refuses to start.
- Migrating the internal helper toolkit. See FEAT-173.
- Adding a `tool_prefix` validation regex (e.g. "must be
  identifier-safe"). The default separator is `_`, but the prefix
  itself is free-form. Validating identifier rules is a
  framework-wide concern, not this feature's scope.

---

## 2. Architectural Design

### Overview

Two changes inside `bots/database/agent.py::configure()`, both
purely defensive:

1. **Prefix check.** After the existing `for tk in self.toolkits`
   loop, iterate once more and raise if any toolkit's
   `tool_prefix` is `None` or empty string.
2. **Collision check.** Same iteration walks
   `tk.list_tool_names()` (the fully-qualified names that the
   toolkit will register) and accumulates them in a dict keyed by
   tool name. On the second occurrence of any name, raise
   `ValueError` referencing both `type(tk).__name__` values.

Both raise before `self._internal_toolkit = DatabaseAgentToolkit()`
runs, so a malformed config never reaches a usable state.

### Component Diagram

```
DatabaseAgent.__init__(toolkits=[...])
       │
       ▼
DatabaseAgent.configure()
       │
       ├──► [existing] tk.start(), cache_partition wiring, etc.
       │
       ├──► [NEW] for tk in self.toolkits:
       │              if not tk.tool_prefix:                 → ValueError
       │              for name in tk.list_tool_names():
       │                  if name in already_seen:           → ValueError
       │                  already_seen[name] = type(tk)
       │
       └──► [existing] self._internal_toolkit = DatabaseAgentToolkit()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatabaseAgent.configure()` | extends | Adds two consecutive validation loops before instantiating `_internal_toolkit`. |
| `AbstractToolkit.tool_prefix` | uses (read) | Read each toolkit's declared prefix to validate non-empty. |
| `AbstractToolkit.list_tool_names()` | uses (call) | Enumerate fully-qualified tool names for collision detection. |
| `_compute_active_tools` (from FEAT-171) | uses | Runtime collision warning becomes a defensive fallback — should never fire in a configured agent. |

### Data Models

None. The collision-detection dict is local to `configure()`:

```python
fully_qualified_owners: Dict[str, type] = {}
```

### New Public Interfaces

None. New errors emitted at existing entry point.

### Error Messages

Three new `ValueError` cases, with exact text:

```python
# Missing / empty prefix
raise ValueError(
    f"DatabaseToolkit subclasses must declare a non-empty "
    f"tool_prefix; {type(tk).__name__} has tool_prefix={tk.tool_prefix!r}. "
    f"Set `tool_prefix` on the toolkit class (e.g. \"db\", \"bq\")."
)

# Identifier-safe prefix (Q2 resolution)
raise ValueError(
    f"DatabaseToolkit subclasses must declare an identifier-safe "
    f"tool_prefix matching {_TOOL_PREFIX_PATTERN.pattern!r}; "
    f"{type(tk).__name__} has tool_prefix={tk.tool_prefix!r}. "
    f"Use only ASCII letters, digits, and underscores, starting "
    f"with a letter."
)

# Fully-qualified name collision
raise ValueError(
    f"Tool name collision while configuring DatabaseAgent: "
    f"{full_name!r} is exposed by both {prior_owner.__name__} and "
    f"{type(tk).__name__}. Two toolkits must not register the same "
    f"fully-qualified tool name. Change one toolkit's tool_prefix or "
    f"remove the duplicate from one of the toolkits."
)
```

---

## 3. Module Breakdown

### Module 1: Validation loops in `configure()`

- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**:
  - Add a module-level compiled regex
    `_TOOL_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")`
    (Q2 resolution).
  - Add the two validation loops after the existing
    `for tk in self.toolkits` block but **before**
    `self._internal_toolkit = DatabaseAgentToolkit()`.
  - The order matters:
    1. **Prefix presence**: raise `ValueError` if any toolkit's
       `tool_prefix` is `None` or empty string.
    2. **Prefix shape**: raise `ValueError` if any toolkit's
       `tool_prefix` does not match `_TOOL_PREFIX_PATTERN`.
    3. **Collision detection**: walk `tk.list_tool_names()` for
       every toolkit, accumulate in a
       `Dict[str, type[DatabaseToolkit]]`, raise `ValueError`
       on second insertion (naming both classes).
  - All three raise with the exact messages above.
  - Pre-empt the internal toolkit instantiation so a malformed
    config never produces a partially-configured agent.
- **Depends on**: FEAT-171 (the two-map split must already be in
  `agent.py`, otherwise the collision detection has nothing
  meaningful to validate against).

### Module 2: Tighten FEAT-171's runtime warning

- **Path**: `packages/ai-parrot/src/parrot/bots/database/agent.py`
- **Responsibility**:
  - Update the comment / log line introduced by FEAT-171 inside
    `_compute_active_tools` to note that this branch is **defensive
    only** post-FEAT-172. If the warning fires in a configured
    agent, that indicates either (a) a toolkit was mutated after
    `configure()` finished, or (b) FEAT-172's eager check missed an
    edge case — both worth investigating.
  - No behaviour change at runtime; semantic change only in the
    log message (e.g. include the suffix "this should have been
    caught at configure() time — please file a bug").
- **Depends on**: Module 1.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_configure_rejects_none_prefix` | Module 1 | `DatabaseAgent` configured with a toolkit whose `tool_prefix=None` raises `ValueError` containing the toolkit class name. |
| `test_configure_rejects_empty_prefix` | Module 1 | Same as above but `tool_prefix=""`. |
| `test_configure_rejects_non_identifier_prefix` | Module 1 | Toolkit with `tool_prefix="my-db"` / `"db "` / `"123db"` raises `ValueError` mentioning the regex `^[A-Za-z][A-Za-z0-9_]*$`. |
| `test_configure_accepts_valid_prefix` | Module 1 | `DatabaseAgent` with one `PostgresToolkit(tool_prefix="db")` configures without error. Regression check. |
| `test_configure_accepts_identifier_prefixes` | Module 1 | Toolkits with `tool_prefix` in `["db", "pg", "bq", "influx", "elastic_v2", "X1"]` all configure successfully. |
| `test_configure_rejects_collision_same_prefix` | Module 1 | Two `MockToolkit` instances with `tool_prefix="dup"` both exposing `dup_search_schema` — `configure()` raises `ValueError` naming both classes. |
| `test_configure_rejects_collision_idempotent_naming` | Module 1 | `AbstractToolkit` prefix rewriting is idempotent. Test the edge case where one toolkit's method is named `db_foo` (already prefixed) and another's `foo` (gets `db_` applied) — both resolve to `db_foo` and must collide. |
| `test_configure_accepts_distinct_prefixes_same_logical_name` | Module 1 | `DatabaseAgent` with `PostgresToolkit(tool_prefix="db")` exposing `db_search_schema` and `MockToolkit(tool_prefix="mk")` exposing `mk_search_schema` — `configure()` succeeds. No collision. |
| `test_runtime_collision_warning_post_configure` | Module 2 | Force a runtime collision by mutating `self.toolkits` after `configure()`. `_compute_active_tools` still logs a warning (defensive fallback). |

### Integration Tests

| Test | Description |
|---|---|
| `test_sql_analyst_unchanged_after_feat_172` | Run the existing sql_analyst smoke flow. `configure()` succeeds, no warnings emitted at runtime, tool surface identical to FEAT-171's baseline. |

### Test Data / Fixtures

Reuse `MockDatabaseToolkit` from FEAT-171's `tests/unit/bots/database/conftest.py`.
Add a parameterized variant:

```python
@pytest.fixture
def mock_toolkit_factory():
    def make(tool_prefix=None, methods=None):
        class _ConfigurableMock(DatabaseToolkit):
            ...
        _ConfigurableMock.tool_prefix = tool_prefix  # may be None / "" / "any"
        return _ConfigurableMock()
    return make
```

---

## 5. Acceptance Criteria

This feature is complete when ALL of the following are true:

- [ ] All new unit tests pass.
- [ ] `test_sql_analyst_unchanged_after_feat_172` passes — no
      regression from the FEAT-171 baseline.
- [ ] `DatabaseAgent.configure()` raises `ValueError` with the exact
      message format documented in Section 2 when a toolkit lacks a
      prefix.
- [ ] `DatabaseAgent.configure()` raises `ValueError` with the exact
      message format documented in Section 2 when a toolkit's
      `tool_prefix` does not match `^[A-Za-z][A-Za-z0-9_]*$`.
- [ ] `DatabaseAgent.configure()` raises `ValueError` with the exact
      message format documented in Section 2 when two toolkits
      collide on a fully-qualified name.
- [ ] No `DatabaseToolkit` subclass in the repo lacks a
      `tool_prefix` after this feature lands (audit + fix in this
      PR if any are missing). See Open Questions.
- [ ] The runtime collision warning from FEAT-171 still exists but
      its log message is updated to indicate it is a defensive
      fallback that should not fire in a configured agent.
- [ ] Documentation in `DatabaseAgent.configure()` docstring
      mentions the two new validation steps and their failure modes.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified by reading the repository at HEAD of `dev` on 2026-05-14.

### Verified Imports

```python
# bots/database/agent.py (existing)
from typing import Any, Dict, List, Optional, Set
from parrot.bots.database.toolkits._internal import DatabaseAgentToolkit  # verified
from parrot.bots.database.toolkits.base import DatabaseToolkit   # verified
```

### Existing Class Signatures

```python
# bots/database/agent.py:134
class DatabaseAgent(...):
    self.toolkits: List[DatabaseToolkit]              # set in __init__:120
    self._toolkit_map: Dict[str, DatabaseToolkit]     # set in __init__:127
    self._internal_toolkit: Optional[DatabaseAgentToolkit]  # set in __init__:128, assigned in configure():180

    async def configure(self, app: Any = None) -> None:  # line 134
        # Existing flow:
        # 1. Iterate self.toolkits to build allowed_schemas / primary_schema
        # 2. Create SchemaQueryRouter
        # 3. Loop self.toolkits: wire cache_partition, retry_config, call tk.start()
        # 4. self._internal_toolkit = DatabaseAgentToolkit()
        # 5. Log info

# tools/toolkit.py:448
class AbstractToolkit:
    def list_tool_names(self) -> List[str]:
        """Return the list of registered tool names AFTER prefix rewrite.
        Triggers _generate_tools() lazily on first call."""
```

### Where to Insert the Validation

```python
# bots/database/agent.py:174-180 (CURRENT — this feature inserts BEFORE line 180)
            try:
                await tk.start()
                self.logger.info("Started toolkit: %s", tk_id)
            except Exception as exc:
                self.logger.warning("Failed to start toolkit %s: %s", tk_id, exc)

        # <<< INSERT VALIDATION LOOPS HERE >>>

        self._internal_toolkit = DatabaseAgentToolkit()
```

### Existing Subclasses of `DatabaseToolkit` to audit

```python
# bots/database/toolkits/base.py:78
class DatabaseToolkit(AbstractToolkit, ABC):
    tool_prefix: str = "db"   # line 93 — already concrete; every subclass inherits "db" unless overridden

# Subclasses observed at HEAD on dev (2026-05-15 audit):
#   - SQLToolkit               (bots/database/toolkits/sql.py:61)         tool_prefix="db"
#   - PostgresToolkit          (bots/database/toolkits/postgres.py:28)    tool_prefix="db" (inherits)
#   - BigQueryToolkit          (bots/database/toolkits/bigquery.py:19)    tool_prefix="db" (inherits)
#   - InfluxDBToolkit          (bots/database/toolkits/influx.py:15)      tool_prefix="db" (inherits)
#   - ElasticToolkit           (bots/database/toolkits/elastic.py:15)     tool_prefix="db" (inherits)
#   - DocumentDBToolkit        (bots/database/toolkits/documentdb.py:15)  tool_prefix="db" (inherits)
# None set tool_prefix to None or "". FEAT-172 does NOT break any existing
# concrete toolkit in the parrot repo. Plugins (navigator-plugins) must be
# audited in their own repo before merging.
#
# IMPORTANT — there is NO class named `AbstractDatabaseToolkit` in the
# codebase. Earlier draft references to that name were corrected on
# 2026-05-15. The real base is `DatabaseToolkit`.
```

### Does NOT Exist (Anti-Hallucination)

- ~~`ToolNameCollisionError`~~ — the name exists in parrot but is
  raised by `ToolManager.register_tool`, not by `DatabaseAgent`.
  This feature uses plain `ValueError`.
- ~~`DatabaseAgent.validate_toolkits()`~~ — does not exist. The
  validation lives inline in `configure()`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Validation must happen **after** every `tk.start()` call but
  **before** `self._internal_toolkit` is assigned. This ordering
  guarantees that `list_tool_names()` is invokable (some toolkits
  generate tools lazily on first `_generate_tools()` call) and
  that no partial state is left behind on failure.
- Error messages must include both colliding class names by their
  short `__name__`, not their fully-qualified module path. The
  operator usually knows the class names; module paths are noise.

### Known Risks / Gotchas

- **Plugins outside the parrot repo**. `DatabaseToolkit`
  subclasses in `navigator-plugins` (e.g. inside `docs/sql.py`) may
  rely on the default `tool_prefix="db"` set on the base class. The
  audit step (acceptance criteria) is critical — if any subclass
  sets `tool_prefix = None` explicitly, this feature breaks it.
  Recommend grepping every consumer repo before merging.
- **`list_tool_names()` side effect**. `AbstractToolkit.list_tool_names`
  triggers `_generate_tools()` lazily on first call. Calling it at
  `configure()` time forces tool generation earlier than it would
  otherwise happen. Test that toolkits which generate expensive
  metadata at `_generate_tools()` time still configure within the
  current latency budget.
- **Test isolation**. `DatabaseAgent.configure()` mutates
  `self._toolkit_map`. Tests that exercise validation failures
  should assert that on failure `_internal_toolkit` is still
  `None`, otherwise leftover state could leak between tests.

### External Dependencies

None.

---

## 8. Open Questions

> All three open questions are resolved. They are kept here with
> their resolutions as the audit trail.

- [x] **Q1 — Audit of existing subclasses** — *Resolved 2026-05-15*:
      **Safe inside the parrot repo.** Grep audit at HEAD on `dev`
      shows every `DatabaseToolkit` subclass
      (`SQLToolkit`, `PostgresToolkit`, `BigQueryToolkit`,
      `InfluxDBToolkit`, `ElasticToolkit`, `DocumentDBToolkit`)
      inherits the default `tool_prefix = "db"` from
      `DatabaseToolkit` (base.py:93). None set `None` or `""`.
      Plugin repos (`navigator-plugins`) still need to be audited
      in their own PRs before this feature merges, but ai-parrot
      itself is clean. Side note: post-FEAT-172, two `DatabaseToolkit`
      subclasses with the inherited `"db"` prefix attached to the
      same agent will collide; the operator must pass distinct
      `tool_prefix` values explicitly. This is by design — the
      whole point of FEAT-172 is fail-fast on misconfig.
- [x] **Q2 — Identifier-safe prefix validation** — *Resolved
      2026-05-15*: **Enforce `^[A-Za-z][A-Za-z0-9_]*$`.** The
      prefix is concatenated into the LLM-visible tool name
      (`{prefix}{separator}{method}`), which most providers
      (OpenAI / Anthropic) reject if it contains dashes, spaces
      or non-ASCII. The regex catches `"my-db"`, `"db "`,
      `"123db"` at `configure()` time. Cheap, real-world bugs
      caught. Implementation: module-level
      `_TOOL_PREFIX_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")`
      checked after the non-empty assertion.
- [x] **Q3 — `OutputComponent` flags in collision error** —
      *Resolved 2026-05-15*: **Omit them.** Collision detection
      runs at `configure()` time, walking
      `tk.list_tool_names()` — `OutputComponent` flags are not
      contextually available (they belong to a specific
      `_compute_active_tools` request). Including them would
      mean synthesising the cross-product post-hoc, which adds
      noise without operational value. The runtime warning in
      FEAT-171 (covered by FEAT-171 Q1) already carries the
      component flag for the rare cases where the defensive
      fallback fires.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-14 | Juan Francisco Ruffato | Initial draft. Extracted from the original FEAT-171 spec (Module 2). |
| 0.2 | 2026-05-15 | Juan Francisco Ruffato | Resolved Q1 (audit clean inside parrot), Q2 (identifier-safe prefix regex), Q3 (omit OutputComponent flags from collision error). Corrected contract drift: `AbstractDatabaseToolkit` → `DatabaseToolkit` (the real class name in base.py:78). Status: draft → approved. |
