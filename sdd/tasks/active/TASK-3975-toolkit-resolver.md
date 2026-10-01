# TASK-3975: ToolkitResolver — single slug→class authority with declarative host registry (M1)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Wave**: 1 (spec §9) · **Module**: M1 toolkit-resolver

---

## Context

Spec §1 P1: five ad-hoc resolvers pick different discovery strategies; `discover_from_registry()`
skips `plugins.tools` (`discovery.py:28`, `:44-45`), so a host toolkit is invisible on most Studio
paths. Spec §2 "Overview" item 1 and "Resolution rules" 1–5 define one process-wide
`ToolkitResolver` that merges built-in explicit entries, `parrot_tools.TOOL_REGISTRY` and the host's
declared `plugins.tools.TOOL_REGISTRY` (prefixed with `HOST_TOOL_PREFIX`), without ever mutating a
registry. This task creates the resolver only; adoption on the call sites is TASK-3979/TK-06 (M2).
It also creates the shared core **host fixture** (`_host_probe.py`, spec §4 "Host fixture") that the
later core tasks extend.

---

## Scope

- Create `parrot/tools/resolver.py` with `ToolkitEntry`, `ToolkitResolver` (`entries()`, `entry()`,
  `resolve()`, `reload()`) and `get_toolkit_resolver()` exactly as spec §2 "New Public Interfaces".
- Implement resolution rules 1–5 (spec §2 "Resolution rules"):
  1. built-in explicit entries (`dataset_manager`, `wiki`, `infographic`; `dotted_path=None`, `source="builtin"`)
     first, then `parrot_tools.TOOL_REGISTRY` (`source="parrot_tools"`);
  2. host entries from `importlib.import_module("plugins.tools")` → declared `TOOL_REGISTRY` dict +
     `HOST_TOOL_PREFIX` str; reject (one `logger.error` naming it) a slug lacking the prefix, a slug
     colliding case-insensitively with a built-in / `parrot_tools` slug, and a toolkit whose
     `tool_prefix` != `HOST_TOOL_PREFIX.rstrip("_")`;
  3. `plugins.tools` without `TOOL_REGISTRY` → `discover_from_walk(["plugins.tools"])` fallback with a
     `DeprecationWarning` (`warnings.warn`) and `source="walk"`, keys as today;
  4. `ImportError` on `plugins.tools` → no host entries, not an error;
  5. a **host** entry whose class is tenant-bound (`getattr(cls, "tenant_bound", False)`) resolves as
     unavailable (`resolve()` → `None`, `entry()` still returns the entry) until M3b (TASK-3989) lifts it.
- `resolve()` / `entry()` are case-insensitive; `plugins.tools` is imported lazily on first use, never at
  `parrot` import (spec §7 "Import-time side effects").
- Create the core host fixture helper `tests/tools/_host_probe.py` (writes a tmp `plugins/tools/`
  package with `HOST_TOOL_PREFIX="tp_"`, `TOOL_REGISTRY={"tp_probe": ..., "tp_probe_tool": ...}`,
  `ProbeToolkit` and `ProbeTool` with side-effect counters) and the M1 unit tests.

**NOT in scope**: changing any call site (TASK-3979/TK-06); `source`/`access` in the catalogue
(TASK-3980/TK-07); the policy (`TASK-3977`); `server_managed_params` on the probe (TASK-3985 extends the
fixture); `read_tools` on the probe (TASK-3981 extends the fixture); lifting rule 5 (TASK-3989).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/resolver.py` | CREATE | ToolkitEntry, ToolkitResolver, get_toolkit_resolver (rules 1–5) |
| `packages/ai-parrot/tests/tools/_host_probe.py` | CREATE | core host fixture helper: tmp plugins/tools package + probe classes + counters |
| `packages/ai-parrot/tests/tools/test_toolkit_resolver.py` | CREATE | M1 unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.discovery import discover_from_registry, discover_from_walk, resolve_class  # discovery.py:31, :64, :139
from parrot.tools.toolkit import AbstractToolkit  # toolkit.py:203
from parrot.tools.abstract import AbstractTool  # abstract.py:281
from parrot.tools.dataset_manager.tool import DatasetManager  # used by interfaces/tools.py:12 and tooling_store.py:22
from parrot.knowledge.wiki import LLMWikiToolkit  # used by tooling_store.py:15
from parrot.tools.infographic_toolkit import InfographicToolkit  # tools/infographic_toolkit.py; used by tooling_store.py:23
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/discovery.py
DEFAULT_SOURCES = ["parrot_tools", "plugins.tools"]           # :22
WALK_SOURCES = {"plugins.tools"}                              # :28
def discover_from_registry(sources: list[str] | None = None) -> Dict[str, str]  # :31 — skips WALK_SOURCES (:44-45)
def discover_from_walk(sources=None, filter_fn=None) -> Dict[str, Type[AbstractTool | AbstractToolkit]]  # :64
    # key = getattr(obj, "name", attr_name) (:105)
def resolve_class(dotted_path: str) -> Type  # :139

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):  # :203
    tool_prefix: str | None = None   # :254
    prefix_separator: str = "_"      # :257

# server today (to be replaced by shims in TASK-3979; for behaviour parity reference only)
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py:39
_EXPLICIT = {"dataset_manager": DatasetManager, "wiki": LLMWikiToolkit, "infographic": InfographicToolkit}
```

