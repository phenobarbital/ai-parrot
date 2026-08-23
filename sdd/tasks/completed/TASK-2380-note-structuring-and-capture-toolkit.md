# TASK-2380: Note structuring + `capture_audio_note` toolkit

**Feature**: FEAT-452 — Audio Notes → Obsidian + LLM Wiki
**Spec**: `sdd/specs/audio-notes-obsidian.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Assigned-to**: unassigned
**Depends-on**: TASK-2379

---

## Context

Implements **Module 3** of the spec — the core of the feature (Goals G1, G2, G5).

One LLM-callable tool performs the whole capture as a single cohesive action:
structure → vault write → wiki ingest. The ordering is **load-bearing**: the
durable Obsidian note is committed *before* the optional wiki ingest is
attempted, so a wiki failure can never lose the thought.

The tool is **transport-neutral**. The text may come from a transcribed voice
note or from a typed message — *voice is only the vehicle* (spec §8, resolved).

---

## Scope

- Add Pydantic models `AudioNoteStructure` and `AudioNoteResult` (fields in the
  contract below).
- Add a structuring prompt builder and response parser, modelled on the parent's
  `_build_analysis_prompt` / `_parse_analysis_response`.
  **Language rule**: body/summary/key points/action items in the transcript's
  source language; **title and tags in English**.
- Add `AudioNoteCaptureToolkit(AbstractToolkit)` exposing exactly **one** public
  async method, `capture_audio_note(transcript, language=None)`.
  `AbstractToolkit` turns every public async method into a tool — keep all
  helpers underscore-prefixed so only the one tool is exposed.
- Capture pipeline inside the tool:
  1. Structure via one LLM call. On failure → verbatim fallback, `structured=False`.
  2. `create_note(path="audio-notes/<YYYY-MM-DD>-<slug>.md", content, frontmatter=okf)`.
     On `FileExistsError` → retry with `-2`, `-3`, … suffix.
  3. Preserve the raw transcript verbatim under a `## Transcript` heading.
  4. `ingest_source(notes_wiki_name, <abs path>)` — best-effort.
- Register the toolkit in `configure()` via `_initialize_tools([...])`.
- Add unit tests.

**NOT in scope**: `/note` sticky mode (TASK-2381); building the notes plane
(TASK-2379); namespace registration (TASK-2382); entity extraction (non-goal);
retaining audio (non-goal); HITL approval (non-goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/fireflies_wiki.py` | MODIFY | Models, prompt/parser, `AudioNoteCaptureToolkit`, `configure()` registration |
| `tests/test_fireflies_wiki_agent.py` | MODIFY | Unit tests for structuring, vault write, wiki ingest, fallbacks |

> ⚠️ `agents/` is **gitignored** (`.gitignore:287`). Commit with `git add -f agents/fireflies_wiki.py`.

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-23 against `dev`.

### Verified Imports

```python
from parrot.tools import AbstractToolkit          # parrot/tools/__init__.py:143
from parrot.tools.obsidian import ObsidianToolkit # parrot/tools/obsidian.py:78
from pydantic import BaseModel, Field             # project standard
# Already at the top of agents/fireflies_wiki.py:
from datetime import datetime, timezone           # line 33
from pathlib import Path                          # line 34
from typing import Any, Dict, List, Optional      # line 35
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):                      # line 78
    async def create_note(self, path: str, content: str,
                          frontmatter: Optional[Dict[str, Any]] = None
                          ) -> Dict[str, Any]:               # line 439
        """Create a new note (fails if it already exists).

        Raises: FileExistsError — if a note already exists at `path`.
        """
        # line 461: `import yaml` — frontmatter is rendered as a YAML block
        # line 466: await self.vault.write_note(path, text, overwrite=False)
        # returns {"created": True, "file": info.model_dump()}

