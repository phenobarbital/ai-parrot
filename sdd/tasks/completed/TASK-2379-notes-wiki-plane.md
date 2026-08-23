# TASK-2379: Build the separate `notes` wiki plane

**Feature**: FEAT-452 — Audio Notes → Obsidian + LLM Wiki
**Spec**: `sdd/specs/audio-notes-obsidian.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec (Goal G2).

Audio notes go into their **own** wiki plane so personal thinking does not
dilute meeting retrieval. This is **not a parameter change** — it requires a
second `LLMWikiToolkit` instance.

`LLMWikiToolkit._config_for()` (`wiki/toolkit.py:1205`) **raises `ValueError`**
when the requested `wiki_name` does not match the toolkit's own configured
wiki. Its docstring is explicit: *"Construct a separate LLMWikiToolkit for each
wiki instance."* Passing `"notes"` to the existing `self._wiki` will raise, not
route.

Because the two planes use **different storage roots**, they share no manifest
and no `wiki.db` — there is no cross-instance consistency hazard.

---

## Scope

- Add three module-level config constants using the existing env helpers:
  `AUDIO_NOTES_WIKI_NAME` (default `"notes"`),
  `AUDIO_NOTES_WIKI_STORAGE_DIR` (default `~/.parrot/wikis/notes`),
  `AUDIO_NOTES_FOLDER` (default `"audio-notes"`).
- Add the instance attributes `notes_wiki_name`, `notes_wiki_storage_dir`,
  `notes_folder`, and `_notes_wiki: Optional[Any] = None` in `__init__`,
  with constructor overrides mirroring the existing `wiki_name` / `wiki_storage_dir`.
- Implement `async def _build_notes_wiki_toolkit(self) -> Optional[Any]` — a
  near-copy of `_build_wiki_toolkit()` (line 243) pointed at the notes storage
  root, with its own PageIndex plane and its own graph toolkit
  (`tenant_id=self.notes_wiki_name`).
- Call `create_wiki(self.notes_wiki_name)` once after construction to bootstrap
  the layout. It is **idempotent** (see contract) — tolerate repeat calls.
- Wire the call into `configure()` alongside the existing `self._wiki` build.
- Best-effort throughout: any failure logs a warning, leaves `_notes_wiki = None`,
  and lets the agent boot.
- Add unit tests.

**NOT in scope**: the capture tool (TASK-2380); `/note` (TASK-2381); namespace
registration (TASK-2382); any entity extraction (an explicit non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/fireflies_wiki.py` | MODIFY | Config constants, attributes, `_build_notes_wiki_toolkit()`, `configure()` wiring |
| `tests/test_fireflies_wiki_agent.py` | MODIFY | Unit tests for the second plane |

> ⚠️ `agents/` is **gitignored** (`.gitignore:287`). Commit with `git add -f agents/fireflies_wiki.py`.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-23 against `dev`.

### Verified Imports

```python
# ALL already imported inside agents/fireflies_wiki.py — reuse the existing
# function-local import style used by _build_wiki_toolkit / _build_pageindex_toolkit.
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit  # line 255
from parrot.knowledge.wiki.models import WikiConfig                          # line 258
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit                     # line 259
from parrot.clients.factory import LLMFactory                                # line 314
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter       # line 315
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit              # line 316

# Module top-level (already present):
from navconfig import config     # line 36
from pathlib import Path         # line 34
```

### Existing Signatures to Use

