---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Audio Notes → Obsidian + LLM Wiki

**Feature ID**: FEAT-452
**Date**: 2026-08-23
**Author**: Jesus Lara (spec: Claude session 2026-08-23)
**Status**: approved
**Target version**: next minor
**Input**: `sdd/proposals/audio-notes-obsidian.brainstorm.md` (status `exploration`, Recommended Option A)
**Depends on**: FEAT-450 (`sdd/specs/wiki-namespaces.spec.md`) — hard prerequisite, see §7 and Worktree Strategy

---

## 1. Motivation & Business Requirements

### Problem Statement

`FirefliesWikiAgent` (`agents/fireflies_wiki.py:165`) already owns a complete
**meeting** knowledge pipeline: Fireflies → Obsidian vault → per-meeting LLM
analysis → GraphIndex LLM Wiki, plus daily/weekly email digests. That pipeline
is *scheduled and batch-oriented* — it only ever ingests what Fireflies
recorded.

But a large share of durable knowledge never happens in a recorded meeting. It
happens **in the moment**: walking, driving, between calls — a decision, an
idea, a follow-up, a piece of context that will be gone in ten minutes.

Meanwhile the Telegram integration *already* transcribes voice notes end to
end. `TelegramAgentWrapper.handle_voice()` (`wrapper.py:3409`) downloads the
OGG, transcribes it via `VoiceTranscriber.transcribe_file()` (`wrapper.py:3546`),
and feeds the resulting text into `_invoke_agent()` as an ordinary message
inside `telegram_chat_scope(chat_id)` (`wrapper.py:3590`).

**The gap is small and specific**: that transcript is treated as a *question*
and answered, then discarded. There is no path that turns a spoken thought into
a structured Obsidian note **and** a queryable wiki page. The transport,
transcription, vault plane and wiki plane all already exist and are wired to the
same agent — nothing connects them.

**Who is affected**: the single operator of `FirefliesWikiAgent` (the vault
owner). Success is blunt and measurable: speak a thought into Telegram, and
seconds later `wikitoolkit query` can find it.

### Goals

- **G1** Turn a transcribed voice note into a structured Obsidian note at
  `audio-notes/YYYY-MM-DD-<slug>.md`, with OKF frontmatter and the verbatim
  transcript preserved under a `## Transcript` heading.
- **G2** Ingest that note into a **separate `notes` wiki plane** immediately at
  capture time — not deferred to the nightly job — so it is queryable within
  seconds.
- **G3** Trigger capture by LLM intent detection, with a deterministic `/note`
  override for when intent detection misfires.
- **G4** Reuse the existing transport, transcription, vault and wiki machinery.
  New code is connective tissue only — no parallel stack, no new external
  dependency.
- **G5** Never lose the thought: a wiki-plane failure, an LLM structuring
  failure, or an unavailable notes plane must all still leave a durable note in
  Obsidian.