# The agent's ObsidianToolkit allows exactly these operations
# (packages/ai-parrot/src/parrot/agents/obsidian.py:108-114):
#   {"read", "list", "search", "create", "update"}
#   -> `create` IS allowed. `append` and `delete` are NOT.

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                       # line 46
    async def ingest_source(self, wiki_name: str, source_path: str,
                            source_type: Optional[str] = None
                            ) -> dict[str, Any]:             # line 166
        """Ingest a raw source document into the wiki.

        Args:
            source_path: Absolute path to the source file.

        Returns: dict with keys source_id, pages_created,
                 graph_nodes_created, duration_ms, status.
        """

# packages/ai-parrot/src/parrot/agents/obsidian.py — the conventions to reuse
class FirefliesObsidianAgent(BasicAgent):                    # line 48
    ANALYSIS_HEADING: str = "## Analysis"                    # line 74
    vault_path: Path                                         # lines 96-100
    obsidian_toolkit: ObsidianToolkit                        # line 105

    @staticmethod
    def _make_note_title(date: str, meeting_title: str) -> str: ...   # line 728
    #   Returns "YYYY-MM-DD-kebab-case-title". Slugify logic at lines 745-753:
    #   lower() then replace " ", "_", "/", "&" with "-", then .strip("-")

    @staticmethod
    def _build_okf_frontmatter(fireflies_id: str, title: str, date: str,
                               participants: List[str],
                               duration: float) -> Dict[str, Any]: ...  # line 520
    #   Returns {"okf": {...}} built from a node dict with keys
    #   concept_id, title, ... (lines 543+). Mirror the SHAPE for notes;
    #   do NOT pass a fake fireflies_id.

    @staticmethod
    def _build_analysis_prompt(transcript_text: str,
                               granularity: str = "standard") -> str: ...  # line 758
    @staticmethod
    def _parse_analysis_response(llm_response: AIMessage) -> Dict[str, Any]: ...  # line 805
    #   ^ PROMPT/PARSER PAIR TO MODEL THE NEW ONE ON

    async def configure(self, app=None) -> None:             # line 120
        # line 132: self._initialize_tools([self.obsidian_toolkit])

# packages/ai-parrot/src/parrot/interfaces/tools.py
def _initialize_tools(self, tools: List[Union[str, AbstractTool, ToolDefinition]]
                      ) -> None: ...                          # line 26
#   Accepts: str | AbstractToolkit class OR INSTANCE | AbstractTool | ToolDefinition

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                   # line 216
    #   "A toolkit automatically converts all public async methods into tools" (line 220)
    #   Name = method name; Description = method docstring;
    #   Schema = auto-generated from type hints (lines 221-224)
    def get_tools(self, ...) -> ...: ...                      # line 484
    def _generate_tools(self) -> None: ...                    # line 537

# agents/fireflies_wiki.py
_DEFAULT_LLM: str = "anthropic:claude-haiku-4-5"              # line 146
class FirefliesWikiAgent(FirefliesObsidianAgent):             # line 165
    _notes_wiki: Optional[Any]      # CREATED BY TASK-2379 — None when unavailable
    notes_wiki_name: str            # CREATED BY TASK-2379
    notes_folder: str               # CREATED BY TASK-2379 — default "audio-notes"
```

### Models to Create (from spec §2 Data Models)

```python
class AudioNoteStructure(BaseModel):
    title: str                 # English — used for the slug
    tags: list[str]            # English
    summary: str               # source language
    key_points: list[str]      # source language
    action_items: list[str]    # source language, may be empty

class AudioNoteResult(BaseModel):
    note_title: str                     # "YYYY-MM-DD-slug"
    vault_path: str                     # "audio-notes/YYYY-MM-DD-slug.md"
    wiki_ingested: bool
    wiki_reason: Optional[str] = None   # set when wiki_ingested is False
    structured: bool                    # False when the verbatim fallback ran
