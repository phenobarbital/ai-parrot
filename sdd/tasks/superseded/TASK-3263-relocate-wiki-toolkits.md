# TASK-3263: Relocate LLMWikiToolkit + CodeStructuralToolkit to `parrot_tools.wiki`

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3262
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (second half). After TASK-3262 moved the `AbstractTool`
wrappers into `parrot_tools.wiki`, the two remaining framework ties in the
wiki tree are the agent-facing toolkits:

- `parrot/knowledge/wiki/toolkit.py` — `LLMWikiToolkit(AbstractToolkit)` (1354 lines)
- `parrot/knowledge/wiki/structural/toolkit.py` — `CodeStructuralToolkit(AbstractToolkit)`

Both import `parrot.tools.toolkit.AbstractToolkit` at module level, which is
exactly what goal G3 forbids. They move verbatim to the `ai-parrot-tools`
distribution next to the precedent `parrot_tools.graphindex.GraphIndexToolkit`
(spec §2 "Relocation"). Every in-repo consumer is repointed in this same task
(spec §7 Gotcha: "Tests referencing ... must be repointed in the same task").

---

## Scope

- `git mv` `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` →
  `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` (content verbatim; only fix
  the module docstring's cross-references if they name the old path).
- `git mv` `packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py` →
  `packages/ai-parrot-tools/src/parrot_tools/wiki/structural_toolkit.py` (content verbatim).
- Leave a **PEP 562 string shim** at `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py`
  (no import statements of `parrot_tools`, only `importlib.import_module("parrot_tools.wiki.toolkit")`
  inside `__getattr__`) — because `docs/guides/jira-wiki-agent-integration.md:154,215,219,290`
  documents `from parrot.knowledge.wiki.toolkit import LLMWikiToolkit` and spec §5 requires
  "No breaking change to any documented public import path". The AST scan (TASK-3268) only
  inspects import statements, so a string-based shim passes G3.
- Repoint `parrot.knowledge.wiki.__init__._EXPORT_MODULES["LLMWikiToolkit"]` to
  `"parrot_tools.wiki.toolkit"`.
- `parrot/knowledge/wiki/structural/__init__.py`: drop the eager
  `CodeStructuralToolkit` import; keep the name in `__all__` resolved through a lazy
  PEP 562 `__getattr__` alias to `parrot_tools.wiki.structural_toolkit`.
- Export `LLMWikiToolkit` and `CodeStructuralToolkit` from `parrot_tools/wiki/__init__.py`
  (lazy map created by TASK-3262 — extend it).
- Repoint every consumer to the explicit new path (list below).
- Add `test_wiki_toolkit_importable_from_parrot_tools` + shim/alias tests.

**NOT in scope**:
- The `AbstractTool` wrappers, `create_wiki_tools`, `create_structural_tools` (TASK-3262).
- `wiki/mcp_server.py` transport selection (TASK-3265).
- Behavioural edits inside `LLMWikiToolkit` / `CodeStructuralToolkit` — move only.
- Rewriting `docs/**` (the shim keeps the documented path working; a doc note is optional).
- A `sys.meta_path` redirector (FEAT-541).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` | CREATE (git mv) | `LLMWikiToolkit`, verbatim |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/structural_toolkit.py` | CREATE (git mv) | `CodeStructuralToolkit`, verbatim |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | CREATE (shim, after mv) | PEP 562 string shim for the documented path |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` | MODIFY | add the two toolkit exports to the lazy map |
| `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` | MODIFY | `_EXPORT_MODULES["LLMWikiToolkit"]` → `parrot_tools.wiki.toolkit` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py` | MODIFY | lazy alias for `CodeStructuralToolkit` |
| `packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py` | MODIFY | repoint lazy import (line 536) |
| `examples/dev_loop/server.py` | MODIFY | repoint lazy import (line 751) — file IS git-tracked |
| `packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py` | MODIFY | repoint lines 31 (TYPE_CHECKING) and 110 |
| `packages/ai-parrot-tools/tests/business_automation/test_memory.py` | MODIFY | repoint `wiki_toolkit_module` import (lines 47, 106) |
| `packages/ai-parrot-tools/tests/wiki/test_toolkit_relocation.py` | CREATE | importability + shim + alias tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `63cc2198e` (2026-09-15). TASK-3262 edits
> `parrot_tools/wiki/__init__.py`, `wiki/structural/__init__.py` and
> `wiki/mcp_server.py` BEFORE this task runs — **re-verify every anchor in those
> files at execution time**; the line numbers below are pre-3262.

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # verified: wiki/toolkit.py:31, structural/toolkit.py:23
from parrot.knowledge.wiki.models import WikiConfig       # verified: wiki/toolkit.py:27
from parrot.knowledge.wiki.structural.service import StructuralService  # verified: structural/toolkit.py:21
import importlib                                          # stdlib (shim / alias)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper                      # line 24
from parrot.knowledge.wiki.context import DEFAULT_BUDGET_TOKENS, pack_results, truncate_to_tokens  # line 25
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator    # line 26
from parrot.knowledge.wiki.models import WikiConfig, WikiLintReport, WikiPageCategory  # line 27
from parrot.knowledge.wiki.search import WikiCombinedSearch                      # line 28
from parrot.knowledge.wiki.sources import SourceCollectionManager               # line 29
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store, estimate_tokens  # line 30
from parrot.tools.toolkit import AbstractToolkit                                 # line 31
def _is_federated(store: Any) -> bool: ...                                       # line 34
class LLMWikiToolkit(AbstractToolkit):                                           # line 41
    def __init__(self, pageindex_toolkit: Any, graphindex_toolkit: Any, okf_toolkit: Any,
                 config: WikiConfig, agent_id: str = "agent",
                 store: Optional[BaseWikiStore] = None, **kwargs: Any) -> None: ...  # line 70
#   internal lazy imports that move with it (all absolute, unchanged):
#   wiki.federation :36, wiki.arango_store :118/:185, wiki.project :119,
#   parrot.loaders.obsidian :291, wiki.export :1191

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py
from parrot.knowledge.wiki.project import (WikiProjectConfig, find_project_root,
    load_effective_config, sqlite_policy_from_config)                            # lines 14-19
from parrot.knowledge.wiki.store import BaseWikiStore, create_wiki_store         # line 20
from parrot.knowledge.wiki.structural.service import StructuralService           # line 21
from parrot.knowledge.wiki.symbols import SymbolKind                             # line 22
from parrot.tools.toolkit import AbstractToolkit                                 # line 23
class CodeStructuralToolkit(AbstractToolkit):                                    # line 26
    def __init__(self, root: Path | None = None, store: BaseWikiStore | None = None,
                 config: WikiProjectConfig | None = None, **kwargs: Any) -> None: ...  # line 44

# packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py
_EXPORT_MODULES: dict[str, str] = {                                              # line 45
    "LLMWikiToolkit": "parrot.knowledge.wiki.toolkit",                           # line 47
def __getattr__(name: str): ...                                                  # lazy resolver (caches in globals())

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py  (pre-3262)
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit       # line 19
    "CodeStructuralToolkit",                                                     # line 35 (__all__)

# ── consumers to repoint (verified) ──
# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py:536
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit  # noqa: PLC0415   (inside try; except logs warning :548)
# examples/dev_loop/server.py:751   (git-tracked)
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
# packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py
    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit          # line 31 (under TYPE_CHECKING)
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit      # line 110 (inside try)
# packages/ai-parrot-tools/tests/business_automation/test_memory.py
    import parrot.knowledge.wiki.toolkit as wiki_toolkit_module       # line 47
    monkeypatch.setattr(wiki_toolkit_module, "LLMWikiToolkit", FakeLLMWikiToolkit)  # line 60
        import parrot.knowledge.wiki.toolkit as wiki_toolkit_module   # line 106
        monkeypatch.setattr(wiki_toolkit_module, "LLMWikiToolkit", RaisingWikiToolkit)  # line 112
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py:27
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig          # resolves via _EXPORT_MODULES — NO edit needed

# precedent
# packages/ai-parrot-tools/src/parrot_tools/graphindex/toolkit.py:76
from parrot.tools.toolkit import AbstractToolkit
```

### Does NOT Exist
- ~~`parrot_tools.wiki.toolkit` / `parrot_tools.wiki.structural_toolkit`~~ — created by this task
  (`parrot_tools/wiki/` itself is created by TASK-3262).
- ~~`parrot_tools.wiki.structural` subpackage~~ — the design uses flat modules
  (`structural_tools.py`, `structural_toolkit.py`), not a nested package.
- ~~Core unit tests that import `parrot.knowledge.wiki.toolkit` directly~~ — only
  `test_memory.py` does; `test_server_repo_wiring.py` and ai-parrot-server `tests/studio/test_toolkits.py`
  reference `LLMWikiToolkit` by name only (via `bootstrap_mod._build_wiki_toolkit` / the package root).
- ~~A `sys.meta_path` finder for `parrot.knowledge.wiki.*`~~ — FEAT-541.
- ~~`ai-parrot` depending on `ai-parrot-tools`~~ — the dependency is the other way
  (`ai-parrot-tools` → `ai-parrot`); core may only reach `parrot_tools` lazily, by string or
  inside `try/except ImportError`.

---

## Implementation Notes

### Key Constraints
- **Move, don't edit.** `git mv` preserves blame; the moved bodies must be byte-identical except
  for docstring cross-references (FILL IN below).
- Core must never import `parrot_tools` with an import *statement* at module level (G3 +
  dependency direction). Lazy strings via `importlib.import_module` only.
- The `parrot.knowledge.wiki.toolkit` shim must NOT `from parrot_tools... import` at module level;
  `monkeypatch.setattr(shim_module, "LLMWikiToolkit", ...)` would patch the shim, not the real
  module — this is why `test_memory.py` is repointed to `parrot_tools.wiki.toolkit` (memory.py
  imports from there after this task).
- `bootstrap.py` / `memory.py` / `examples/dev_loop/server.py` keep their `try/except` shape:
  when `ai-parrot-tools` is not installed they must degrade exactly as they do today.
- Worktree tests: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest ...`.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py:44-110` — PEP 562 lazy map pattern.
- `packages/ai-parrot-tools/src/parrot_tools/graphindex/__init__.py` — toolkit export precedent.

---

## Implementation Blueprint

### Steps (in order)
1. Re-verify the anchors of `parrot_tools/wiki/__init__.py` and `wiki/structural/__init__.py` as
   left by TASK-3262 — *why*: that task rewrote both files; the pre-3262 line numbers above are stale.
2. `git mv packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py`
   and `git mv packages/ai-parrot/src/parrot/knowledge/wiki/structural/toolkit.py packages/ai-parrot-tools/src/parrot_tools/wiki/structural_toolkit.py`
   — *why*: keeps history; the spec (G6) wants move-shaped diffs.
3. Commit-free check: `python -c "import parrot_tools.wiki.toolkit, parrot_tools.wiki.structural_toolkit"` with the
   PYTHONPATH above — *why*: all internal imports are absolute `parrot.knowledge.wiki.*`, so the move needs no import edits; prove it before touching consumers.
4. Create the shim at the old `wiki/toolkit.py` path — *why*: documented import path (docs/guides/jira-wiki-agent-integration.md).
5. Edit `wiki/__init__.py`, `wiki/structural/__init__.py`, `parrot_tools/wiki/__init__.py` — *why*: package-root names keep resolving.
6. Repoint the 4 consumer files + `test_memory.py` — *why*: explicit new path in new code (CLAUDE.md: prefer `parrot_tools.<x>`), and monkeypatch must hit the real module.
7. Write `test_toolkit_relocation.py`; run the test commands in Acceptance Criteria.

### `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` (CREATE — shim, after the git mv)
```python
"""Compatibility shim — ``LLMWikiToolkit`` now lives in ``parrot_tools.wiki.toolkit``.

FEAT-540 moved the agent-facing toolkit out of the framework-free wiki tree.
This module keeps the documented ``from parrot.knowledge.wiki.toolkit import
LLMWikiToolkit`` path working without an import statement that would tie the
wiki tree back to the agent framework (resolved lazily, PEP 562).
"""
from __future__ import annotations

import importlib
from typing import Any

_TARGET_MODULE = "parrot_tools.wiki.toolkit"

__all__ = ["LLMWikiToolkit"]


def __getattr__(name: str) -> Any:
    """Resolve ``LLMWikiToolkit`` from ``parrot_tools.wiki.toolkit`` on first access.

    Args:
        name: Attribute requested on this module.

    Returns:
        The attribute from the relocated module.

    Raises:
        AttributeError: If ``name`` is not re-exported here.
    """
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # FILL IN: ImportError handling — bounded by: when ai-parrot-tools is absent the
    # error message must name the `ai-parrot-tools` distribution (raise ImportError from exc);
    # callers (bootstrap.py, memory.py) already catch Exception and degrade.
    value = getattr(importlib.import_module(_TARGET_MODULE), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Return the re-exported names for ``dir()`` / completion."""
    return sorted(__all__)
```
**Why this shape**: string target + `__getattr__` satisfies the AST scan (no module-level import
statement) while honouring spec §5 "No breaking change to any documented public import path".
Do not add `CodeStructuralToolkit` here — it was never exported from this module.

### `packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '"LLMWikiToolkit": "parrot.knowledge.wiki.toolkit",' packages/ai-parrot/src/parrot/knowledge/wiki/__init__.py)
# REPLACE line 47:
    "LLMWikiToolkit": "parrot.knowledge.wiki.toolkit",
# WITH:
    # FEAT-540: relocated to the ai-parrot-tools distribution (resolved lazily).
    "LLMWikiToolkit": "parrot_tools.wiki.toolkit",
```
**Why**: `parrot.knowledge.wiki.LLMWikiToolkit` is documented in this module's own docstring and
used by `ai-parrot-server/.../studio/toolkits.py:27`; pointing straight at the real module avoids a
double hop through the shim.

### `packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified pre-3262: grep -c 'from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit' packages/ai-parrot/src/parrot/knowledge/wiki/structural/__init__.py)
# DELETE:
from parrot.knowledge.wiki.structural.toolkit import CodeStructuralToolkit
# KEEP "CodeStructuralToolkit" in __all__. APPEND at end of module:

_LAZY_ALIASES: dict[str, str] = {
    # FEAT-540: moved to ai-parrot-tools; kept resolvable from the package root.
    "CodeStructuralToolkit": "parrot_tools.wiki.structural_toolkit",
}


def __getattr__(name: str):
    """Resolve relocated agent-facing names lazily (PEP 562).

    Args:
        name: Attribute requested on the package.

    Returns:
        The object from its relocated module.

    Raises:
        AttributeError: If ``name`` is not a lazy alias.
    """
    module_path = _LAZY_ALIASES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
```
**Why**: `CodeStructuralToolkit` is in the package `__all__` today (public); the eager import is a
module-level `parrot.tools` tie. If TASK-3262 already added a `__getattr__` here, MERGE the alias into
it — `# FILL IN: merge with any existing module __getattr__ — bounded by: exactly one __getattr__ per module`.

### `packages/ai-parrot-tools/src/parrot_tools/wiki/__init__.py` (MODIFY)
```python
# FILL IN: anchor — this file is created by TASK-3262; add to its lazy export map (quote the
# verified map line at execution time):
    "LLMWikiToolkit": "parrot_tools.wiki.toolkit",
    "CodeStructuralToolkit": "parrot_tools.wiki.structural_toolkit",
# and add both names to __all__.
```
**Why**: spec AC `from parrot_tools.wiki import LLMWikiToolkit, CodeStructuralToolkit` must resolve.

### Consumers (MODIFY — one-line swaps)
```python
# packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.toolkit import LLMWikiToolkit' packages/ai-parrot/src/parrot/cli/devloop/bootstrap.py)
        from parrot_tools.wiki.toolkit import LLMWikiToolkit  # noqa: PLC0415   (line 536, stays inside try)

# examples/dev_loop/server.py
# occurrences: 1 (verified: grep -c 'from parrot.knowledge.wiki.toolkit import LLMWikiToolkit' examples/dev_loop/server.py)
        from parrot_tools.wiki.toolkit import LLMWikiToolkit                     (line 751)

# packages/ai-parrot-tools/src/parrot_tools/business_automation/memory.py
# occurrences: 2 (verified: grep -c 'from parrot.knowledge.wiki.toolkit import LLMWikiToolkit' .../memory.py)
#   → both are distinct by indentation: line 31 (4 spaces, under `if TYPE_CHECKING:`),
#     line 110 (8 spaces, inside `try:` after `from parrot.knowledge.wiki.models import WikiConfig`)
    from parrot_tools.wiki.toolkit import LLMWikiToolkit                         (line 31)
        from parrot_tools.wiki.toolkit import LLMWikiToolkit                     (line 110)

# packages/ai-parrot-tools/tests/business_automation/test_memory.py
# occurrences: 2 (verified: grep -c 'import parrot.knowledge.wiki.toolkit as wiki_toolkit_module' .../test_memory.py)
#   → line 47 (4 spaces) and line 106 (8 spaces); replace both:
    import parrot_tools.wiki.toolkit as wiki_toolkit_module
```
**Why**: memory.py now imports from `parrot_tools.wiki.toolkit`, so the monkeypatch must target that
module or the fake never takes effect (test would silently build a real toolkit).

### `packages/ai-parrot-tools/tests/wiki/test_toolkit_relocation.py` (CREATE)
```python
"""FEAT-540 TASK-3263 — agent-facing wiki toolkits live in parrot_tools.wiki."""
from __future__ import annotations

import ast
from pathlib import Path


def test_wiki_toolkit_importable_from_parrot_tools() -> None:
    """Spec §5: ``from parrot_tools.wiki import LLMWikiToolkit, CodeStructuralToolkit``."""
    from parrot_tools.wiki import CodeStructuralToolkit, LLMWikiToolkit

    assert LLMWikiToolkit.__module__ == "parrot_tools.wiki.toolkit"
    assert CodeStructuralToolkit.__module__ == "parrot_tools.wiki.structural_toolkit"


def test_legacy_paths_resolve_to_same_objects() -> None:
    """Documented paths keep working and return the relocated classes."""
    # FILL IN: assert identity for parrot.knowledge.wiki.LLMWikiToolkit,
    # parrot.knowledge.wiki.toolkit.LLMWikiToolkit and
    # parrot.knowledge.wiki.structural.CodeStructuralToolkit — bounded by spec §5
    # "No breaking change to any documented public import path".


def test_wiki_tree_has_no_toolkit_import_statements() -> None:
    """The core shim/alias modules reference parrot_tools only by string."""
    # FILL IN: ast-parse packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py and
    # wiki/structural/__init__.py; assert no ast.Import/ImportFrom whose module starts with
    # "parrot.tools" or "parrot_tools" at module level — bounded by G3. Locate the repo root
    # from Path(__file__).resolve().parents[N] (verify N at execution time).
```
**Why**: covers spec unit test `test_wiki_toolkit_importable_from_parrot_tools` plus the two
guarantees this task introduces (compat + no import statements).

### FILL IN checklist
- [ ] `wiki/toolkit.py` shim — ImportError message names `ai-parrot-tools`; bounded by graceful degradation of callers.
- [ ] `parrot_tools/wiki/toolkit.py` / `structural_toolkit.py` module docstrings — update `:class:` cross-refs that name the old path; nothing else changes.
- [ ] `structural/__init__.py` — merge alias into an existing `__getattr__` if TASK-3262 created one.
- [ ] `parrot_tools/wiki/__init__.py` — quote the verified lazy-map anchor from TASK-3262.
- [ ] `test_toolkit_relocation.py` — identity asserts + AST check; repo-root `parents[N]`.

---

## Addendum — repo-root `tests/` consumers (review, 2026-09-15)

The repo has a SECOND tracked test tree at the root (`tests/`, run by CI via
root `pyproject.toml` `testpaths=["tests"]`, ci.yml:138/:200). The consumer scan
above covered only `packages/*/tests`. These root tests import or patch
`LLMWikiToolkit` / `CodeStructuralToolkit` / `parrot.knowledge.wiki.toolkit` /
`...structural.toolkit` and MUST be checked (verified 2026-09-15 with
`git ls-files tests | xargs grep -nE "wiki\.toolkit|structural\.toolkit|import .*(LLMWikiToolkit|CodeStructuralToolkit)"`):

- `tests/knowledge/wiki/test_toolkit.py:9,94,103,117,127,156,168,349`
- `tests/knowledge/wiki/conftest.py:24`
- `tests/knowledge/wiki/test_toolkit_arango.py:18`
- `tests/knowledge/wiki/test_integration.py:30`
- `tests/knowledge/wiki/test_authoring.py:312,370`
- `tests/knowledge/wiki/test_file_store.py:198`
- `tests/knowledge/wiki/test_updated_at.py:77`
- `tests/knowledge/wiki/test_package_init.py:11`
- `tests/knowledge/wiki/structural/test_tools.py:14`
- `tests/knowledge/wiki/roblox/test_edge_health.py:20`
- `tests/test_fireflies_wiki_agent.py:500,575,600`
- `tests/integration/test_fireflies_meeting_registry.py:31`

Rule: plain imports through the kept lazy shims/aliases may stay as they are;
any `monkeypatch.setattr(<module>, ...)` / `patch("parrot.knowledge.wiki.toolkit.X")`
string MUST be repointed to the module that now defines the symbol
(`parrot_tools.wiki.toolkit` / `parrot_tools.wiki.structural_toolkit`) — a patch on
a shim module does not affect the real class's globals. Re-grep at execution time.

---

## Acceptance Criteria

- [ ] `from parrot_tools.wiki import LLMWikiToolkit, CodeStructuralToolkit` resolves (spec §5).
- [ ] `from parrot.knowledge.wiki import LLMWikiToolkit`, `from parrot.knowledge.wiki.toolkit import LLMWikiToolkit`
      and `from parrot.knowledge.wiki.structural import CodeStructuralToolkit` return the same class objects.
- [ ] No module under `packages/ai-parrot/src/parrot/knowledge/wiki/` contains a module-level
      `parrot.tools.toolkit` import (`grep -rn "^from parrot.tools" packages/ai-parrot/src/parrot/knowledge/wiki/` → empty).
- [ ] `git log --follow packages/ai-parrot-tools/src/parrot_tools/wiki/toolkit.py` shows the pre-move history.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot-tools/tests/wiki/ packages/ai-parrot-tools/tests/business_automation/test_memory.py -v` passes.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src pytest packages/ai-parrot/tests/knowledge/wiki/ packages/ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py packages/ai-parrot/tests/cli/devloop/ -v` passes.
- [ ] `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-server/src pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -v` passes.
- [ ] `ruff check` clean on every changed file.
- [ ] Root-tree consumers pass: `pytest tests/knowledge/wiki/ tests/test_fireflies_wiki_agent.py tests/integration/test_fireflies_meeting_registry.py -v` (integration tests may skip without services)

---

## Test Specification

See `test_toolkit_relocation.py` in the blueprint. Existing suites that must keep passing unchanged
(beyond the repointed import): `ai-parrot-tools/tests/business_automation/test_memory.py`,
`ai-parrot-server/tests/studio/test_toolkits.py`, `ai-parrot/tests/flows/dev_loop/test_server_repo_wiring.py`,
`ai-parrot/tests/cli/devloop/test_bootstrap_dev_flow.py`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3262 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep every anchor; files touched by TASK-3262 WILL have moved lines
4. **Update status** in `sdd/tasks/index/graphindex-core-seams.json` → `"in-progress"`
5. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:`
6. **Verify** all acceptance criteria (worktree: prefix pytest with the PYTHONPATH shown; never `uv sync` in a worktree)
7. **Move this file** to `sdd/tasks/completed/TASK-3263-relocate-wiki-toolkits.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: Spec Module 3 says "removing `parrot/knowledge/wiki/toolkit.py`"; this task
replaces it with a string-only PEP 562 shim because `docs/guides/jira-wiki-agent-integration.md`
documents that import path (spec §5 "No breaking change to any documented public import path").