### Does NOT Exist
- ~~`parrot.tools.resolver`~~, ~~`ToolkitResolver`~~, ~~`ToolkitEntry`~~, ~~`get_toolkit_resolver`~~ — created here.
- ~~`plugins.tools.TOOL_REGISTRY` honoured by `discover_from_registry`~~ — skipped (`discovery.py:44-45`); do NOT change `discovery.py` (ToolManager keeps its signatures).
- ~~a `HOST_TOOL_PREFIX` convention~~ — introduced here.
- ~~`tenant_bound` on `AbstractToolkit` / `AbstractTool`~~ — added by TASK-3976; read it with `getattr(..., False)` here.
- ~~`ServerParam` / `server_managed_params`~~ — TASK-3985; the probe in this task does not declare them yet.
- ~~a registry setter / mutation API~~ — the resolver never writes into any registry dict (AC "No code path mutates …").

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/resolver.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/_host_probe.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_toolkit_resolver.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/discovery.py#discover_from_registry",
    "sym:packages/ai-parrot/src/parrot/tools/discovery.py#discover_from_walk",
    "sym:packages/ai-parrot/src/parrot/tools/discovery.py#resolve_class",
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Lazy, cached, read-only view over declared registries, like `discover_from_registry` (`discovery.py:31-61`)
  but **including** `plugins.tools` with the prefix/collision rules. Use `resolve_class` for dotted paths.
- Built-in explicit entries: `dataset_manager`, `wiki`, `infographic` — map to the classes `_EXPLICIT`
  uses today (`tooling_store.py:39`); import them lazily inside `_build()` to avoid import cycles
  (`parrot.knowledge.wiki` pulls heavy deps).
- `parrot_tools.TOOL_REGISTRY` is read through `importlib.import_module("parrot_tools")`; `ImportError`
  → no entries (it is optional).
- The prefix check needs the class: rule 2's `tool_prefix` check resolves the dotted path at build
  time; a dotted path that fails to import is rejected with one `logger.error` (it would be unavailable anyway).

### Cross-feature ordering
- None. Wave 1, no sibling dependency (package X16 "No sibling dependency (early)"). May merge before
  any FEAT-605 or FEAT-621 task.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/discovery.py` — strategies reused.
- `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py:92-119` — today's case-insensitive lookup to keep.

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `resolver.py` from the block below — *why*: the spec fixes the API and the rule order.
2. Fill `_build()` rule by rule, logging each rejected host entry once — *why*: rules 2–4 are the security boundary (no shadowing, RC-1).
3. Create `_host_probe.py` (fixture writer) — *why*: every later core test reuses one probe package (spec §4 "Host fixture").
4. Write the four M1 tests; mutation-check each (e.g. drop the collision check → `test_resolver_rejects_unprefixed_and_colliding_host_slugs` RED).

### `packages/ai-parrot/src/parrot/tools/resolver.py` (CREATE)
```python
"""Single slug → class authority for toolkits and tools (FEAT-622 M1).

Merges, in order: built-in explicit entries, ``parrot_tools.TOOL_REGISTRY`` and the host's declared
``plugins.tools.TOOL_REGISTRY`` (prefixed by ``HOST_TOOL_PREFIX``). Never mutates any registry.
"""
from __future__ import annotations

import importlib
import logging
import threading
import warnings
from typing import Literal

from pydantic import BaseModel

from parrot.tools.discovery import discover_from_walk, resolve_class

logger = logging.getLogger("parrot.tools.resolver")

_HOST_PACKAGE = "plugins.tools"


class ToolkitEntry(BaseModel, frozen=True):
    """One resolvable slug."""

    slug: str
    dotted_path: str | None  # None for built-in explicit entries (and walked classes)
    source: Literal["builtin", "parrot_tools", "host", "walk"]