```

### Does NOT Exist

- ~~`LLMWikiToolkit.ingest_text()`~~ / ~~`ingest_markdown()`~~ / ~~`ingest_content()`~~
  — **do not exist.** Ingestion is **path-based**:
  `ingest_source(wiki_name, source_path, source_type=None)`.
  You must write the file to disk FIRST, then pass its **absolute** path.
- ~~`ObsidianToolkit.create_note(..., overwrite=True)`~~ — **no `overwrite`
  parameter.** The signature is `(path, content, frontmatter=None)` and it
  always writes with `overwrite=False` internally (line 466). A collision
  raises `FileExistsError` — that is the retry signal, not an error to surface.
- ~~`ObsidianToolkit.append_note`~~ is available to this agent — **it is not.**
  `allowed_operations` is `{"read","list","search","create","update"}`
  (`obsidian.py:108-114`); `append` is excluded.
- ~~`ObsidianToolkit.create_audio_note()`~~ — not a real method.
- ~~`AudioNoteStructure`~~, ~~`AudioNoteResult`~~, ~~`AudioNoteCaptureToolkit`~~,
  ~~`capture_audio_note`~~ — none exist yet; **this task creates them**.
- ~~`WikiConfig.extract_entities`~~ — no such field, and extraction is an
  explicit non-goal of FEAT-452. Do not attempt it.
- ~~`TranscriptionResult` is available inside the agent~~ — it is **not** passed
  in. The tool receives a plain `transcript: str` and an optional
  `language: str`. Do not import `TranscriptionResult` here.
- ~~`_build_okf_frontmatter` accepts a note-shaped payload~~ — its signature is
  `(fireflies_id, title, date, participants, duration)` (`obsidian.py:520`).
  Mirror the returned `{"okf": {...}}` SHAPE for notes; do not call it with
  fabricated meeting arguments.

---

## Implementation Notes

### Pattern to Follow

- **Prompt/parser symmetry**: model the pair on `_build_analysis_prompt` /
  `_parse_analysis_response` (`obsidian.py:758`, `:805`) rather than inventing
  a second convention.
- **Note title**: reuse `_make_note_title(date, title)` (`obsidian.py:728`)
  verbatim — it already produces `YYYY-MM-DD-kebab-case-title`.
- **Transcript preservation**: mirror the `ANALYSIS_HEADING` convention
  (`obsidian.py:74`) with a `## Transcript` heading.

### Key Constraints

- **Exactly ONE LLM call per capture.** This is an acceptance criterion. Do not
  add a second pass for tags, titles or classification.
- Route the LLM call through the agent's configured client (`AbstractClient`) —
  **never** the Anthropic SDK directly.
- **Ordering is load-bearing**: vault write MUST be committed before the wiki
  ingest is attempted.
- **Failure asymmetry**:
  - LLM structuring fails → verbatim note, `structured=False`, no exception.
  - `_notes_wiki is None` → `wiki_ingested=False`, note still written.
  - `ingest_source` raises → warn, `wiki_ingested=False`, note still written.
  - **Vault write fails → surface it.** This is the one failure the user must see.
- `ingest_source` needs an **absolute** path; `create_note` takes a
  **vault-relative** path. Compose the absolute path as
  `self.vault_path / notes_folder / f"{note_title}.md"`.
- Only `capture_audio_note` may be public on the toolkit — every helper must be
  underscore-prefixed or `AbstractToolkit` will expose it as a tool too.
- The tool docstring **is** the LLM's tool description. Make it say: call this
  when the user is recording something to REMEMBER (note, idea, decision,
  reminder, follow-up) rather than asking a question; and that the text may be
  spoken or typed.

### References in Codebase

- `packages/ai-parrot/src/parrot/agents/obsidian.py:758`, `:805` — prompt/parser pair
- `packages/ai-parrot/src/parrot/agents/obsidian.py:728` — note-title convention
- `packages/ai-parrot/src/parrot/tools/obsidian.py:439` — `create_note`
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:166` — `ingest_source`

---

## Acceptance Criteria

- [ ] The note is written to `audio-notes/YYYY-MM-DD-<slug>.md`
- [ ] The raw transcript is preserved verbatim under `## Transcript`
- [ ] Body/summary/key points/action items are in the source language; title and
      tags are in English