```python
# agents/fireflies_wiki.py — the pattern to copy
def _int_env(key: str, default: int) -> int: ...             # line 56
def _bool_env(key: str, default: bool = False) -> bool: ...  # line 76
def _list_env(key: str) -> List[str]: ...                    # line 91

_DEFAULT_LLM: str = "anthropic:claude-haiku-4-5"             # line 146
_LLM: str = config.get("FIREFLIES_WIKI_LLM", fallback=_DEFAULT_LLM)   # line 147
_WIKI_NAME: str = config.get("FIREFLIES_WIKI_NAME", fallback="meetings")   # line 150
_WIKI_STORAGE_DIR: str = config.get("FIREFLIES_WIKI_STORAGE_DIR",
    fallback=str(Path.home() / ".parrot" / "wikis" / "meetings"))          # line 151

class FirefliesWikiAgent(FirefliesObsidianAgent):             # line 165
    wiki_name: str                                            # line 208
    wiki_storage_dir: Path                                    # line 209
    _wiki: Optional[Any]                                      # line 224

    async def configure(self, app=None) -> None:              # line 230
        # body: await super().configure(app)
        #       self._wiki = await self._build_wiki_toolkit()

    async def _build_wiki_toolkit(self) -> Optional[Any]:     # line 243
        # THE PATTERN TO COPY. Shape:
        #   try:
        #       <function-local imports>
        #       storage = self.wiki_storage_dir
        #       storage.mkdir(parents=True, exist_ok=True)
        #       pageindex_toolkit = self._build_pageindex_toolkit(storage)
        #       graph_toolkit = await build_graph_memory_toolkit(
        #           storage / "graph", tenant_id=self.wiki_name, agent_id=self.name)
        #       wiki_config = WikiConfig(
        #           wiki_name=self.wiki_name, storage_dir=storage, sync_graph=True)
        #       toolkit = LLMWikiToolkit(
        #           pageindex_toolkit, graph_toolkit, None, wiki_config,
        #           agent_id=self.name)
        #       self.logger.info(...)
        #       return toolkit
        #   except Exception as exc:  # noqa: BLE001
        #       self.logger.warning(...)
        #       return None

    def _build_pageindex_toolkit(self, storage: Path) -> Optional[Any]: ...  # line 298
        # Uses config.get("WIKI_MODEL") or _LLM; builds PageIndexLLMAdapter over
        # LLMFactory.create(model_spec); returns PageIndexToolkit(adapter,
        # storage_dir=storage / "pageindex"). Returns None on failure.
        # REUSABLE AS-IS for the notes plane — pass the notes storage root.

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                        # line 46
    def __init__(self, pageindex_toolkit, graph_toolkit, <third_positional>,
                 config: WikiConfig, agent_id: str = ...): ...  # line 75
    async def create_wiki(self, wiki_name: str,
                          description: Optional[str] = None) -> dict[str, Any]: ...  # line 445
    #   IDEMPOTENT — verified:
    #     for d in directories:            # line 475
    #         if not d.exists():           # line 476  <<< guard
    #             d.mkdir(parents=True, exist_ok=True)   # line 477
    #     await asyncio.to_thread(self._bookkeeper.write_index, ...)   # line 481
    #     await asyncio.to_thread(self._bookkeeper.log_operation, ..., "CREATE", ...)  # line 484
    #   Creates only `{storage_dir}/sources`; writes index.md + log.md.
    #   Repeat calls append a duplicate CREATE log line (cosmetic, harmless).

    def _config_for(self, wiki_name: str) -> WikiConfig: ...  # line 1205
    #   *** RAISES ValueError when wiki_name != self._config.wiki_name (lines 1222-1226):
    #       "Wiki '{wiki_name}' is not managed by this toolkit (configured for
    #        '{...}'). Construct a separate LLMWikiToolkit for each wiki instance."
    #   THIS is why a second instance is mandatory. ***

# packages/ai-parrot/src/parrot/knowledge/wiki/models.py
class WikiConfig(BaseModel):                                  # line 52
    wiki_name: str                                            # line 83 — required
    storage_dir: Path                                         # line 84 — required
    source_dir: Optional[Path] = None                         # line 85 — defaults to storage_dir/sources
    page_categories: list[WikiPageCategory]                   # line 89
    # plus: search_weights, lightweight_model, model, sync_graph,
    #       storage_backend, charter_path   (see the class docstring, lines 53-81)
```

### Does NOT Exist

- ~~`WikiConfig.extract_entities`~~ — **no such field.** Verified against the
  full field list at `models.py:83+`. Entity extraction is a non-goal here anyway.
- ~~One `LLMWikiToolkit` serving multiple wikis~~ — **false.** `_config_for`
  raises on mismatch. Never pass `"notes"` to `self._wiki`.
- ~~`LLMWikiToolkit.create_wiki` fails when the wiki already exists~~ — **false.**
  It is idempotent (`toolkit.py:475-477`). No `exist_ok` argument is needed
  or accepted.
- ~~`FirefliesWikiAgent._notes_wiki`~~ / ~~`.notes_wiki_name`~~ /
  ~~`.notes_folder`~~ / ~~`._build_notes_wiki_toolkit()`~~ — none exist yet;
  **this task creates them**.
- ~~`build_graph_memory_toolkit` is synchronous~~ — it is **awaited**
  (`fireflies_wiki.py:256`). It is an async factory.
- ~~`LLMWikiToolkit.__init__` takes keyword-only planes~~ — the first three
  arguments are **positional** (`pageindex_toolkit, graph_toolkit, <third>`),
  followed by `config` and `agent_id`. Copy the existing call at
  `fireflies_wiki.py:266-272` verbatim in shape.

---

## Implementation Notes

### Pattern to Follow

`_build_notes_wiki_toolkit()` is a near-copy of `_build_wiki_toolkit()`
(line 243) with `wiki_name` → `notes_wiki_name` and `wiki_storage_dir` →
`notes_wiki_storage_dir`. Consider factoring the shared body into a private
helper taking `(wiki_name, storage_dir)` — but only if it does not disturb the
existing meetings path, which must keep behaving identically.

### Key Constraints

- **Best-effort.** Wrap everything in `try/except Exception`, log a warning,
  return `None`. The agent must always boot — this mirrors the existing posture
  at lines 289-297.
- `create_wiki` failure must **not** null out an otherwise working toolkit —
  log and continue.
- Use `_bool_env` / plain `config.get(...)` for the new constants, matching
  lines 146-157. Constants are module-level because they are read at import time.