- **G6** Stop the meetings wiki from absorbing audio notes (see §2 "Vault
  scoping" — a latent defect this feature must fix to meet G2's separation).
- **G7** No regression to existing behavior: when the capture tool is never
  invoked, every existing path behaves byte-identically.

### Non-Goals (explicitly out of scope)

- **Multi-tenancy.** Single user, one vault. No per-chat-id vault or wiki
  routing.
- **Retaining the original audio.** Discarded, per the existing `finally` block
  in `handle_voice`. No audio at rest.
- **HITL approve-before-commit.** Confirmation is a single silent line;
  corrections happen later in Obsidian.
- **A general-purpose reusable audio-note toolkit.** A standalone
  `AudioNoteToolkit` mountable by any agent was rejected in brainstorm — see
  `proposals/audio-notes-obsidian.brainstorm.md` Option B. There is exactly one
  consumer today; the capture toolkit is agent-local.
- **Channel-side capture in the Telegram wrapper.** Rejected in brainstorm
  Option C — wrong layer, Telegram-only.
- **Charter-driven supervised ingestion of voice notes.** Rejected for now in
  brainstorm Option D (batch/review latency profile is the opposite of what
  fleeting-thought capture needs). Revisit after FEAT-451.
- **Raw-audio entry points** (HTTP upload, watched folder, email attachment).
- **Changing `handle_voice()` itself.** Untouched by this feature.
- **Injecting a `FederatedWikiStore` into `LLMWikiToolkit`.** FEAT-450 lists
  this as optional and explicitly not required for its own acceptance
  (`wiki-namespaces.spec.md:153`); it is not in scope here either.

---

## 2. Architectural Design

### Overview

The transcript reaches the agent as a normal message — **`handle_voice()` is not
modified**. The agent gains one new LLM-callable tool, `capture_audio_note`,
which performs the whole capture as a single cohesive action:

1. **Structure** the raw transcript with one LLM call on the agent's pinned
   Claude Haiku 4.5 (`_DEFAULT_LLM`, `agents/fireflies_wiki.py:146`) — producing
   an English title, English tags, and a same-language summary, key points and
   action items.
2. **Write** it to `audio-notes/YYYY-MM-DD-<slug>.md` via
   `ObsidianToolkit.create_note()` with OKF frontmatter.
3. **Ingest** that single file into the `notes` wiki via
   `LLMWikiToolkit.ingest_source()`.
4. **Return** the note title, which the agent echoes as one line.

The ordering is load-bearing, in the same spirit as `sync_meetings_to_wiki`'s
documented step order: **the vault write is committed before the wiki ingest is
attempted**, so the durable artifact exists before the optional one.

**Two triggers.** The LLM detects capture intent from phrasing ("note to
self…", "remember that…", "idea:…"). For when it misfires, `/note` arms exactly
one capture: the next voice or text message in that chat is captured with no
intent guessing, and the mode clears (consume-on-next-message).

**Two separate wiki toolkit instances.** `LLMWikiToolkit._config_for()`
(`toolkit.py:1205`) raises `ValueError` when `wiki_name` does not match its own
configured wiki — its docstring is explicit: *"Construct a separate
LLMWikiToolkit for each wiki instance."* A separate `notes` wiki is therefore
**not a parameter**; it requires a second toolkit instance with its own
`WikiConfig`, PageIndex plane and GraphIndex plane. `FirefliesWikiAgent` will
hold both `self._wiki` (meetings, existing) and `self._notes_wiki` (new), each
built by the same best-effort pattern as `_build_wiki_toolkit()`
(`agents/fireflies_wiki.py:243`). Because the two planes have **different
storage roots**, they share no manifest and no `wiki.db`; there is no
cross-instance consistency hazard.

**Vault scoping (G6).** `sync_meetings_to_wiki` currently calls
`ingest_obsidian_vault(self.wiki_name, str(self.vault_path), incremental=True)`
(`agents/fireflies_wiki.py:425`) against the **whole vault**, and the verified
signature has **no folder-filter parameter** (`toolkit.py:196`). As written, the
nightly job would sweep `audio-notes/` into the *meetings* wiki, defeating G2's
separation. The fix is to narrow that call to
`str(self.vault_path / self.meetings_folder)` — the path-based API already
supports it. This is a latent defect independent of this feature (the meetings
wiki has been ingesting every unrelated note in the vault all along) and is
corrected here because G2 depends on it.

**Wiki write mechanism.** `ingest_source()` is used, not `create_page()`.
`create_page()` writes a page with no entry in the source manifest, so the
nightly incremental pass would later see the same note as a new file and author
a **second** page for it. `ingest_source()` registers the note in the manifest,
making the immediate write and any later incremental pass agree, and making
`reingest_source()` work after the note is hand-edited in Obsidian.

**Wiki bootstrapping.** `create_wiki()` (`toolkit.py:445`) is called once at
configure time for the notes plane. It is idempotent by inspection: directory
creation is guarded by `if not d.exists()` (`toolkit.py:475-477`), and
`write_index` / `log_operation` are safe to repeat.

**`/note` and the chat-scope gap.** `@telegram_command` (`decorators.py:5`)
already lets an agent declare a slash command with no wrapper change. But
`_register_agent_commands`'s inner `agent_cmd_handler` (`wrapper.py:749-794`)
never enters `telegram_chat_scope`, so an agent command **cannot currently
resolve which chat invoked it** — which per-chat sticky mode requires. This
feature adds that scope wrapper: a small additive change that benefits every
agent command, not just this one.

### Component Diagram

```
Telegram voice note
        │
        ▼
handle_voice()  ── UNCHANGED ── wrapper.py:3409
  download → VoiceTranscriber.transcribe_file() → TranscriptionResult
        │
        ▼  with telegram_chat_scope(chat_id)   wrapper.py:3590
   _invoke_agent(transcript)
        │
        ▼
FirefliesWikiAgent  (LLM tool-calling loop)
        │
        ├── intent detected  ─────┐
        │                          │
        └── /note armed for chat ──┤   agent_cmd_handler + telegram_chat_scope  ← NEW
                                   │        (wrapper.py:749-794)
                                   ▼
                     AudioNoteCaptureToolkit.capture_audio_note()   ← NEW
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
      1. LLM structure     2. ObsidianToolkit    3. LLMWikiToolkit
         (Haiku 4.5)          .create_note()        .ingest_source()
         title/tags/EN        audio-notes/           notes wiki
         body in source       YYYY-MM-DD-slug.md     (self._notes_wiki)   ← NEW instance
         language                  │                       │
                                   │  DURABLE              │  BEST-EFFORT
                                   ▼                       ▼
                            (must succeed)          (failure → warn, note kept)
                                   │
                                   ▼
                        "✅ Saved: <title>"

Nightly (existing, one line changed):
  sync_meetings_to_wiki → ingest_obsidian_vault(meetings, vault_path/meetings_folder)
                                                          ^^^^^^^^^^^^^^^^^^^^^^^^^ was: vault_path
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FirefliesWikiAgent` (`agents/fireflies_wiki.py:165`) | extends | New `_notes_wiki` plane, `_note_mode` map, `/note` command, capture toolkit registration in `configure()` |
| `FirefliesObsidianAgent.configure()` (`agents/obsidian.py:120`) | uses | Already calls `_initialize_tools([self.obsidian_toolkit])` at `:132` — the capture toolkit is appended to the same call path |
| `ObsidianToolkit.create_note()` (`tools/obsidian.py:439`) | uses | Consumed unchanged. Agent's `allowed_operations` already contains `create` (`agents/obsidian.py:108-114`) |
| `LLMWikiToolkit.ingest_source()` (`wiki/toolkit.py:166`) | uses | Consumed unchanged, on the new notes instance |
| `LLMWikiToolkit.create_wiki()` (`wiki/toolkit.py:445`) | uses | Idempotent bootstrap of the notes plane at configure time |
| `LLMWikiToolkit.ingest_obsidian_vault()` (`wiki/toolkit.py:196`) | modifies caller | Caller narrowed to the meetings subfolder; the method itself is untouched |
| `TelegramAgentWrapper._register_agent_commands()` (`wrapper.py:742`) | modifies | Additive: wrap `agent_cmd_handler` in `telegram_chat_scope` |
| `telegram_command` (`telegram/decorators.py:5`) | uses | Declares `/note`; no wrapper change needed to declare |
| `current_telegram_chat_id` (`telegram/context.py:14`) | uses | Keys the per-chat sticky-mode map. **Value is a `str`, not an `int`** |
| `TranscriptionResult.language` (`transcriber/models.py:102`) | uses | Drives source-language body generation |
| `handle_voice()` (`wrapper.py:3409`) | **untouched** | Explicitly not modified |
| FEAT-450 `wikitoolkit ns add` | depends on | Registers the notes plane as a queryable namespace (see §7) |

### Data Models

```python
# agents/fireflies_wiki.py — new module-level models

class AudioNoteStructure(BaseModel):
    """LLM-structured form of a raw voice transcript."""
    title: str          # English, used for the slug
    tags: list[str]     # English, OKF/frontmatter tags
    summary: str        # source language
    key_points: list[str]      # source language
    action_items: list[str]    # source language, may be empty

class AudioNoteResult(BaseModel):
    """Return value of capture_audio_note."""
    note_title: str            # "YYYY-MM-DD-slug"
    vault_path: str            # "audio-notes/YYYY-MM-DD-slug.md"
    wiki_ingested: bool
    wiki_reason: Optional[str] = None   # populated when wiki_ingested is False
    structured: bool                    # False when the LLM fallback path was used
```

### New Public Interfaces

```python
# agents/fireflies_wiki.py

class AudioNoteCaptureToolkit(AbstractToolkit):
    """Single-purpose, agent-local toolkit exposing exactly one tool.

    Holds references to the agent's collaborators because a bare @tool
    function cannot close over agent state. AbstractToolkit converts each
    public async method into a tool, so this class exposes exactly one.
    """
    def __init__(
        self,
        obsidian_toolkit: ObsidianToolkit,
        notes_wiki_provider: Callable[[], Optional[Any]],
        llm_call: Callable[[str], Awaitable[AIMessage]],
        notes_folder: str = "audio-notes",
        wiki_name: str = "notes",
    ) -> None: ...

    async def capture_audio_note(
        self,
        transcript: str,
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """Save a note as a structured Obsidian note and wiki page.

        Call this when the user is recording something to REMEMBER
        (a note, idea, decision, reminder or follow-up) rather than
        asking a question.

        Transport-neutral: the text may come from a transcribed voice
        note OR from a typed message — voice is only the vehicle.
        ``language`` is the transcript's detected language for voice
        input, and ``None`` for typed input.
        """


class FirefliesWikiAgent(FirefliesObsidianAgent):   # existing, extended
    _notes_wiki: Optional[Any]              # NEW — second LLMWikiToolkit instance
    _note_mode: dict[str, bool]             # NEW — chat_id (str) → armed
    notes_wiki_name: str                    # NEW
    notes_wiki_storage_dir: Path            # NEW
    notes_folder: str                       # NEW, default "audio-notes"

    async def _build_notes_wiki_toolkit(self) -> Optional[Any]: ...   # NEW
    #   ^ the single seam where the wiki plane is constructed

    @telegram_command("note", description="Capture the next message as a note")
    async def arm_note_mode(self, _args: str = "") -> str: ...        # NEW
```

**Configuration keys** (navconfig, read through the existing `_int_env` /
`_bool_env` / `_list_env` helpers in `agents/fireflies_wiki.py:56-100`):

| Key | Default | Purpose |
|---|---|---|
| `AUDIO_NOTES_WIKI_NAME` | `"notes"` | Notes wiki identifier |
| `AUDIO_NOTES_WIKI_STORAGE_DIR` | `~/.parrot/wikis/notes` | Notes wiki storage root |
| `AUDIO_NOTES_FOLDER` | `"audio-notes"` | Vault subfolder for captures |

---

## 3. Module Breakdown

### Module 1: Telegram agent-command chat scope
- **Path**: `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py`
- **Responsibility**: Wrap the inner `agent_cmd_handler` (`wrapper.py:749-794`)
  in `telegram_chat_scope(chat_id)` so agent-declared slash commands can resolve
  the invoking chat via `get_current_telegram_chat_id()`. Purely additive; no
  existing behavior removed.
- **Depends on**: nothing in this spec. **Must land first** — Module 4 depends on it.

### Module 2: Notes wiki plane
- **Path**: `agents/fireflies_wiki.py`
- **Responsibility**: New config constants; `_build_notes_wiki_toolkit()`
  constructing a **second** `LLMWikiToolkit` with its own `WikiConfig`,
  PageIndex plane and graph plane; idempotent `create_wiki()` bootstrap; wire
  into `configure()`. Best-effort throughout — any failure leaves
  `self._notes_wiki` as `None` and the agent boots.
- **Depends on**: existing `_build_wiki_toolkit()` / `_build_pageindex_toolkit()`
  patterns (`agents/fireflies_wiki.py:243`, `:298`).

### Module 3: Note structuring + capture toolkit
- **Path**: `agents/fireflies_wiki.py`
- **Responsibility**: `AudioNoteStructure` / `AudioNoteResult` models; the
  structuring prompt and response parser (mirroring `_build_analysis_prompt` /
  `_parse_analysis_response`, `agents/obsidian.py:758`, `:805`);
  `AudioNoteCaptureToolkit` with its single `capture_audio_note` tool; OKF
  frontmatter construction; slug collision handling; the verbatim fallback path.
- **Depends on**: Module 2.

### Module 4: `/note` sticky mode
- **Path**: `agents/fireflies_wiki.py`
- **Responsibility**: `_note_mode: dict[str, bool]` keyed by chat id;
  `@telegram_command("note")` handler arming exactly one capture;
  consume-on-next-message clearing; forcing the capture path when armed.
- **Depends on**: Module 1, Module 3.

### Module 5: Vault scoping fix
- **Path**: `agents/fireflies_wiki.py`
- **Responsibility**: Narrow `_ingest_vault_into_wiki()`'s
  `ingest_obsidian_vault` call (`agents/fireflies_wiki.py:425`) from
  `str(self.vault_path)` to `str(self.vault_path / self.meetings_folder)`, so
  `audio-notes/` never reaches the meetings wiki.
- **Depends on**: nothing. Independently landable.

### Module 6: Namespace registration
- **Path**: documentation + operator runbook (no code)
- **Responsibility**: Register the notes wiki as a FEAT-450 namespace
  (`wikitoolkit ns add notes --store <AUDIO_NOTES_WIKI_STORAGE_DIR>`) so
  `wikitoolkit query` reaches audio notes and `--ns notes` targets them.
- **Depends on**: **FEAT-450 merged.** See §7 and Worktree Strategy.

### Module 7: Scheduled entity extraction on the notes plane
- **Path**: `agents/fireflies_wiki.py`
- **Responsibility**: A `@schedule`d job that runs Phase-2 LLM entity extraction
  over the notes wiki tree, so audio notes contribute CONCEPT nodes to the graph.
- **Why scheduled and not per-capture**: `ingest_source()` (`wiki/toolkit.py:166`)
  has **no** `extract_entities` parameter, and `WikiConfig` has no such field.
  Extraction is `WikiIngestOrchestrator.extract_entities(tree_name, wiki_config,
  granularity, custom_instructions)` (`wiki/ingest.py:439`), reached inside
  `LLMWikiToolkit` only via `ingest_obsidian_vault` (`wiki/toolkit.py:298`).
  It **iterates the whole PageIndex tree**, not the newly added page — so calling
  it per capture would cost O(n) LLM calls per note and would violate the
  acceptance criterion "exactly one LLM call per note". A scheduled sweep
  delivers the graph value without putting it in the latency-critical path.
- **Depends on**: Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_agent_command_enters_chat_scope` | 1 | An agent command handler sees `get_current_telegram_chat_id()` equal to the invoking chat id |
| `test_agent_command_scope_resets` | 1 | The contextvar is reset after the handler returns, including on exception |
| `test_existing_agent_commands_unaffected` | 1 | Commands that ignore chat scope behave identically |
| `test_build_notes_wiki_separate_instance` | 2 | `_notes_wiki` is a distinct object from `_wiki` with a different `wiki_name` and `storage_dir` |
| `test_build_notes_wiki_failure_returns_none` | 2 | Construction failure leaves `_notes_wiki is None` and does not raise from `configure()` |
| `test_create_wiki_called_idempotently` | 2 | A second `configure()` does not error on an existing notes plane |
| `test_structure_transcript_parses_llm_response` | 3 | Valid LLM output → populated `AudioNoteStructure` |
| `test_structure_fallback_on_llm_error` | 3 | LLM failure → verbatim note, `structured=False`, no exception |
| `test_note_written_to_audio_notes_folder` | 3 | Path is `audio-notes/YYYY-MM-DD-<slug>.md` |
| `test_transcript_preserved_verbatim` | 3 | The `## Transcript` section contains the raw transcript unmodified |
| `test_title_and_tags_english_body_source_language` | 3 | Spanish transcript → Spanish body, English title/tags |
| `test_slug_collision_appends_suffix` | 3 | `create_note` raising `FileExistsError` → retry as `-2`, then `-3` |
| `test_wiki_failure_keeps_note` | 3 | `ingest_source` raising → `wiki_ingested=False`, note still on disk, no exception |
| `test_vault_write_failure_propagates` | 3 | A vault write failure is surfaced, not silently swallowed |
| `test_note_mode_arms_single_capture` | 4 | `/note` arms; the next message captures; the mode then clears |
| `test_note_mode_scoped_per_chat` | 4 | Arming chat A does not arm chat B |
| `test_note_mode_unarmed_answers_normally` | 4 | Without `/note` and without intent, the message is answered, not saved |
| `test_nightly_ingest_scoped_to_meetings_folder` | 5 | `ingest_obsidian_vault` receives `<vault>/meetings`, not `<vault>` |

### Integration Tests

| Test | Description |
|---|---|
| `test_capture_end_to_end` | Transcript → structured note on disk → page present in the notes wiki, queryable |
| `test_capture_no_duplicate_after_incremental` | Capture a note, then run an incremental vault ingest; **exactly one** page exists for it (validates `ingest_source` over `create_page`) |
| `test_audio_notes_absent_from_meetings_wiki` | After a capture and a nightly `sync_meetings_to_wiki`, the meetings wiki contains no audio-note page |
| `test_voice_note_question_still_answered` | A question sent by voice is answered normally; no note is created |
| `test_existing_telegram_voice_suite_passes` | `test_telegram_voice.py` and `test_telegram_voice_integration.py` pass unmodified |

### Test Data / Fixtures

```python
@pytest.fixture
def tmp_vault(tmp_path):
    """Minimal Obsidian vault with meetings/ and audio-notes/ subfolders."""
    ...

@pytest.fixture
def spanish_transcript():
    return ("nota para mí: deberíamos mover el presupuesto de reintentos "
            "a la configuración del scheduler")

@pytest.fixture
def fake_notes_wiki(mocker):
    """LLMWikiToolkit double recording ingest_source calls."""
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

**Capture behavior**
- [ ] A voice note expressing capture intent produces a note at
      `audio-notes/YYYY-MM-DD-<slug>.md` and a single-line
      `✅ Saved: <title>` reply — no draft, no approval buttons (G1, G3)
- [ ] The note contains the verbatim transcript under a `## Transcript`
      heading (G1)
- [ ] The note body is in the transcript's source language; the title, tags
      and OKF frontmatter are in English (G1)
- [ ] `/note` arms exactly one capture; the next message is captured and the
      mode clears without a further command (G3)
- [ ] `/note` state is per-chat: arming one chat does not arm another (G3)
- [ ] A voice note that is a question is still answered normally and creates
      no note (G7)

**Wiki behavior**
- [ ] A captured note is retrievable via the notes wiki immediately after
      capture, without waiting for the nightly job (G2)
- [ ] `self._notes_wiki` is a **separate `LLMWikiToolkit` instance** from
      `self._wiki`, with its own `wiki_name` and `storage_dir` (G2)
- [ ] After a capture followed by an incremental vault ingest, **exactly one**
      wiki page exists for that note — no duplicate (G2)
- [ ] After a capture and a full `sync_meetings_to_wiki` run, the **meetings**
      wiki contains no audio-note page (G6)
- [ ] `_ingest_vault_into_wiki()` passes `<vault>/<meetings_folder>` to
      `ingest_obsidian_vault`, not `<vault>` (G6)

**Resilience**
- [ ] With the notes wiki unavailable (`_notes_wiki is None`), capture still
      writes the Obsidian note and reports `wiki_ingested=False` (G5)
- [ ] With `ingest_source` raising, the note remains on disk and no exception
      reaches the user (G5)
- [ ] With the LLM structuring call failing, a verbatim note is written with
      `structured=False` (G5)
- [ ] A vault write failure IS surfaced to the user and does not report
      success (G5)
- [ ] Notes-plane construction failure leaves the agent bootable, matching the
      existing `_build_wiki_toolkit()` posture (G5)

**Non-regression**
- [ ] `handle_voice()` is unmodified (G7)
- [ ] Existing Telegram voice tests pass unmodified: `pytest
      packages/ai-parrot-integrations/tests/integrations/telegram/test_telegram_voice.py
      packages/ai-parrot-integrations/tests/integrations/telegram/test_telegram_voice_integration.py -v` (G7)
- [ ] Agent commands that do not use chat scope behave identically after the
      Module 1 change (G7)
- [ ] No breaking changes to any existing public API (G7)

**Constraints**
- [ ] **No new external dependency** is added to any `pyproject.toml` (G4)
- [ ] The capture path performs **exactly one** LLM call per note, on the
      agent's configured client via `AbstractClient` — never the Anthropic SDK
      directly (G4)
- [ ] No blocking I/O in the async capture path (G4)
- [ ] `agents/fireflies_wiki.py` is committed with `git add -f` (it is
      gitignored — see the file's own module docstring)
- [ ] FEAT-450 is merged before this feature's branch is merged (see §7)
- [ ] Notes wiki registered as a namespace and reachable via
      `wikitoolkit query --ns notes` (G2, Module 6)
- [ ] Entity extraction over the notes plane runs on a **schedule**, never in
      the capture path — the capture path's one-LLM-call budget is unchanged
      (Module 7)
- [ ] `capture_audio_note` is reachable from typed text messages as well as
      voice transcripts; its `language` argument is optional and `None` for
      typed input (Module 3, Module 4)

**Process**
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] `ruff check` clean on changed files
- [ ] Documentation updated: new config keys and the `/note` command

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Every reference below was read from source and its line numbers re-verified
> on 2026-08-23 against `dev` @ `af08f4c81`. Implementation agents MUST NOT
> reference imports, attributes, or methods not listed here without first
> verifying they exist.

### Verified Imports

```python
# All confirmed to resolve:
from parrot.agents.obsidian import FirefliesObsidianAgent      # agents/fireflies_wiki.py:38
from parrot.registry import register_agent                      # agents/fireflies_wiki.py:39
from parrot.scheduler import ScheduleType, schedule             # agents/fireflies_wiki.py:40
from parrot.tools import tool, AbstractTool, AbstractToolkit    # parrot/tools/__init__.py:142-144
from parrot.tools.obsidian import ObsidianToolkit               # parrot/tools/obsidian.py:78
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit        # agents/fireflies_wiki.py:259
from parrot.knowledge.wiki.models import WikiConfig             # agents/fireflies_wiki.py:258
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit  # agents/fireflies_wiki.py:255
from parrot.clients.factory import LLMFactory                   # agents/fireflies_wiki.py:314
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter      # agents/fireflies_wiki.py:315
from parrot.knowledge.pageindex.toolkit import PageIndexToolkit            # agents/fireflies_wiki.py:316
from navconfig import config                                    # agents/fireflies_wiki.py:36

from parrot.integrations.telegram.decorators import telegram_command, discover_telegram_commands
#   ^ telegram/decorators.py:5 and :35
from parrot.integrations.telegram.context import (
    telegram_chat_scope, get_current_telegram_chat_id, current_telegram_chat_id
)   # ^ telegram/context.py:19, :30, :14
```

### Existing Class Signatures

```python
# agents/fireflies_wiki.py
@register_agent(name="fireflies_wiki", at_startup=True)          # line 164
class FirefliesWikiAgent(FirefliesObsidianAgent):                # line 165
    wiki_name: str                                                # line 208
    wiki_storage_dir: Path                                        # line 209
    daily_recipients: List[str]                                   # line 212
    weekly_recipients: List[str]                                  # line 217
    _wiki: Optional[Any]                                          # line 224 — None when unavailable

    async def configure(self, app=None) -> None: ...              # line 230
    async def _build_wiki_toolkit(self) -> Optional[Any]: ...     # line 243
    def _build_pageindex_toolkit(self, storage: Path) -> Optional[Any]: ...  # line 298
    async def sync_meetings_to_wiki(self, limit=None, analysis_limit=None) -> Dict[str, Any]: ...  # line 343
    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]: ...            # line 411
    #   ^ line 425: await self._wiki.ingest_obsidian_vault(
    #                   self.wiki_name, str(self.vault_path),
    #                   incremental=True, extract_entities=_EXTRACT_ENTITIES)
    #     *** str(self.vault_path) is the whole vault — Module 5 narrows this ***

# Module-level constants — agents/fireflies_wiki.py
_DEFAULT_LLM: str = "anthropic:claude-haiku-4-5"                  # line 146
_LLM: str                                                          # line 147
_WIKI_NAME: str = config.get("FIREFLIES_WIKI_NAME", fallback="meetings")   # line 150
_WIKI_STORAGE_DIR: str                                             # line 151 (~/.parrot/wikis/meetings)
_EXTRACT_ENTITIES: bool                                            # line 155
def _int_env(key: str, default: int) -> int: ...                   # line 56
def _bool_env(key: str, default: bool = False) -> bool: ...        # line 76
def _list_env(key: str) -> List[str]: ...                          # line 91

# packages/ai-parrot/src/parrot/agents/obsidian.py
class FirefliesObsidianAgent(BasicAgent):                          # line 48
    ANALYSIS_HEADING: str = "## Analysis"                          # line 74
    vault_path: Path                                               # lines 96-100 (env OBSIDIAN_VAULT_PATH, default ~/vaults/notes)
    fireflies_token: Optional[str]                                 # line 101
    meetings_folder: str                                           # line 102 (default "meetings")
    obsidian_toolkit: ObsidianToolkit                              # line 105
    #   ^ allowed_operations={"read","list","search","create","update"}  lines 108-114

    async def configure(self, app=None) -> None: ...               # line 120
    #   ^ line 132: self._initialize_tools([self.obsidian_toolkit])
    async def summarize_transcript(...) -> ...: ...                # line 305
    async def summarize_pending_transcripts(...) -> ...: ...       # line 392
    @staticmethod
    def _build_okf_frontmatter(fireflies_id: str, title: str, date: str,
                               participants: List[str], duration: float) -> Dict[str, Any]: ...  # line 520
    @staticmethod
    def _make_note_title(date: str, meeting_title: str) -> str: ...            # line 728
    #   ^ returns "YYYY-MM-DD-kebab-case-title"
    @staticmethod
    def _build_analysis_prompt(transcript_text: str, granularity: str = "standard") -> str: ...  # line 758
    @staticmethod
    def _parse_analysis_response(llm_response: AIMessage) -> Dict[str, Any]: ...  # line 805

# packages/ai-parrot/src/parrot/tools/obsidian.py
class ObsidianToolkit(AbstractToolkit):                            # line 78
    def __init__(self, vault_path: Optional[str | Path] = None,
                 backend: Literal["local", "rest"] = "local",
                 vault: Optional[ObsidianVaultInterface] = None,
                 allowed_operations: Optional[Set[str]] = None,
                 **backend_kwargs: Any) -> None: ...               # line 127
    async def create_note(self, path: str, content: str,
                          frontmatter: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...  # line 439
    #   ^ line 461: `import yaml` (frontmatter rendering)
    #   ^ writes with overwrite=False → raises FileExistsError when the note exists
    async def update_note(self, path: str, content: str,
                          preserve_frontmatter: bool = True) -> Dict[str, Any]: ...  # line 471
    async def append_note(self, path: str, content: str) -> Dict[str, Any]: ...      # line 504
    async def classify_note(self, path: str) -> Dict[str, Any]: ...                  # line 631
    async def apply_okf_frontmatter(...) -> ...: ...                                 # line 702

# packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py
class LLMWikiToolkit(AbstractToolkit):                             # line 46
    def __init__(self, pageindex_toolkit, graph_toolkit, <third>, config: WikiConfig,
                 agent_id: str = ...) -> None: ...                 # line 75
    async def ingest_source(self, wiki_name: str, source_path: str,
                            source_type: Optional[str] = None) -> dict[str, Any]: ...  # line 166
    #   ^ returns: source_id, pages_created, graph_nodes_created, duration_ms, status
    async def ingest_obsidian_vault(self, wiki_name: str, vault_path: str,
                                    incremental: bool = False,
                                    extract_entities: bool = False,
                                    granularity: str = "standard") -> dict[str, Any]: ...  # line 196
    #   *** NO folder-filter parameter — verified. vault_path is a directory path. ***
    async def create_wiki(self, wiki_name: str,
                          description: Optional[str] = None) -> dict[str, Any]: ...    # line 445
    #   ^ idempotent: dirs guarded by `if not d.exists()` (lines 475-477);
    #     write_index / log_operation safe to repeat (lines 481-489)
    async def create_page(self, wiki_name: str, title: str, content: str,
                          category: str = "concept",
                          related_pages: Optional[list[str]] = None) -> dict[str, Any]: ...  # line 643
    async def reingest_source(self, ...) -> ...: ...               # line 963
    async def query(self, ...) -> ...: ...                         # line 304
    def _config_for(self, wiki_name: str) -> WikiConfig: ...       # line 1205
    #   *** RAISES ValueError when wiki_name != self._config.wiki_name (lines 1222-1226).
    #       Docstring: "Construct a separate LLMWikiToolkit for each wiki instance."
    #       This is why a `notes` wiki needs a SECOND toolkit instance. ***

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    async def handle_voice(self, message: Message) -> None: ...    # line 3409
    #   registered lines 305-317 for ContentType.VOICE and ContentType.AUDIO, private chats only
    #   line 3546: result = await transcriber.transcribe_file(tmp_path, language=voice_config.language)
    #   line 3590: `with telegram_chat_scope(chat_id):` around _invoke_agent(...)
    def _register_agent_commands(self) -> None: ...                # line 742
    #   inner `async def agent_cmd_handler(message, ...)` at line 749; registered line 794
    #   *** does NOT enter telegram_chat_scope — the gap Module 1 fixes ***
    #   *** receives only `message`; parses raw_args from message.text ***

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py
def telegram_command(command: str, description: str = "",
                     parse_mode: str = "keyword") -> Callable: ...  # line 5
#   parse_mode ∈ {"keyword", "positional", "raw"}   # lines 19-21
#   sets fn._telegram_command = {command, description, parse_mode}   # line 25
def discover_telegram_commands(agent: Any) -> List[Dict[str, Any]]: ...  # line 35
#   skips attrs starting with "_"  # line 49

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py
current_telegram_chat_id: ContextVar[Optional[str]]                 # line 14 — default None
@contextmanager
def telegram_chat_scope(chat_id: int | str | None) -> Iterator[None]: ...  # line 19
#   *** stores str(chat_id) — the contextvar value is a STRING, not an int (line 21) ***
def get_current_telegram_chat_id() -> Optional[str]: ...            # line 30

# packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py
class TranscriptionResult(BaseModel):                               # line 90
    text: str                          # line 98
    language: str                      # line 102 — ISO 639-1
    duration_seconds: float            # line 106
    confidence: Optional[float]        # line 111
    processing_time_ms: int            # line 117

# packages/ai-parrot/src/parrot/interfaces/tools.py
def _initialize_tools(self, tools: List[Union[str, AbstractTool, ToolDefinition]]) -> None: ...  # line 26
#   accepts: str (toolkit or tool name) | AbstractToolkit class or instance |
#            AbstractTool | ToolDefinition

# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                         # line 216
#   "A toolkit automatically converts all public async methods into tools" (line 220)
    def get_tools(self, ...) -> ...: ...                            # line 484
    def _generate_tools(self) -> None: ...                          # line 537

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool(_func=None, *, name=None, description=None, schema=None,
         auto_register=False, requires_confirmation=False,
         confirm_template=None, confirm_window_seconds=0,
         allow_edit=False): ...                                     # line 55
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AudioNoteCaptureToolkit` | `ObsidianToolkit.create_note()` | method call | `parrot/tools/obsidian.py:439` |
| `AudioNoteCaptureToolkit` | `LLMWikiToolkit.ingest_source()` | method call | `parrot/knowledge/wiki/toolkit.py:166` |
| `AudioNoteCaptureToolkit` | agent LLM client | `AbstractClient` via the agent's configured client | `agents/fireflies_wiki.py:146` |
| `FirefliesWikiAgent.configure()` | `_initialize_tools([...])` | registration | `parrot/interfaces/tools.py:26`, called at `agents/obsidian.py:132` |
| `_build_notes_wiki_toolkit()` | `LLMWikiToolkit.__init__` + `create_wiki()` | construction + idempotent bootstrap | `wiki/toolkit.py:75`, `:445` |
| `arm_note_mode()` | `@telegram_command("note")` | decorator | `telegram/decorators.py:5` |
| `arm_note_mode()` | `get_current_telegram_chat_id()` | contextvar read (**requires Module 1**) | `telegram/context.py:30` |
| Module 1 | `telegram_chat_scope` | context manager around `agent_cmd_handler` | `telegram/context.py:19`, `wrapper.py:749-794` |
| Module 5 | `ingest_obsidian_vault(...)` | narrowed `vault_path` argument | `agents/fireflies_wiki.py:425` |
| Module 6 | `wikitoolkit ns add` | CLI (FEAT-450) | `wiki-namespaces.spec.md:266` *(unverified — FEAT-450 not merged)* |

### Does NOT Exist (Anti-Hallucination)

Verified absent by `grep -rn` over `packages/*/src` and `agents/` — zero hits:

- ~~`capture_audio_note`~~, ~~`AudioNoteToolkit`~~, ~~`AudioNoteCaptureToolkit`~~,
  ~~`AudioNoteAgent`~~, ~~`parrot.tools.audio_notes`~~ — none exist yet; all are
  created by this feature
- ~~`FirefliesWikiAgent.capture_note()`~~ / ~~`.save_voice_note()`~~ — not real methods
- ~~`FirefliesWikiAgent._notes_wiki`~~ / ~~`._note_mode`~~ — do not exist yet (created here)
- ~~`ObsidianToolkit.create_audio_note()`~~ — not a real method; use `create_note()`
- ~~`LLMWikiToolkit.ingest_text()`~~ / ~~`ingest_markdown()`~~ — **do not exist.**
  Ingestion is **path-based**: `ingest_source(wiki_name, source_path, source_type=None)`.
  There is no string-content ingest entry point.
- ~~`ingest_obsidian_vault(..., folder=...)`~~ / ~~`subfolder=`~~ / ~~`include=`~~ /
  ~~`exclude=`~~ — **no folder-filter parameter exists.** Verified signature is
  `(wiki_name, vault_path, incremental, extract_entities, granularity)`.
  Scoping is achieved by passing a subdirectory as `vault_path`.
- ~~One `LLMWikiToolkit` serving multiple wikis~~ — **false.** `_config_for()`
  (`toolkit.py:1205`) raises `ValueError` on a `wiki_name` mismatch. Passing
  `"notes"` to the meetings toolkit will raise, not route.
- ~~`TelegramAgentWrapper.handle_note()`~~ / ~~`note_mode`~~ /
  ~~`VoiceConfig.note_mode`~~ — no note-mode concept exists in the Telegram
  integration
- ~~`agent_cmd_handler` receives `chat_id`~~ — it does **not**. It receives only
  `message` and parses `raw_args` from the text, and never enters
  `telegram_chat_scope`. Any design assuming an agent command can already
  resolve its chat is wrong — that is exactly what Module 1 adds.
- ~~`current_telegram_chat_id` holds an `int`~~ — **it holds a `str`**
  (`context.py:22` calls `str(chat_id)`). Keying a dict by `int` will silently miss.
- ~~`TranscriptionResult.markdown`~~ / ~~`.segments`~~ / ~~`.speaker`~~ /
  ~~`.words`~~ — not fields. The model has exactly `text`, `language`,
  `duration_seconds`, `confidence`, `processing_time_ms`.
- ~~`parrot/tools/` holds no concrete toolkits~~ — mostly true (core keeps base
  machinery; concrete toolkits ship from `parrot_tools`), but **`obsidian.py` is
  a genuine exception living in core** at
  `packages/ai-parrot/src/parrot/tools/obsidian.py:78` — verified.
- ~~`agents/fireflies_wiki.py` is git-tracked~~ — **it is gitignored.** Commit
  with `git add -f`.
- **FEAT-450 symbols are NOT yet in the codebase**: ~~`FederatedWikiStore`~~,
  ~~`WikiNamespaceConfig`~~, ~~`GlobalWikiRegistry`~~,
  ~~`WikiProjectConfig.namespaces`~~, ~~`federation.py`~~, ~~`wikitoolkit ns add`~~
  — all specified in `sdd/specs/wiki-namespaces.spec.md` but unmerged.
  *(unverified — check before use)*

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Best-effort wiki construction.** Mirror `_build_wiki_toolkit()`
  (`agents/fireflies_wiki.py:243`) exactly: wrap construction in
  `try/except Exception`, log a warning, return `None`. The agent must always boot.
- **Prompt/parse symmetry.** Model the structuring prompt and parser on
  `_build_analysis_prompt` / `_parse_analysis_response` (`agents/obsidian.py:758`,
  `:805`) rather than inventing a second convention.
- **Note-title convention.** Reuse `_make_note_title()` (`agents/obsidian.py:728`)
  — `YYYY-MM-DD-kebab-case-title` — verbatim.
- **Config helpers.** Use the existing `_int_env` / `_bool_env` / `_list_env`
  module-level helpers (`agents/fireflies_wiki.py:56`, `:76`, `:91`).
- Async-first throughout; no blocking I/O in the capture path.
- Pydantic models for all structured data.
- `self.logger`, never `print`.
- Google-style docstrings and strict type hints on every new function and class.

### Known Risks / Gotchas

| Risk | Mitigation |
|---|---|
| **LLM intent detection is probabilistic** — it will occasionally answer a note or save a question | Accepted trade for a natural interface. `/note` is the deterministic override. The user sees the outcome immediately (a `✅ Saved` line or an answer) and can correct course. |
| **`_config_for` raises on wiki-name mismatch** (`toolkit.py:1205`) | A second `LLMWikiToolkit` instance is mandatory, not optional. Never pass `"notes"` to `self._wiki`. |
| **Vault bleed into the meetings wiki** | Module 5 narrows the nightly ingest to `<vault>/<meetings_folder>`. Note this changes what the meetings wiki contains — it has been absorbing every unrelated vault note until now. Existing meetings-wiki pages for non-meeting notes are not retroactively pruned by this feature. |
| **Duplicate pages** if `create_page` were used instead of `ingest_source` | `ingest_source` is mandated; an integration test asserts exactly one page survives an incremental pass. |
| **`current_telegram_chat_id` is a `str`** (`context.py:22`) | Key `_note_mode` by `str`. An `int` key silently never matches. |
| **Forgotten sticky mode swallowing a later question** | Consume-on-next-message clearing makes this structurally impossible beyond one message. |
| **Same-day slug collision** | `create_note` raises `FileExistsError` by design (`overwrite=False`) — that is the retry signal, not an error to surface. Append `-2`, `-3`. |
| **Empty / unintelligible transcript** | Already handled upstream: `handle_voice` answers "couldn't understand" and returns before the agent is invoked (`wrapper.py:3560-3565`). No new handling needed. |
| **Very long transcript** | Bounded upstream by `max_audio_duration_seconds` pre-check in `handle_voice`. No new limit. |
| **Concurrent captures in one chat** | Vault writes are per-file with `overwrite=False`; the collision-suffix path covers the race. |
| **`agents/fireflies_wiki.py` is gitignored** | Every commit touching it needs `git add -f`. An `sdd-worker` that forgets this will appear to have made no changes. |
| **One extra tool in every prompt** | Marginal token cost, accepted. |

### FEAT-450 dependency — precise scope

FEAT-450 is declared a **hard prerequisite**: this feature's branch does not
merge until `wiki-namespaces` is merged.

What the dependency actually buys, stated precisely so nobody over- or
under-reads it:

- **It does NOT change how the notes wiki is written.** FEAT-450 operates on the
  `BaseWikiStore` / `wikitoolkit` CLI retrieval plane. Its own spec lists
  `toolkit.py:LLMWikiToolkit` as *"optional | may accept an injected federated
  store; **not required for AC**"* (`wiki-namespaces.spec.md:153`). Modules 1–5
  are technically independent of it and could be built and tested today.
- **It IS what makes audio notes discoverable.** Without namespaces,
  `wikitoolkit query` reads exactly one plane, so a separate `notes` wiki would
  be written but unreachable from the CLI and MCP tools — defeating G2's
  "queryable in seconds". FEAT-450's `store` namespace kind
  (`WikiNamespaceConfig.store`, `wiki-namespaces.spec.md:162`) is what registers
  it, and `--ns notes` / `--ns all` is what reaches it.

Consequence for sequencing: Module 6 is hard-blocked. Modules 1–5 are not
technically blocked but are held behind the same merge gate per the declared
dependency. If the gate is later relaxed, Modules 1–5 can ship first and Module
6 follows FEAT-450 — the code seam (`_build_notes_wiki_toolkit()`) is designed
so that migration touches one method.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | **No new external dependencies.** |
| `aiogram` | existing | Telegram transport; only the existing `Command()` registration path is touched |
| `PyYAML` | existing | Frontmatter; already imported inside `ObsidianToolkit.create_note()` (`tools/obsidian.py:461`) |
| `pydantic` | existing | Tool input/output models; project-wide standard |

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`
- **Rationale**: Modules 2–5 all edit the single file `agents/fireflies_wiki.py`.
  Splitting them across worktrees would produce guaranteed conflicts for no
  parallelism gain. One feature worktree, tasks executed sequentially.
- **Task ordering** (dependency-driven):
  1. **Module 1** (wrapper chat scope) — must land first; Module 4 depends on it.
     Lives in a different package, so it is the one piece that *could* be split
     into its own worktree if desired.
  2. **Module 5** (vault scoping fix) — independent, small, landable any time.
  3. **Module 2** (notes wiki plane) → **Module 3** (capture toolkit) →
     **Module 4** (`/note`) — strictly sequential, same file.
  4. **Module 6** (namespace registration) — last, gated on FEAT-450.
- **Cross-feature dependencies**:
  - **FEAT-450 `wiki-namespaces` — MUST BE MERGED FIRST** (declared hard
    dependency; see §7 for precise scope). Status: `approved`, 10 tasks, not merged.
  - **FEAT-451 `wikitoolkit-ingest-documents`** — no blocking relationship. It
    changes the content-acquisition layer *inside* `ingest_source` without
    changing its signature, so this feature consumes it either way. No shared
    source files.
  - `agents/fireflies_wiki.py` is touched by no other in-flight spec.

```bash
# After task decomposition and once FEAT-450 has merged:
git checkout dev && git pull origin dev
git worktree add -b feat-452-audio-notes-obsidian \
  .claude/worktrees/feat-452-audio-notes-obsidian HEAD
```

---

## 8. Open Questions

**Resolved in brainstorm** (carried forward — do NOT re-open):

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Where should capture logic live — *Resolved in brainstorm*: an LLM-callable tool on the agent (Option A); no changes to `handle_voice`. → §2 Overview, §3 Module 3
- [x] Note shape — *Resolved in brainstorm*: LLM-structured (title, summary, key points, action items, tags, OKF frontmatter) with the verbatim transcript preserved in a `## Transcript` section. → §2 Overview, §5 AC
- [x] Wiki write timing — *Resolved in brainstorm*: immediate direct write at capture time, not deferred to the nightly job. → G2, §5 AC
- [x] Save-vs-answer trigger — *Resolved in brainstorm*: LLM intent detection, with `/note` as a deterministic override. → G3, §3 Module 4
- [x] Vault layout — *Resolved in brainstorm*: `audio-notes/YYYY-MM-DD-<slug>.md`, one note per capture, sequence suffix on same-day collision. → G1, §5 AC
- [x] Wiki target — *Resolved in brainstorm*: a separate `notes` wiki with its own name and storage dir, not the `meetings` wiki. → G2, §2 "Two separate wiki toolkit instances"
- [x] Telegram feedback — *Resolved in brainstorm*: silent confirmation only (`✅ Saved: <title>`); no HITL approval, no inline edit buttons. → §5 AC
- [x] `/note` semantics — *Resolved in brainstorm*: sticky per-chat mode, plus the upstream `telegram_chat_scope` fix to `agent_cmd_handler`. → §3 Modules 1 and 4
- [x] Original audio retention — *Resolved in brainstorm*: discard; `handle_voice`'s existing `finally` block deletes the temp file. → §1 Non-Goals
- [x] Language — *Resolved in brainstorm*: body in the transcript's source language; title, tags and OKF frontmatter in English. → §2 Data Models, §5 AC
- [x] Tenancy — *Resolved in brainstorm*: single user, one vault. → §1 Non-Goals

**Resolved during this spec**:

- [x] Vault bleed into the meetings wiki — *Resolved by user, 2026-08-23*: narrow
  the nightly ingest to `vault_path / meetings_folder`. → G6, §3 Module 5
- [x] Sticky-mode reset policy — *Resolved by user, 2026-08-23*:
  consume-on-next-message. → §3 Module 4, §5 AC
- [x] FEAT-450 sequencing — *Resolved by user, 2026-08-23*: hard dependency;
  FEAT-450 merges first. → §7, Worktree Strategy
- [x] Does the notes wiki need `create_wiki()` bootstrapping? — *Resolved by code
  inspection, 2026-08-23*: yes, call it at configure time; it is idempotent
  (`toolkit.py:475-489`). → §2 "Wiki bootstrapping", §3 Module 2
- [x] Confirm `ingest_source` over `create_page` — *Resolved by design analysis*:
  `ingest_source` is mandated because `create_page` leaves no source-manifest
  entry and would yield a duplicate page on the next incremental pass. An
  integration test verifies this empirically rather than trusting the analysis.
  → §2 "Wiki write mechanism", §4 `test_capture_no_duplicate_after_incremental`

**Still open**:

- [x] Should the meetings wiki be **retroactively pruned** of non-meeting vault
  notes it has absorbed while the nightly ingest was unscoped? Module 5 stops
  the bleed going forward but does not clean up history. Cheapest options: leave
  as-is, or a one-off `wikitoolkit` prune. Not blocking implementation.
  — *Owner: Jesus Lara*: leave as-is
- [x] Should `capture_audio_note` also be reachable from **text** messages
  (not just voice), e.g. "note to self: …" typed rather than spoken? The tool
  itself is transport-agnostic and would work; the question is whether intent
  detection on typed text produces too many false saves. Decidable during
  implementation. — *Owner: Jesus Lara*: I think yes, a note written is equal than voice, used to save notes into wiki/obsidian, voice is only the vehicle.
- [x] Does the notes wiki warrant `extract_entities=True` (Phase-2 LLM entity
  extraction) at ingest? The meetings plane defaults it off
  (`_EXTRACT_ENTITIES`, `agents/fireflies_wiki.py:155`). Personal notes are
  short, so cost is low and graph value may be high. Deferrable.
  — *Owner: Jesus Lara*: yes.
  **Implementation constraint discovered during decomposition**: `ingest_source`
  has no `extract_entities` parameter and extraction iterates the whole tree
  (`wiki/ingest.py:439`), so it CANNOT run per capture without violating the
  "exactly one LLM call per note" criterion. Realized as scheduled Module 7.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-23 | Jesus Lara (Claude session) | Initial draft from `audio-notes-obsidian.brainstorm.md` (Option A) |
| 0.2 | 2026-08-23 | Jesus Lara (Claude session) | Approved. Open questions resolved: no retroactive prune; capture reachable from typed text; entity extraction enabled — realized as scheduled Module 7 (cannot run per capture, see §3 Module 7) |