- [ ] A same-day slug collision retries with `-2`, then `-3`
- [ ] LLM structuring failure → verbatim note written, `structured=False`, no raise
- [ ] `_notes_wiki is None` → note written, `wiki_ingested=False`
- [ ] `ingest_source` raising → note written, `wiki_ingested=False`, no raise
- [ ] A vault write failure IS surfaced (does not report success)
- [ ] `ingest_source` receives an **absolute** path
- [ ] Exactly **one** LLM call per capture
- [ ] `AbstractToolkit.get_tools()` on the capture toolkit returns exactly **one** tool
- [ ] The tool is registered and visible to the agent's LLM after `configure()`
- [ ] The tool works with `language=None` (typed input)
- [ ] Tests pass: `pytest tests/test_fireflies_wiki_agent.py -v`
- [ ] No linting errors: `ruff check agents/fireflies_wiki.py`
- [ ] Committed with `git add -f agents/fireflies_wiki.py`

---

## Test Specification

```python
# tests/test_fireflies_wiki_agent.py  (EXTEND the existing module)
# Reuse the existing _load_agent_module() path-import helper and skipif guard.

class TestAudioNoteCapture:
    async def test_note_path_and_transcript_preserved(self, toolkit):
        """Note lands in audio-notes/ with the raw transcript under ## Transcript."""
        result = await toolkit.capture_audio_note("recordar comprar leche", language="es")
        assert result["vault_path"].startswith("audio-notes/")
        content = _written_content()
        assert "## Transcript" in content
        assert "recordar comprar leche" in content

    async def test_language_split(self, toolkit):
        """Spanish body, English title and tags."""

    async def test_slug_collision_retries_with_suffix(self, toolkit):
        """FileExistsError on the first path -> retry as -2."""
        obsidian.create_note.side_effect = [FileExistsError, {"created": True, "file": {}}]

    async def test_llm_failure_writes_verbatim(self, toolkit):
        """Structuring failure still writes a note, flagged structured=False."""
        assert result["structured"] is False

    async def test_wiki_unavailable_keeps_note(self, toolkit):
        """_notes_wiki is None -> note written, wiki_ingested False."""
        assert result["wiki_ingested"] is False

    async def test_ingest_error_keeps_note(self, toolkit):
        """ingest_source raising does not propagate and does not lose the note."""

    async def test_vault_failure_surfaces(self, toolkit):
        """A vault write failure is NOT swallowed."""
        with pytest.raises(Exception):
            await toolkit.capture_audio_note("...")

    async def test_ingest_source_receives_absolute_path(self, toolkit):
        """ingest_source is called with an absolute path, not a vault-relative one."""
        assert Path(wiki.ingest_source.call_args[0][1]).is_absolute()

    async def test_exactly_one_llm_call(self, toolkit):
        """The capture path makes exactly one LLM call."""
        assert llm.call_count == 1

    def test_toolkit_exposes_single_tool(self, toolkit):
        """Only capture_audio_note is exposed; helpers stay private."""
        assert [t.name for t in toolkit.get_tools()] == ["capture_audio_note"]

    async def test_typed_input_without_language(self, toolkit):
        """language=None (typed note) works."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** — §2 Overview, §2 Data Models, §2 New Public Interfaces, §3 Module 3, §7 Known Risks
2. **Check dependencies** — TASK-2379 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `tools/obsidian.py:439-470`,
   `wiki/toolkit.py:166-195` and `agents/obsidian.py:720-840` before writing code
4. **Update status** in `sdd/tasks/index/audio-notes-obsidian.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2380-note-structuring-and-capture-toolkit.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude session 2026-08-23)
**Date**: 2026-08-23
**Notes**: Added `AudioNoteStructure`/`AudioNoteResult` Pydantic models,
`_build_note_structuring_prompt` / `_parse_note_structure_response`
(modelled on `_build_analysis_prompt` / `_parse_analysis_response` —
labelled `##` sections), `_build_note_okf_frontmatter` (OKF `{"okf": {...}}`
shape via the real `project_okf_block`/`ConceptType.DOCUMENT_NODE`
machinery, best-effort → `{}` on failure — same posture as
`_build_okf_frontmatter`), and `AudioNoteCaptureToolkit(AbstractToolkit)`
exposing exactly one public method, `capture_audio_note(transcript,
language=None)`. Pipeline: structure (1 LLM call, verbatim fallback on any
failure) → `create_note()` with `FileExistsError` → `-2`/`-3`… retry
(propagates any other exception, so a real vault failure surfaces) →
best-effort `ingest_source(notes_wiki_name, <absolute path>)`. Wired into
`configure()` via `_initialize_tools([capture_toolkit])`, injecting
`obsidian_toolkit=self.obsidian_toolkit`,
`notes_wiki_provider=lambda: self._notes_wiki` (always reads the live
value), `llm_call=self.client.complete`, `vault_path=self.vault_path`,
`notes_folder=self.notes_folder`, `wiki_name=self.notes_wiki_name`.