class ToolkitResolver:
    """Process-wide, lazily built, read-only resolver (spec §2 "Resolution rules")."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, ToolkitEntry] | None = None  # key: slug.lower()
        self._classes: dict[str, type] = {}  # key: slug.lower(); walked / explicit classes

    def entries(self) -> list[ToolkitEntry]:
        """Every entry, sorted by slug (catalogue and policy use this)."""
        return sorted(self._ensure().values(), key=lambda item: item.slug)

    def entry(self, slug: str) -> ToolkitEntry | None:
        """Case-insensitive entry lookup; returns rule-5-unavailable entries too."""
        return self._ensure().get(slug.lower())

    def resolve(self, slug: str) -> type | None:
        """Case-insensitive slug → class; ``None`` when unknown, unimportable or unavailable (rule 5)."""
        found = self.entry(slug)
        if found is None:
            return None
        # FILL IN: return the cached class for builtin/walk entries, else resolve_class(found.dotted_path)
        #   catching (ImportError, AttributeError) → None; for source == "host" apply rule 5
        #   (getattr(cls, "tenant_bound", False) → None) — bounded by spec rule 5 and AC test_tenant_bound_host_entry_unavailable_before_enforcement
        raise NotImplementedError

    def reload(self) -> None:
        """Drop the cache (tests / hot reload only)."""
        with self._lock:
            self._entries = None
            self._classes = {}

    def _ensure(self) -> dict[str, ToolkitEntry]:
        if self._entries is None:
            with self._lock:
                if self._entries is None:
                    self._entries = self._build()
        return self._entries

    def _build(self) -> dict[str, ToolkitEntry]:
        """Apply rules 1–4 once."""
        entries: dict[str, ToolkitEntry] = {}
        # FILL IN: rule 1 — builtin explicit entries (lazy imports of DatasetManager, LLMWikiToolkit,
        #   InfographicToolkit into self._classes), then parrot_tools.TOOL_REGISTRY (ImportError → skip)
        # FILL IN: rules 2–4 — self._add_host_entries(entries); keep this method ≤ 60 lines (R4)
        return entries

    def _add_host_entries(self, entries: dict[str, ToolkitEntry]) -> None:
        """Rules 2–4: declared host registry, else deprecated walk fallback, else nothing."""
        try:
            package = importlib.import_module(_HOST_PACKAGE)
        except ImportError:
            return  # rule 4
        declared = getattr(package, "TOOL_REGISTRY", None)
        if not isinstance(declared, dict):
            warnings.warn(
                "plugins.tools without TOOL_REGISTRY is deprecated; declare TOOL_REGISTRY and HOST_TOOL_PREFIX",
                DeprecationWarning,
                stacklevel=2,
            )
            # FILL IN: rule 3 — discover_from_walk([_HOST_PACKAGE]); add each key not already present with
            #   source="walk", dotted_path=None, class cached in self._classes
            return
        prefix = getattr(package, "HOST_TOOL_PREFIX", None)
        # FILL IN: rule 2 — for each (slug, dotted) reject with one logger.error when: prefix is not a str,
        #   slug lacks prefix, slug.lower() collides with an existing entry, the class cannot be imported,
        #   or its tool_prefix != prefix.rstrip("_") (AbstractTool classes have no tool_prefix: skip that check);
        #   otherwise add ToolkitEntry(slug=slug, dotted_path=dotted, source="host")


_RESOLVER: ToolkitResolver | None = None
_RESOLVER_LOCK = threading.Lock()


def get_toolkit_resolver() -> ToolkitResolver:
    """Return the process-wide resolver, building it lazily on first use."""
    global _RESOLVER  # noqa: PLW0603
    if _RESOLVER is None:
        with _RESOLVER_LOCK:
            if _RESOLVER is None:
                _RESOLVER = ToolkitResolver()
    return _RESOLVER
```
**Why this shape**: the API is fixed by spec §2; entries are keyed lower-case so lookups stay
case-insensitive like today (`testing.py:108-111`). Rule 5 lives in `resolve()` (not `_build`) so
TASK-3989 lifts it by deleting one branch. Do NOT add a write/register method.

### `packages/ai-parrot/tests/tools/_host_probe.py` (CREATE)
```python
"""Core host fixture (spec §4 "Host fixture"): writes a tmp ``plugins/tools`` package."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

PROBE_INIT = textwrap.dedent(
    '''
    HOST_TOOL_PREFIX = "tp_"
    TOOL_REGISTRY = {
        "tp_probe": "plugins.tools.probe.ProbeToolkit",
        "tp_probe_tool": "plugins.tools.probe.ProbeTool",
    }
    '''
)