- `notes_wiki_storage_dir` must be `.expanduser()`-ed, like line 209-211.
- The graph toolkit must use `tenant_id=self.notes_wiki_name` so the notes graph
  is isolated from the meetings graph.

### References in Codebase

- `agents/fireflies_wiki.py:243` — `_build_wiki_toolkit()`, the pattern
- `agents/fireflies_wiki.py:298` — `_build_pageindex_toolkit()`, reusable as-is
- `agents/fireflies_wiki.py:230` — `configure()`, the wiring point

---

## Acceptance Criteria

- [ ] `self._notes_wiki` is a **distinct object** from `self._wiki`
- [ ] The two toolkits have different `wiki_name` and different `storage_dir`
- [ ] `create_wiki` is called for the notes plane and a second `configure()`
      does not error
- [ ] A construction failure leaves `_notes_wiki is None` and `configure()`
      does not raise
- [ ] The meetings plane's behavior is byte-identical to before
- [ ] The three config keys are honored, with the documented defaults
- [ ] Tests pass: `pytest tests/test_fireflies_wiki_agent.py -v`
- [ ] No linting errors: `ruff check agents/fireflies_wiki.py`
- [ ] Committed with `git add -f agents/fireflies_wiki.py`

---

## Test Specification

```python
# tests/test_fireflies_wiki_agent.py  (EXTEND the existing module)
#
# Reuse the existing _load_agent_module() path-import helper and the module-level
# skipif guard. Do NOT invent a new import mechanism.

class TestNotesWikiPlane:
    async def test_separate_instance_from_meetings(self, agent):
        """The notes plane is a distinct toolkit with its own name and storage."""
        assert agent._notes_wiki is not agent._wiki

    async def test_defaults(self):
        """Unset env yields notes / ~/.parrot/wikis/notes / audio-notes."""
        assert agent.notes_wiki_name == "notes"
        assert agent.notes_folder == "audio-notes"

    async def test_create_wiki_called_and_idempotent(self, agent):
        """create_wiki bootstraps the plane and tolerates a second configure()."""

    async def test_build_failure_returns_none(self, monkeypatch):
        """A construction error leaves _notes_wiki as None without raising."""
        assert agent._notes_wiki is None

    async def test_meetings_plane_unaffected(self, agent):
        """self._wiki is still built exactly as before."""

    async def test_graph_tenant_isolated(self, agent):
        """build_graph_memory_toolkit receives tenant_id=notes_wiki_name."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 "Two separate wiki toolkit instances", §2 "Wiki bootstrapping", §3 Module 2
2. **Check dependencies** — none
3. **Verify the Codebase Contract** — re-read `agents/fireflies_wiki.py:243-340`
   and `wiki/toolkit.py:445-497` before editing
4. **Update status** in `sdd/tasks/index/audio-notes-obsidian.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2379-notes-wiki-plane.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added three module-level config constants
(`_AUDIO_NOTES_WIKI_NAME`, `_AUDIO_NOTES_WIKI_STORAGE_DIR`,
`_AUDIO_NOTES_FOLDER`) with the documented defaults, plus the matching
constructor params/attributes (`notes_wiki_name`, `notes_wiki_storage_dir`
— `.expanduser()`-ed, `notes_folder`) and `self._notes_wiki: Optional[Any]
= None`. Implemented `_build_notes_wiki_toolkit()` as a near-copy of
`_build_wiki_toolkit()`, reusing `_build_pageindex_toolkit()` as-is,
`tenant_id=self.notes_wiki_name` for graph isolation, and its own
`WikiConfig`/`LLMWikiToolkit` instance — never the shared `self._wiki`.
Added an idempotent `create_wiki(self.notes_wiki_name)` bootstrap call
whose own failure is caught separately and does not null out an otherwise
working toolkit. Wired into `configure()` right after the existing
`self._wiki` build, both best-effort. `configure()` and `_build_wiki_toolkit()`
for the meetings plane are otherwise byte-identical.

Added `TestNotesWikiPlane` (7 tests: separate-instance, defaults,
create_wiki idempotency, create_wiki-failure resilience, build-failure →
None, meetings-plane-unaffected, graph-tenant-isolation) by monkeypatching
the same three seams `_build_wiki_toolkit` uses
(`build_graph_memory_toolkit`, `WikiConfig`, `LLMWikiToolkit`) at their
source modules — no test file previously covered `_build_wiki_toolkit`
itself, so this also exercises the meetings path via
`test_meetings_plane_unaffected`. Full suite:
`pytest tests/test_fireflies_wiki_agent.py -v` → 38 passed. `ruff check
agents/fireflies_wiki.py` / test file: new code introduces no findings
beyond the file's pre-existing `Optional[X]`-style `UP045`/`UP006`
findings (the file predates the `X | None` convention throughout; matched
existing style rather than doing an unrelated file-wide rewrite).
Committed with `git add -f agents/fireflies_wiki.py`.

**Deviations from spec**: none
