# TASK-4180: Public, click-free wiki ingest runtime

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The FEAT-647 wiki target (TASK-4185) must run the FEAT-402 supervised path
(charter triage → `WikiIngestOrchestrator.ingest`) from inside a running
asyncio server. Today the only builder of that service stack is the CLI-private
`_build_ingest_runtime` in `wiki/cli.py`, which raises `click.ClickException`
and builds the novelty scorer with `_run()` = `asyncio.run()` — which **fails
inside a running event loop**. Spec §3 Module 3 extracts the stack into a
public `parrot.knowledge.wiki.runtime` module; the CLI keeps its names,
signatures, monkeypatch seams and messages.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` with:
  - `WikiRuntimeError(RuntimeError)`
  - `build_triage_adapters(lightweight_model, model)` — body moved verbatim from `cli._build_triage_adapters`
  - `async build_novelty_scorer(root, config, store)` — body moved from `cli._build_novelty_scorer`, with `_run(_build_evaluator())` replaced by `await _build_evaluator()`
  - `build_ingest_runtime(...)` — body moved from `cli._build_ingest_runtime`, minus model-id resolution, adapter construction and novelty-scorer construction, which are **passed in**
- Turn the three CLI functions into thin wrappers that keep their exact names
  and signatures.
- Tests for the public module and for the unchanged CLI error message.

**Deviation from the spec's Interface Skeleton (additive, binding for TASK-4185)**:
the skeleton listed `build_ingest_runtime(..., *, lightweight_model, model, fetch_timeout)`
and a sync `build_novelty_scorer`. Verified facts force two changes:
1. `build_novelty_scorer` is `async` — the sync version calls `asyncio.run()`, which raises inside the server's loop.
2. `build_ingest_runtime` takes `novelty_scorer` (required keyword) and `adapters` (optional keyword).
   Existing tests monkeypatch `wiki_cli._build_triage_adapters` (`tests/knowledge/wiki/inbox/conftest.py:60`,
   `tests/knowledge/wiki/test_cli.py:306`); if the public builder called its own adapter factory the CLI
   seam would be bypassed and those tests would build real LLM clients. So the CLI builds adapters through
   its own (patchable) `_build_triage_adapters` and passes them in. When `adapters is None` the public
   builder calls `build_triage_adapters` itself and wraps failures in `WikiRuntimeError`.

**NOT in scope**: `_resolve_ingest_model_ids` (uses `click.echo`; stays in the CLI), `_open_store`,
`_open_sources`, `_resolve_charter_path`, `_checkpoint_if_sqlite`, any change to the `ingest`/`inbox`
command logic, the wiki target itself (TASK-4185).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` | CREATE | public runtime builders + `WikiRuntimeError` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | three functions become wrappers over `runtime` |
| `packages/ai-parrot/tests/knowledge/wiki/test_ingest_runtime.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported at module top of wiki/cli.py (reuse in runtime.py with the same paths):
from parrot.knowledge.wiki.project import WikiProjectConfig                       # cli.py:80-104 block; class at project.py:531
from parrot.knowledge.wiki.sources import SourceCollectionManager                 # cli.py:110; class at sources.py:108
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore            # cli.py:111
# TYPE_CHECKING-only in cli.py (cli.py:49-52):
from parrot.knowledge.wiki.charter import Charter                                 # charter.py:311
from parrot.knowledge.wiki.inbox.processor import InboxRuntime                    # processor.py:43
# Imported lazily INSIDE the moved function bodies (keep them lazy — heavy deps):
from parrot.clients.factory import LLMFactory                                     # cli.py:4632
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter            # cli.py:4633
from parrot.knowledge.wiki.search import WikiCombinedSearch                       # cli.py:4685, :4767
from parrot.knowledge.wiki.triage import IngestTriageRouter, NoveltyScorer        # cli.py:4686 / :4768
from parrot.knowledge.graphindex.assemble import GraphAssembler                   # cli.py:4696 (try/except ImportError)
from parrot.knowledge.graphindex.factory import HashingGraphEmbedder, make_stub_tenant_context
from parrot.knowledge.graphindex.grounding import GroundingEvaluator
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.retriever import GraphExpandedRetriever
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit                   # cli.py:4761
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.documents import DocumentAcquirer
from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
from parrot.knowledge.wiki.models import WikiConfig
# Tests:
from parrot.knowledge.wiki.charter import load_charter                            # charter.py:404
from parrot.knowledge.wiki.store import create_wiki_store                         # used by tests/knowledge/wiki/inbox/conftest.py
import parrot.knowledge.wiki.cli as wiki_cli
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
_cli_logger = logging.getLogger("wikitoolkit.cli")                                # :118
def _run(coro: Any) -> Any: return asyncio.run(coro)                               # :565
def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:   # :4611-4642
def _resolve_ingest_model_ids(lightweight_model_opt: str | None, model_opt: str | None) -> tuple[str, str]:  # :4645
def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:  # :4671-4726
    # ... evaluator = _run(_build_evaluator())   # :4725  ← the asyncio.run that breaks in a server
def _build_ingest_runtime(root: Path, config: WikiProjectConfig, store: BaseWikiStore,
                          sources: SourceCollectionManager, charter: "Charter", charter_path: Path, *,
                          lightweight_model_opt: str | None, model_opt: str | None,
                          fetch_timeout: float = 30.0) -> "InboxRuntime":           # :4729-~4824
    # error message to preserve verbatim:
    #   f"Could not build LLM client(s) for {lightweight_model!r}/{model!r}: {exc}"
# Callers (must keep working unchanged): _build_triage_adapters at :4772, :5168, :5276;
#   _build_novelty_scorer at :4800; _build_ingest_runtime at :5282, :5450, :5461

# packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py:43
class InboxRuntime(BaseModel):  # frozen, arbitrary_types_allowed
    root; config; wiki_config; charter; store; sources; bookkeeper; acquirer; router; orchestrator
    light_adapter: SkipValidation[PageIndexLLMAdapter]; heavy_adapter: SkipValidation[PageIndexLLMAdapter]
    search: WikiCombinedSearch; models: dict[str, str]
```
```python
# Monkeypatch seams that MUST keep working (existing tests):
# tests/knowledge/wiki/inbox/conftest.py:60  monkeypatch.setattr(wiki_cli, "_build_triage_adapters", lambda l, m: (a, a, l, True))
# tests/knowledge/wiki/test_cli.py:306        patch _build_triage_adapters with side_effect
# tests/knowledge/wiki/inbox/test_cli_inbox.py:46, test_end_to_end.py:24  monkeypatch _build_ingest_runtime
# Minimal valid charter YAML used in tests: tests/knowledge/wiki/inbox/test_taxonomy.py:10-23
```