# FILL IN: PROBE_MODULE source — ProbeToolkit(AbstractToolkit): tool_prefix="tp", tenant_bound=True,
#   auto_open=True, async _open() increments COUNTERS["opened"], read tool whoami(), write tool bump()
#   (COUNTERS["bump"] += 1), config_options() increments COUNTERS["options_calls"] with NO scope check;
#   ProbeTool(AbstractTool): name="tp_probe_tool", tenant_bound=True, custom args_schema,
#   _open counter, _execute counter, NO scope check. A module-level COUNTERS dict holds every counter.
#   Bounded by spec §4 "Host fixture" (server_managed_params / read_tools are added by TASK-3985 / TK-07).
PROBE_MODULE = ""


@pytest.fixture
def host_plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write plugins/tools/{__init__,probe}.py under tmp_path, prepend it to sys.path, reset the resolver."""
    from parrot.tools.resolver import get_toolkit_resolver

    pkg = tmp_path / "plugins" / "tools"
    pkg.mkdir(parents=True)
    (tmp_path / "plugins" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text(PROBE_INIT)
    (pkg / "probe.py").write_text(PROBE_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in [m for m in sys.modules if m == "plugins" or m.startswith("plugins.")]:
        monkeypatch.delitem(sys.modules, name)
    get_toolkit_resolver().reload()
    yield pkg
    get_toolkit_resolver().reload()
```
**Why**: one probe definition shared by every core test; later tasks extend `PROBE_MODULE` instead of
writing new probes. Test modules import the fixture with `from ._host_probe import host_plugins  # noqa: F401`.

### FILL IN checklist
- [ ] `resolver.py::ToolkitResolver.resolve` — builtin/walk cache vs `resolve_class`, rule 5; bounded by spec rule 5.
- [ ] `resolver.py::ToolkitResolver._build` — rule 1 order (builtin before `parrot_tools`); bounded by spec rule 1.
- [ ] `resolver.py::ToolkitResolver._add_host_entries` — rules 2–3 rejection list, one `logger.error` each; bounded by RC-1.
- [ ] `_host_probe.py::PROBE_MODULE` — probe classes and counters; bounded by spec §4 "Host fixture".

---

## Acceptance Criteria

- [ ] `from parrot.tools.resolver import ToolkitResolver, ToolkitEntry, get_toolkit_resolver` works; importing `parrot` does not import `plugins.tools`.
- [ ] `tp_probe` / `tp_probe_tool` appear in `entries()` with `source="host"`; built-ins precede and are never shadowed (RC-1).
- [ ] Unprefixed and colliding host slugs are excluded with exactly one `logger.error` each.
- [ ] A `plugins.tools` without `TOOL_REGISTRY` still resolves walked classes (`source="walk"`) and emits a `DeprecationWarning`.
- [ ] Before M3b, `resolve("tp_probe")` is `None` (unavailable) while `entry("tp_probe")` exists.
- [ ] No code mutates `parrot_tools.TOOL_REGISTRY` or any registry dict.
- [ ] `flake8 packages/ai-parrot/src/parrot/tools/resolver.py` clean; complexity ≤ 10 per function.
- [ ] All tests pass and every assertion is mutation-checked (evidence in the Completion Note).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_toolkit_resolver.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_toolkit_resolver.py
import logging
import pytest
from parrot.tools.resolver import get_toolkit_resolver
from ._host_probe import host_plugins  # noqa: F401


def test_resolver_sees_declared_host_registry(host_plugins):
    """tp_probe resolves (entry) and appears in entries() with source="host"."""
    resolver = get_toolkit_resolver()
    assert resolver.entry("TP_PROBE").source == "host"
    assert "tp_probe" in {e.slug for e in resolver.entries() if e.source == "host"}


def test_resolver_rejects_unprefixed_and_colliding_host_slugs(host_plugins, caplog):
    """`probe` (no prefix) and a slug equal to a parrot_tools key are excluded, one error logged each."""
    # FILL IN: rewrite host_plugins/__init__.py with the two bad slugs, reload(), assert absence + 2 error records


def test_resolver_walk_fallback_without_registry(host_plugins):
    """A plugins.tools without TOOL_REGISTRY still resolves walked classes, source="walk"."""
    # FILL IN: blank __init__.py, reload(), pytest.warns(DeprecationWarning), assert walked key resolves


def test_tenant_bound_host_entry_unavailable_before_enforcement(host_plugins):
    """Rule 5: tenant-bound host entry is unavailable until M3b (TASK-3989 replaces this test)."""
    resolver = get_toolkit_resolver()
    assert resolver.entry("tp_probe") is not None
    assert resolver.resolve("tp_probe") is None
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Mutation evidence**: <for each new assertion: the code reverted, the test that went RED>

**Deviations from spec**: none | describe if any