Added `TestAudioNoteCapture` (12 tests covering every AC: transcript
path/preservation, language split, slug-collision retry, LLM-failure
fallback, wiki-unavailable / ingest-error resilience, vault-failure
surfacing, absolute-path ingest, exactly-one-LLM-call, single-tool
exposure, typed-input `language=None`). Full suite:
`pytest tests/test_fireflies_wiki_agent.py -v` → 49 passed. `ruff check
agents/fireflies_wiki.py`: new code introduces no findings beyond the
file's pre-existing `Optional[X]`/`List[X]`/`datetime.utcnow` style
findings (matched existing convention, no unrelated rewrite). Committed
with `git add -f agents/fireflies_wiki.py`.

The `configure()` wiring itself (the `_initialize_tools([capture_toolkit])`
call) was verified with a manual end-to-end smoke script (structure → real
`create_note`/`ingest_source` call shapes, `get_tools()` → exactly
`capture_audio_note`) rather than a `configure()`-level unit test — no
existing test in this file drives `configure()` end-to-end (it needs
`tool_manager`/`client`/MCP wiring the lightweight `__new__`-built `agent`
fixture doesn't set up); the established convention here is to unit-test
the constituent builder methods directly, which `TestAudioNoteCapture`
does for the toolkit itself.

**Deviations from spec**: (1) The spec's illustrative
`AudioNoteCaptureToolkit.__init__` pseudocode omits a `vault_path`
parameter, but computing the **absolute** path `ingest_source` requires
(per this task's own Implementation Notes: "Compose the absolute path as
`self.vault_path / notes_folder / ...`") needs the vault root inside the
toolkit itself — added `vault_path: Path` as a required constructor
parameter, populated from `self.vault_path` at `configure()` time.
(2) The spec's pseudocode types `llm_call` as
`Callable[[str], Awaitable[AIMessage]]`; verified via
`packages/ai-parrot/src/parrot/clients/base.py:983` that
`AbstractClient.complete()` actually returns `str` (its own docstring:
"collapse to a single string here") — typed `llm_call` as
`Callable[[str], Awaitable[str]]` and parse a plain string instead, wiring
`llm_call=self.client.complete` directly (still `AbstractClient`, never the
Anthropic SDK). (3) Added two imports not in the original Codebase
Contract — `project_okf_block` (`parrot.interfaces.obsidian.okf`) and
`ConceptType` (`parrot.knowledge.okf.ontology`) — verified by direct source
read (`okf.py:71`, `_build_model` requires only `concept_id`; ontology.py:57
confirms `DOCUMENT_NODE`) before use, per the anti-hallucination protocol,
since `_build_okf_frontmatter`'s fixed meeting-shaped signature could not
be reused as-is (contract explicitly forbids fabricating meeting args).