### Does NOT Exist
- ~~`parrot.knowledge.wiki.runtime`~~ — this task creates it
- ~~a public `build_inbox_runtime` / `ingest_one` / `triage_and_ingest`~~ — not in the codebase; do not add them
- ~~`InboxRuntime.build(...)` / any factory classmethod on `InboxRuntime`~~
- ~~an async variant of `_run`~~ — runtime.py must use plain `await`
- ~~`WikiRuntimeError` anywhere today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_ingest_runtime.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_triage_adapters",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_novelty_scorer",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_build_ingest_runtime",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#_run",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/inbox/processor.py#InboxRuntime",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/project.py#WikiProjectConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/sources.py#SourceCollectionManager",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#Charter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/charter.py#load_charter"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure move: no behavior change for the CLI. Same messages, same logging text
  (the "different providers" info line moves to the runtime module's logger).
- runtime.py must not import `click` or anything from `wiki/cli.py` (no cycle).
- Keep heavy imports lazy inside functions, exactly as in the CLI.

### References in Codebase
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py:4611-4824` — code being moved
- `packages/ai-parrot/tests/knowledge/wiki/inbox/conftest.py` — fake adapter + `create_wiki_store` pattern

---

## Implementation Blueprint

### Steps (in order)
1. Create `runtime.py` (two blocks below) and move the three bodies into it — *why*: give async servers a click-free builder (spec §3 M3).
2. In `build_novelty_scorer`, replace `_run(_build_evaluator())` with `await _build_evaluator()` and make the function `async` — *why*: `asyncio.run` raises inside a running loop.
3. Replace the three CLI function bodies with wrappers — *why*: keep CLI names, signatures, monkeypatch seams and messages (AC-15 of the spec).
4. Add the runtime import in cli.py next to the other `parrot.knowledge.wiki` imports — *why*: wrappers need the public functions.
5. Write tests; run the existing wiki CLI/inbox tests to prove no regression.

### `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` (CREATE — block 1/2)
```python
"""Public, click-free builders for the supervised wiki-ingest service stack (FEAT-647).

Extracted from ``parrot.knowledge.wiki.cli`` so async servers (chat integrations)
can run charter triage + ingest without ``click`` or ``asyncio.run``. The CLI
wraps these functions and keeps its own names as monkeypatchable seams.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import BaseWikiStore

if TYPE_CHECKING:
    from parrot.knowledge.wiki.charter import Charter
    from parrot.knowledge.wiki.inbox.processor import InboxRuntime

logger = logging.getLogger(__name__)

__all__ = ["WikiRuntimeError", "build_triage_adapters", "build_novelty_scorer", "build_ingest_runtime"]


class WikiRuntimeError(RuntimeError):
    """An LLM client or the supervised-ingest runtime could not be constructed."""


def build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:
    """Construct the lightweight/heavy ``PageIndexLLMAdapter`` pair.

    Args:
        lightweight_model: Stage-1 triage model spec (``provider:model``).
        model: Stage-2 model spec, also used for page generation.

    Returns:
        ``(lightweight_adapter, heavy_adapter, lightweight_model_id, same_provider)``.
    """
    # FILL IN: move the body of cli._build_triage_adapters (cli.py:4632-4642) verbatim,
    #   including its two lazy imports — bounded by "pure move, no behavior change"


async def build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:
    """Construct a NoveltyScorer (grounding-backed when the graph DB exists).

    Async because the grounding evaluator loads the graph with ``await``;
    safe to call from inside a running event loop.

    Args:
        root: Wiki project root.
        config: The project's ``WikiProjectConfig``.
        store: The open retrieval-plane store (search-proxy fallback).

    Returns:
        A configured ``NoveltyScorer``.
    """
    # FILL IN: move the body of cli._build_novelty_scorer (cli.py:4685-4726) verbatim, EXCEPT
    #   `evaluator = _run(_build_evaluator())` becomes `evaluator = await _build_evaluator()`
    #   — bounded by "no asyncio.run in runtime.py"
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py` (CREATE — block 2/2, appended)
```python
def build_ingest_runtime(
    root: Path,
    config: WikiProjectConfig,
    store: BaseWikiStore,
    sources: SourceCollectionManager,
    charter: "Charter",
    charter_path: Path,
    *,
    lightweight_model: str,
    model: str,
    novelty_scorer: Any,
    adapters: tuple[Any, Any, str, bool] | None = None,
    fetch_timeout: float = 30.0,
) -> "InboxRuntime":
    """Build the supervised-ingestion service bindings for one wiki.

    Args:
        root: Wiki project root.
        config: Resolved project configuration.
        store: Open retrieval-plane store.
        sources: Source manifest manager matching ``store``.
        charter: Parsed editorial charter.
        charter_path: Source path for ``charter``.
        lightweight_model: Stage-1 model spec (recorded in ``InboxRuntime.models``).
        model: Stage-2 model spec.
        novelty_scorer: Prebuilt scorer (``await build_novelty_scorer(...)``).
        adapters: Prebuilt ``build_triage_adapters`` result; built here when ``None``.
        fetch_timeout: URL acquisition timeout in seconds.

    Returns:
        The ``InboxRuntime`` consumed by ``InboxProcessor`` and the FEAT-647 wiki target.

    Raises:
        WikiRuntimeError: If ``adapters`` is ``None`` and an LLM client cannot be built.
    """
    from parrot.knowledge.pageindex.toolkit import PageIndexToolkit
    from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
    from parrot.knowledge.wiki.documents import DocumentAcquirer
    from parrot.knowledge.wiki.inbox.processor import InboxRuntime
    from parrot.knowledge.wiki.ingest import WikiIngestOrchestrator
    from parrot.knowledge.wiki.models import WikiConfig
    from parrot.knowledge.wiki.search import WikiCombinedSearch
    from parrot.knowledge.wiki.triage import IngestTriageRouter

    if adapters is None:
        try:
            adapters = build_triage_adapters(lightweight_model, model)
        except Exception as exc:
            raise WikiRuntimeError(
                f"Could not build LLM client(s) for {lightweight_model!r}/{model!r}: {exc}"
            ) from exc
    light_adapter, heavy_adapter, light_model_id, same_provider = adapters
    # FILL IN: move cli._build_ingest_runtime from `wiki_dir = config.storage_path(root)` to the final
    #   `return InboxRuntime(...)` verbatim, with these exact substitutions:
    #   - `_cli_logger.info(` → `logger.info(`
    #   - `novelty_scorer = _build_novelty_scorer(root, config, store)` → DELETE (use the parameter)
    #   — bounded by "pure move" + InboxRuntime fields (processor.py:43)
```
**Why this shape**: model-id resolution (`click.echo`, coding-agent detection)
stays CLI-only; adapters and the novelty scorer are injectable so the CLI's
patchable seams keep controlling them and async callers can `await` the scorer.

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — import)
```python
# occurrences: 1 (verified: grep -c '^from parrot.knowledge.wiki.sources import SourceCollectionManager$' cli.py → 1)
# AFTER — insert below `from parrot.knowledge.wiki.sources import SourceCollectionManager` (verified: cli.py:110)
from parrot.knowledge.wiki.runtime import (
    WikiRuntimeError,
    build_ingest_runtime,
    build_novelty_scorer,
    build_triage_adapters,
)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (MODIFY — wrappers)
```python
# occurrences: 1 each (verified: grep -c for each def line → 1, 1, 1)
# REPLACE the BODY (keep signature + docstring) of:
#   `def _build_triage_adapters(lightweight_model: str, model: str) -> tuple[Any, Any, str, bool]:` (cli.py:4611)
    return build_triage_adapters(lightweight_model, model)

# REPLACE the BODY (keep signature + docstring) of:
#   `def _build_novelty_scorer(root: Path, config: WikiProjectConfig, store: BaseWikiStore) -> Any:` (cli.py:4671)
    return _run(build_novelty_scorer(root, config, store))

# REPLACE the BODY (keep signature + docstring incl. "Raises: click.ClickException") of:
#   `def _build_ingest_runtime(` (cli.py:4729)
    lightweight_model, model = _resolve_ingest_model_ids(lightweight_model_opt, model_opt)
    try:
        adapters = _build_triage_adapters(lightweight_model, model)
    except Exception as exc:
        raise click.ClickException(f"Could not build LLM client(s) for {lightweight_model!r}/{model!r}: {exc}") from exc
    novelty_scorer = _build_novelty_scorer(root, config, store)
    try:
        return build_ingest_runtime(
            root, config, store, sources, charter, charter_path,
            lightweight_model=lightweight_model, model=model,
            novelty_scorer=novelty_scorer, adapters=adapters, fetch_timeout=fetch_timeout,
        )
    except WikiRuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
```
**Why**: the CLI resolves adapters through its own module-global
`_build_triage_adapters` so `monkeypatch.setattr(wiki_cli, "_build_triage_adapters", …)`
keeps working; the ClickException message is byte-identical to today's.

### `packages/ai-parrot/tests/knowledge/wiki/test_ingest_runtime.py` (CREATE)
```python
"""FEAT-647 / TASK-4180 — public wiki ingest runtime."""
from pathlib import Path
from typing import Any

import click
import pytest

import parrot.knowledge.wiki.cli as wiki_cli
from parrot.knowledge.wiki import runtime as wiki_runtime
from parrot.knowledge.wiki.charter import load_charter
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import create_wiki_store

_CHARTER_YAML = """\
version: "1"
scope:
  include: []
  exclude: []
weights:
  density: 0.4
  novelty: 0.35
  durability: 0.25
thresholds:
  admit: 0.75
  reject: 0.35
calibration: {}
"""


class _FakeAdapter:
    """Never called during construction; only identity matters."""


@pytest.fixture
def wiki_project(tmp_path: Path) -> dict[str, Any]:
    # FILL IN: mkdir tmp_path/".parrot"/"wiki"; write _CHARTER_YAML to tmp_path/"charter.yaml";
    #   config = WikiProjectConfig(storage_dir=".parrot/wiki"); store = create_wiki_store(tmp_path/".parrot/wiki",
    #   backend="sqlite"); sources = SourceCollectionManager(storage / "sources", db_path=storage / "wiki.db",
    #   busy_timeout=config.sqlite_busy_timeout) with storage = config.storage_path(tmp_path) (verified: cli.py:541-547);
    #   return {"root", "config", "store", "sources", "charter_path"} — bounded by verified constructors only
    ...
```

### FILL IN checklist
- [ ] `runtime.py::build_triage_adapters` — verbatim move of cli.py:4632-4642
- [ ] `runtime.py::build_novelty_scorer` — verbatim move with `await _build_evaluator()`
- [ ] `runtime.py::build_ingest_runtime` — verbatim move with the two listed substitutions
- [ ] `test_ingest_runtime.py` — fixture + tests of the Test Specification

---

## Acceptance Criteria

- [ ] AC-1: `from parrot.knowledge.wiki.runtime import WikiRuntimeError, build_triage_adapters, build_novelty_scorer, build_ingest_runtime` works and `runtime.py` imports neither `click` nor `parrot.knowledge.wiki.cli`.
- [ ] AC-2: `build_ingest_runtime(..., adapters=<fakes>, novelty_scorer=<scorer>)` returns an `InboxRuntime` whose `light_adapter`/`heavy_adapter` are the fakes and `models == {"lightweight": ..., "heavy": ...}`.
- [ ] AC-3: with `adapters=None` and a failing `build_triage_adapters`, `WikiRuntimeError` is raised with message `Could not build LLM client(s) for '<l>'/'<m>': <exc>`.
- [ ] AC-4: `await build_novelty_scorer(...)` works inside a running loop (pytest-asyncio test) when no graph DB exists.
- [ ] AC-5: `wiki_cli._build_ingest_runtime` raises `click.ClickException` with the identical message when `_build_triage_adapters` fails, and honours a monkeypatched `wiki_cli._build_triage_adapters`.
- [ ] AC-6: existing tests pass unchanged: `tests/knowledge/wiki/test_cli.py`, `tests/knowledge/wiki/inbox/test_cli_inbox.py`, `tests/knowledge/wiki/inbox/test_end_to_end.py`.
- [ ] No linting errors.

- [ ] Lint clean: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/runtime.py packages/ai-parrot/src/parrot/knowledge/wiki/cli.py packages/ai-parrot/tests/knowledge/wiki/test_ingest_runtime.py`
---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_ingest_runtime.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_cli.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_cli_inbox.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/inbox/test_end_to_end.py -q`

---

## Test Specification

```python
def test_runtime_module_is_click_free():
    src = Path(wiki_runtime.__file__).read_text(encoding="utf-8")
    assert "import click" not in src and "wiki.cli" not in src


async def test_build_novelty_scorer_inside_loop(wiki_project):
    scorer = await wiki_runtime.build_novelty_scorer(wiki_project["root"], wiki_project["config"], wiki_project["store"])
    assert scorer is not None


async def test_build_ingest_runtime_with_injected_adapters(wiki_project):
    fake = _FakeAdapter()
    scorer = await wiki_runtime.build_novelty_scorer(wiki_project["root"], wiki_project["config"], wiki_project["store"])
    rt = wiki_runtime.build_ingest_runtime(
        wiki_project["root"], wiki_project["config"], wiki_project["store"], wiki_project["sources"],
        load_charter(wiki_project["charter_path"]), wiki_project["charter_path"],
        lightweight_model="google:light", model="google:heavy",
        novelty_scorer=scorer, adapters=(fake, fake, "light", True),
    )
    assert rt.light_adapter is fake and rt.models == {"lightweight": "google:light", "heavy": "google:heavy"}


def test_build_ingest_runtime_wraps_adapter_failure(wiki_project, monkeypatch):
    def _boom(l, m):
        raise ValueError("no key")
    monkeypatch.setattr(wiki_runtime, "build_triage_adapters", _boom)
    with pytest.raises(wiki_runtime.WikiRuntimeError, match=r"Could not build LLM client\(s\) for 'a:b'/'c:d': no key"):
        wiki_runtime.build_ingest_runtime(
            ..., lightweight_model="a:b", model="c:d", novelty_scorer=object(),  # FILL IN: positional args from fixture
        )


def test_cli_wrapper_keeps_click_message(wiki_project, monkeypatch):
    def _boom(l, m):
        raise ValueError("no key")
    monkeypatch.setattr(wiki_cli, "_build_triage_adapters", _boom)
    with pytest.raises(click.ClickException, match=r"Could not build LLM client\(s\) for 'a:b'/'c:d': no key"):
        wiki_cli._build_ingest_runtime(
            ..., lightweight_model_opt="a:b", model_opt="c:d",  # FILL IN: positional args from fixture
        )
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/teams-telegram-uploader-bookstore.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4180 teams-telegram-uploader-bookstore verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

## Completion Note

Implemented by engine seat; merged. Tests run via PYTHONPATH with main-checkout .so files (merge-tier validation failed on a worktree import env issue, not code). Pre-existing unrelated failures: pageindex test_adapter x2, test_okf_ontology.
