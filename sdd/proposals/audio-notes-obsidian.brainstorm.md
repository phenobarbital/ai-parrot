---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: Audio Notes → Obsidian + LLM Wiki

**Date**: 2026-08-23
**Author**: Jesus Lara (session: Claude Opus 5)
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

`FirefliesWikiAgent` (`agents/fireflies_wiki.py:165`) already owns a complete
**meeting** knowledge pipeline: Fireflies → Obsidian vault → per-meeting LLM
analysis → GraphIndex LLM Wiki, plus daily/weekly email digests. That pipeline
is *scheduled and batch-oriented* — it only ever ingests what Fireflies
recorded.

But a large share of durable knowledge never happens in a recorded meeting. It
happens **in the moment**: walking, driving, between calls — a decision, an
idea, a follow-up, a piece of context that will be gone in ten minutes.

Meanwhile the Telegram integration *already* transcribes voice notes end to
end. `TelegramAgentWrapper.handle_voice()`
(`packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3409`)
downloads the OGG, transcribes it via `VoiceTranscriber.transcribe_file()`, and
feeds the resulting text into `_invoke_agent()` as an ordinary message.

**The gap is small and specific**: that transcript is treated as a *question*
and answered, then discarded. There is no path that turns a spoken thought into
a structured Obsidian note **and** a queryable wiki page. The transport,
transcription, vault plane and wiki plane all already exist and are wired to the
same agent — nothing connects them.

**Who is affected**: the single operator of `FirefliesWikiAgent` (the vault
owner). Success is measurable and blunt: speak a thought into Telegram, and
seconds later `wikitoolkit query` can find it.

## Constraints & Requirements

- **Reuse, don't rebuild.** Transcription (`VoiceTranscriber`), vault writes
  (`ObsidianToolkit`), and wiki ingest (`LLMWikiToolkit`) all exist and are
  already wired into this agent. New code should be the *connective tissue*,
  not a parallel stack.
- **`agents/fireflies_wiki.py` is gitignored** — it must be committed with
  `git add -f` (the file's own module docstring says so, same as
  `agents/security_advisor.py`).
- **Async-first, no blocking I/O** — the capture path runs inside the aiogram
  event loop while the user waits.
- **Capture must never lose the thought.** A wiki-plane failure must NOT lose
  the Obsidian note. The existing agent already treats the wiki as strictly
  best-effort (`_build_wiki_toolkit` returns `None` on any failure and the
  agent still boots) — the capture path must inherit that posture.
- **No wrapper regressions.** The only upstream change is additive: wrapping
  agent-command handlers in `telegram_chat_scope` (see Option A). Voice
  handling itself is untouched.
- **Single user, one vault.** No multi-tenancy, no per-chat vault routing.
- **LLM cost stays bounded** — one structuring call per captured note, on the
  agent's already-pinned Claude Haiku 4.5 (`_DEFAULT_LLM`), through
  `AbstractClient`, never the Anthropic SDK directly.
- **Notes must not pollute meeting retrieval** — audio notes target their own
  wiki plane (see the "vault bleed" constraint in Open Questions).

---

## Options Explored

### Option A: `capture_audio_note` LLM tool on the agent + `/note` sticky mode

The transcript reaches the agent as a normal message — exactly as it does
today, with **zero changes to `handle_voice`**. The agent gains one new
LLM-callable tool, `capture_audio_note`, which performs the whole capture as a
single cohesive action:

1. Structure the raw transcript with one LLM call (title, summary, key points,
   action items, tags), preserving the verbatim transcript in a
   `## Transcript` section — mirroring the parent class's existing
   `## Analysis` convention (`ANALYSIS_HEADING`, `obsidian.py:74`).
2. Write it to `audio-notes/YYYY-MM-DD-<slug>.md` via `ObsidianToolkit.create_note()`
   with OKF frontmatter.
3. Immediately ingest that single file into the **notes** wiki via
   `LLMWikiToolkit.ingest_source()`.
4. Return a one-line confirmation the agent echoes back to Telegram.

Two ways to trigger it:

- **LLM intent** — the model reads phrasing like "note to self…",
  "remember that…", "idea:…" and calls the tool instead of answering.
- **`/note` sticky mode** — a deterministic escape hatch when intent detection
  misfires. `@telegram_command("note")`
  (`packages/ai-parrot-integrations/src/parrot/integrations/telegram/decorators.py:5`)
  already exists and needs **no wrapper change to declare**. It does, however,
  need one small upstream fix: `_register_agent_commands`'s inner
  `agent_cmd_handler` (`wrapper.py:749-794`) never enters
  `telegram_chat_scope`, so an agent command cannot currently tell which chat
  invoked it. Wrapping that handler is a ~3-line additive change that benefits
  **every** agent command, not just this feature.

✅ **Pros:**
- Smallest possible new surface: one tool + one sticky-mode flag + a 3-line
  wrapper fix. Everything else already exists and is already wired.
- Channel-agnostic by construction — MS Teams
  (`msteams/wrapper.py:788 _handle_voice_attachment`) and the voice WebSocket
  both feed transcripts through the same agent loop, so they get capture for
  free without knowing this feature exists.
- Natural interaction: you just talk. No mode to remember in the common case.
- The `/note` fix is a genuine upstream improvement with independent value.
- Failure is graceful and layered: wiki down → note still in Obsidian;
  LLM structuring fails → fall back to verbatim note.

❌ **Cons:**
- LLM intent detection is probabilistic. It will occasionally answer a note or
  save a question. `/note` mitigates but does not eliminate this.
- Adds one tool to the agent's tool list, marginally growing every prompt.
- Sticky mode is per-chat state living on the agent — needs a clear reset
  policy (auto-expire after one message vs. explicit `/note off`).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | Telegram transport | already a dependency of `ai-parrot-integrations`; only the existing `Command()` registration path is touched |
| `PyYAML` | OKF frontmatter serialization | already imported inside `ObsidianToolkit.create_note()` (`tools/obsidian.py:461`) |
| `pydantic` | tool input/output models | project-wide standard |
| — | **no new dependencies** | transcription, vault and wiki planes are all existing internal code |

🔗 **Existing Code to Reuse:**
- `agents/fireflies_wiki.py:165` — `FirefliesWikiAgent`; add the tool + `/note` here
- `agents/fireflies_wiki.py:243` — `_build_wiki_toolkit()`; the best-effort wiki
  wiring pattern to imitate for the notes plane
- `packages/ai-parrot/src/parrot/agents/obsidian.py:120` — `configure()` already
  calls `_initialize_tools([self.obsidian_toolkit])`, so registering one more
  toolkit/tool follows an established path
- `packages/ai-parrot/src/parrot/agents/obsidian.py:728` — `_make_note_title()`,
  the `YYYY-MM-DD-slug` convention to reuse verbatim
- `packages/ai-parrot/src/parrot/agents/obsidian.py:520` — `_build_okf_frontmatter()`,
  the OKF block shape to mirror for notes
- `packages/ai-parrot/src/parrot/tools/obsidian.py:439` — `ObsidianToolkit.create_note()`
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:166` — `LLMWikiToolkit.ingest_source()`
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/context.py:14` —
  `current_telegram_chat_id` / `telegram_chat_scope`, already active around
  the voice-note agent call (`wrapper.py:3590`)

---

### Option B: Standalone reusable `AudioNoteToolkit`

Build a new `AbstractToolkit` that owns the full capture pipeline
(`transcribe → structure → vault → wiki`) as a self-contained, mountable unit,
independent of `FirefliesWikiAgent`. Any agent could mount it; it would accept
either a transcript or a raw audio path.

✅ **Pros:**
- Cleanest separation of concerns; personal-note capture stops being a
  side-effect of a meetings agent.
- Reusable across agents and testable in isolation without a Telegram bot.
- Could accept raw audio directly, making it usable from non-transcribing
  channels (HTTP upload, watched folder, email attachment).

❌ **Cons:**
- Substantially more surface for the same user-visible outcome: a new toolkit
  needs its own vault handle, its own wiki plane construction, its own config
  block — duplicating what `FirefliesWikiAgent.configure()` already builds.
- Two independent `LLMWikiToolkit` instances over the same storage root is a
  concurrency and manifest-consistency question nobody currently has to answer.
- Speculative generality: there is exactly one consumer today.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | toolkit config + tool schemas | project standard |
| `PyYAML` | frontmatter | transitive via `ObsidianToolkit` |
| — | no new external deps | same internal planes as Option A |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/toolkit.py` — `AbstractToolkit`, incl. the
  `_open()`/`_close()`/`auto_open` lifecycle hooks (FEAT-391) for the vault handle
- `packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py:114` —
  `VoiceTranscriber.transcribe_file()`, for the raw-audio entry point
- `packages/ai-parrot/src/parrot/tools/obsidian.py:78` — `ObsidianToolkit`

---

### Option C: Channel-side capture inside `handle_voice`

Add a note-mode branch to `TelegramAgentWrapper.handle_voice()`: when the chat
is in note mode, write the transcript straight to the vault and wiki and return,
never entering the agent loop at all.

✅ **Pros:**
- Fully deterministic — zero chance the LLM answers instead of saving.
- Lowest latency and lowest token cost (no agent turn, no tool-call round trip).
- Trivial to reason about and to test.

❌ **Cons:**
- Wrong architectural layer. The transport wrapper would need a vault path, a
  wiki toolkit and an LLM client — knowledge that belongs to the agent. This
  is precisely the coupling `AbstractToolkit` exists to prevent.
- Telegram-only. MS Teams and the voice WebSocket get nothing.
- Duplicates `ObsidianToolkit` logic in the integrations package, splitting the
  vault-write path across two distributions.
- Touches the most safety-critical, most-tested handler in the wrapper
  (`test_telegram_voice.py`, `test_telegram_voice_integration.py`) for a
  feature that does not need to touch it at all.

📊 **Effort:** Low (to build) / High (to live with)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | transport | existing |
| — | no new deps | but pulls `parrot.knowledge.wiki` into `ai-parrot-integrations`, a new cross-package dependency |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:3409` —
  `handle_voice()`, the branch point
- `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py:211` —
  `voice_enabled`, the config gate pattern

---

### Option D (unconventional): Voice notes as a supervised ingest source

Rather than treating a voice note as *a note*, treat it as **a document
entering a corpus**, and hand it to the charter-driven supervised ingestion
pipeline being built in FEAT-451 (`sdd/specs/wikitoolkit-ingest-documents.spec.md`,
building on FEAT-402 `supervised-wiki-ingestion`). The transcript is written to
a watched `sources/` directory; `wikitoolkit ingest` triages it against a
charter, decides whether it earns a page, and only then authors one — with HITL
review and audit sampling already built in.

✅ **Pros:**
- Reuses a far more sophisticated machine: triage, manifest, charter-based
  relevance, HITL review, audit sampling — none of which Option A gets.
- Uniform treatment of every knowledge input (contracts, decks, meetings,
  voice) through one governed pipeline.
- Naturally solves deduplication and re-ingest, because the manifest is the
  pipeline's core abstraction rather than an afterthought.

❌ **Cons:**
- **Hard dependency on in-flight work.** FEAT-451 is specced with tasks
  reserved but not merged; FEAT-450 (wiki-namespaces) is also open. Building on
  two unlanded features couples this feature's schedule to both.
- Wrong latency profile for the actual use case. Supervised ingestion is
  batch- and review-oriented; "speak a thought, have it queryable in seconds"
  is the entire point here.
- Charter triage may legitimately *reject* a personal note as low-relevance —
  correct for a corporate corpus, exactly wrong for a personal thought.
- Over-engineered for a single-user vault where the human already decided the
  thought was worth keeping by choosing to speak it.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | `wikitoolkit ingest` pipeline | internal; FEAT-402 landed, FEAT-451 in flight (not merged) |

🔗 **Existing Code to Reuse:**
- `sdd/specs/supervised-wiki-ingestion.spec.md` — FEAT-402, the landed pipeline
- `sdd/specs/wikitoolkit-ingest-documents.spec.md` — FEAT-451, in flight
- `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:166` — `ingest_source()`,
  the entry point either way

---

## Recommendation

**Option A** is recommended.

The decisive argument is how little genuinely new machinery this feature
requires. Transcription, the vault plane, the wiki plane and the agent that
owns both are **already wired together in one object** — `FirefliesWikiAgent`
constructs its `ObsidianToolkit` in `__init__` and its `LLMWikiToolkit` in
`configure()`, and `_initialize_tools()` already exposes vault operations to
the LLM. What is missing is not infrastructure; it is one cohesive action that
does structuring + vault write + wiki ingest atomically, plus a way to know the
user meant "save this".

Option A's real cost is honest and worth naming: **LLM intent detection is
probabilistic**, and it will sometimes get it wrong in both directions. That is
the trade being made in exchange for a natural interface. The `/note` sticky
mode is the deliberate mitigation — when intent detection misfires, there is a
deterministic override that costs one command. Given a single user who can
immediately see the outcome (a `✅ Saved` line or a normal answer) and correct
course, an occasional misfire is a minor annoyance rather than data loss.

Option C would eliminate that uncertainty entirely — and it is the strongest
counter-argument to Option A. It is rejected not because it does not work, but
because it puts vault paths, an LLM client and a wiki toolkit inside a Telegram
transport handler, confines the feature to one channel, and modifies the
most-tested handler in the wrapper to do it. Buying determinism with that much
architectural debt is a bad trade when `/note` buys most of it for three lines.

Option B is the right answer to a question nobody is asking yet: there is one
consumer, and building a second `LLMWikiToolkit` over the same storage root
introduces manifest-consistency questions in exchange for reuse that has no
claimant. If a second consumer appears, Option A's tool extracts into Option B's
toolkit with little rework — the tool body *is* the toolkit body.

Option D is genuinely appealing and is the better long-term shape for a
multi-source corporate corpus. It is rejected for **now** on two grounds: it
depends on two unmerged features (FEAT-450, FEAT-451), and its batch/review
latency profile is the opposite of what "capture a fleeting thought" needs. It
should be revisited once FEAT-451 lands.

**Wiki write mechanism** — recommended: `ingest_source()`, not `create_page()`.
`create_page()` writes a page with no entry in the source manifest, so the
existing nightly `ingest_obsidian_vault(incremental=True)` would later see the
same note as a new file and author a **second** page for it. `ingest_source()`
registers the note in the manifest, making the immediate write and the nightly
incremental pass agree, and making `reingest_source()` work after the note is
edited by hand in Obsidian.

---

## Feature Description

### User-Facing Behavior

The operator sends a voice note to the Telegram bot exactly as they do today.

**Intent path** — the note starts with something like *"note to self: we should
move the retry budget into the scheduler config"*. The agent recognizes capture
intent, structures the thought, saves it, and replies with a single line:

```
✅ Saved: 2026-08-23-retry-budget-in-scheduler-config
```

Nothing else. No draft to approve, no buttons. Confirmation is deliberately
silent-by-default; corrections happen later in Obsidian, where editing is
better than it can ever be in a chat window.

**Deterministic path** — the operator sends `/note`. The chat enters capture
mode and the bot confirms briefly. The next voice (or text) message is captured
verbatim-structured with no intent guessing, and the mode resets.

Either way, seconds later the thought is retrievable:

```bash
wikitoolkit query "retry budget scheduler"
```

Questions asked by voice continue to be answered normally — this feature adds a
branch, it does not replace the existing behavior.

**Language**: the note body is written in the transcript's own language
(`TranscriptionResult.language` is already returned by the transcriber), so a
Spanish thought stays in Spanish and keeps its phrasing. The **title, tags and
OKF frontmatter are written in English**, so the wiki index and graph edges
stay uniform across a bilingual vault and cross-language retrieval keeps working.

### Internal Behavior

The flow, end to end, with each hop naming its existing owner:

1. **Transport (unchanged)** — `handle_voice()` downloads, transcribes, and
   calls `_invoke_agent()` inside `telegram_chat_scope(chat_id)`. The temp
   audio file is deleted in its existing `finally` block; **the original audio
   is not retained**.
2. **Routing** — the agent's LLM sees the transcript. Either it detects capture
   intent, or sticky note-mode is active for that chat (read from the agent's
   per-chat mode map, keyed by `current_telegram_chat_id`).
3. **Structuring** — one LLM call on the agent's pinned Haiku 4.5 turns the raw
   transcript into: an English title, an English tag set, a same-language
   summary, key points, and action items. This mirrors `_build_analysis_prompt`
   / `_parse_analysis_response` (`obsidian.py:758`, `:805`) rather than
   inventing a second prompt-and-parse convention.
4. **Vault write** — `ObsidianToolkit.create_note()` writes
   `audio-notes/<YYYY-MM-DD>-<slug>.md`, slug from the generated title via the
   existing `_make_note_title()` convention, with OKF frontmatter shaped like
   `_build_okf_frontmatter()`. The verbatim transcript is preserved under a
   `## Transcript` heading so nothing the user said is lost to summarization.
5. **Wiki write** — `LLMWikiToolkit.ingest_source(notes_wiki, <path>)` ingests
   that one file into a **separate `notes` wiki** with its own `wiki_name` and
   storage dir, built by the same best-effort pattern as
   `_build_wiki_toolkit()`. Personal thinking does not dilute meeting retrieval.
6. **Reply** — the tool returns the note title; the agent echoes one line.

The ordering is load-bearing, in the same spirit as `sync_meetings_to_wiki`'s
documented step order: **the vault write is committed before the wiki ingest is
attempted**, so the durable artifact exists before the optional one.

### Edge Cases & Error Handling

| Condition | Behavior |
|---|---|
| Empty / unintelligible transcript | `handle_voice` already answers "couldn't understand" and returns before the agent is invoked. No new handling needed. |
| LLM structuring call fails | Fall back to a verbatim note: generated title from the first words, minimal frontmatter, full transcript body. **Never lose the thought to a failed enrichment.** |
| Wiki plane unavailable (`self._notes_wiki is None`) | Note is written to Obsidian; capture reports success with a `wiki: skipped` field. Same posture the agent already takes in `_ingest_vault_into_wiki()`. |
| `ingest_source` raises | Logged as a warning, note stays in the vault, tool still returns success. The nightly incremental pass is the backstop. |
| Same-day slug collision | Append a `-2`, `-3` sequence suffix. `create_note()` raises `FileExistsError` by design (`overwrite=False`), which is the signal to retry with a suffix — not an error to surface. |
| Vault write fails (permissions, disk) | Hard failure. The agent replies with the error and does **not** claim success. This is the one failure the user must see. |
| Sticky note-mode set but never used | Auto-expire after the next message, or after a timeout, so a forgotten `/note` cannot silently swallow a later question. |
| Voice note is actually a question | Answered normally. `/note` promotes it if the user disagrees. |
| Very long transcript | Bounded by the existing `max_audio_duration_seconds` pre-check in `handle_voice`; no new limit needed. |
| Concurrent captures in one chat | Vault writes are per-file and `create_note` is `overwrite=False`; the collision-suffix path covers the race. |

---

## Capabilities

### New Capabilities
- `audio-note-capture`: turn a transcribed voice note into a structured
  Obsidian note plus an immediately-queryable wiki page, via an LLM-callable
  tool with a deterministic `/note` override.

### Modified Capabilities
- `telegram-voice-notes` (`sdd/specs/telegram-voice-notes.spec.md`) — **not
  modified**; consumed as-is. Listed here only to record that it was checked.
- Telegram agent-command handling (`wrapper.py:_register_agent_commands`) —
  additive change: enter `telegram_chat_scope` around `agent_cmd_handler` so
  agent-declared commands can resolve the invoking chat. No existing spec owns
  this; it is a small upstream enabler with independent value.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `agents/fireflies_wiki.py` | extends | New `capture_audio_note` tool, `/note` command, notes-wiki plane in `configure()`. **Gitignored — commit with `git add -f`.** |
| `packages/ai-parrot-integrations/.../telegram/wrapper.py` | modifies | ~3 lines: wrap `agent_cmd_handler` in `telegram_chat_scope`. Additive, no behavior removed. |
| `packages/ai-parrot/src/parrot/tools/obsidian.py` | depends on | `create_note()` consumed unchanged. Note: the agent currently allows only `{read, list, search, create, update}` (`obsidian.py:105-118`) — sufficient, no change needed. |
| `packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py` | depends on | `ingest_source()` / `create_wiki()` consumed unchanged. |
| `packages/ai-parrot-integrations/.../voice/transcriber/` | depends on | `TranscriptionResult.language` consumed for language routing. Unchanged. |
| Configuration (navconfig) | extends | New: `AUDIO_NOTES_WIKI_NAME`, `AUDIO_NOTES_WIKI_STORAGE_DIR`, `AUDIO_NOTES_FOLDER`. Follows the existing `_int_env`/`_bool_env`/`_list_env` helpers in `fireflies_wiki.py`. |
| Tests | extends | New unit tests for the tool + `/note`. Existing `test_telegram_voice*.py` must keep passing untouched. |
| **Breaking changes** | none | Every existing path behaves identically when the tool is never invoked. |

---

## Code Context

### User-Provided Code

The user described the idea in prose, not code:

> "We created an agent called `FirefliesWikiAgent` at `agents/fireflies_wiki.py`
> and it is used for sync fireflies+obsidian+wiki, but I was thinking: if we
> send audio notes to the agent (via Telegram using current understanding of
> voice notes) then voice notes transcribed as markdown text can be saved into
> Obsidian + Wiki at the same time."

### Verified Codebase References

#### Classes & Signatures

```python
# From agents/fireflies_wiki.py:164-165
@register_agent(name="fireflies_wiki", at_startup=True)
class FirefliesWikiAgent(FirefliesObsidianAgent):
    wiki_name: str            # line 208
    wiki_storage_dir: Path    # line 209
    _wiki: Optional[Any]      # line 224 — set in configure(), None when unavailable

    async def configure(self, app=None) -> None: ...              # line 230
    async def _build_wiki_toolkit(self) -> Optional[Any]: ...      # line 243
    def _build_pageindex_toolkit(self, storage: Path) -> Optional[Any]: ...  # line 298
    async def sync_meetings_to_wiki(self, limit=None, analysis_limit=None) -> Dict[str, Any]: ...  # line 343
    async def _ingest_vault_into_wiki(self) -> Dict[str, Any]: ... # line 411

# From packages/ai-parrot/src/parrot/agents/obsidian.py:48
class FirefliesObsidianAgent(BasicAgent):
    ANALYSIS_HEADING: str = "## Analysis"       # line 74
    vault_path: Path                            # line 96-100
    meetings_folder: str                        # line 102 (default "meetings")
    obsidian_toolkit: ObsidianToolkit           # line 105

    async def configure(self, app=None) -> None: ...   # line 120
    #   ^ already calls self._initialize_tools([self.obsidian_toolkit])  # line 132
    async def summarize_transcript(...) -> ...: ...    # line 305
    @staticmethod
    def _build_okf_frontmatter(fireflies_id: str, title: str, date: str,
                               participants: List[str], duration: float) -> Dict[str, Any]: ...  # line 520
    @staticmethod
    def _build_analysis_prompt(transcript_text: str, granularity: str = "standard") -> str: ...  # line 758
    @staticmethod
    def _parse_analysis_response(llm_response: AIMessage) -> Dict[str, Any]: ...  # line 805
    @staticmethod
    def _make_note_title(date: str, meeting_title: str) -> str: ...  # line 728
    #   ^ returns "YYYY-MM-DD-kebab-case-title"

# From packages/ai-parrot/src/parrot/tools/obsidian.py:78
class ObsidianToolkit(AbstractToolkit):
    def __init__(self, vault_path: Optional[str | Path] = None,
                 backend: Literal["local", "rest"] = "local",
                 vault: Optional[ObsidianVaultInterface] = None,
                 allowed_operations: Optional[Set[str]] = None,
                 **backend_kwargs: Any) -> None: ...          # line 127
    async def create_note(self, path: str, content: str,
                          frontmatter: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...  # line 439
    #   ^ writes with overwrite=False → raises FileExistsError if the note exists
    async def update_note(self, path: str, content: str,
                          preserve_frontmatter: bool = True) -> Dict[str, Any]: ...  # line 471
    async def append_note(self, path: str, content: str) -> Dict[str, Any]: ...      # line 504
    async def classify_note(self, path: str) -> Dict[str, Any]: ...                  # line 631
    async def apply_okf_frontmatter(...) -> ...: ...                                  # line 702

# From packages/ai-parrot/src/parrot/knowledge/wiki/toolkit.py:46
class LLMWikiToolkit(AbstractToolkit):
    async def ingest_source(self, wiki_name: str, source_path: str,
                            source_type: Optional[str] = None) -> dict[str, Any]: ...  # line 166
    #   ^ returns: source_id, pages_created, graph_nodes_created, duration_ms, status
    async def ingest_obsidian_vault(self, wiki_name: str, vault_path: str,
                                    incremental: bool = False,
                                    extract_entities: bool = False,
                                    granularity: str = "standard") -> dict[str, Any]: ...  # line 196
    #   ^ NOTE: no subfolder filter — takes a directory path only
    async def create_wiki(self, wiki_name: str,
                          description: Optional[str] = None) -> dict[str, Any]: ...    # line 445
    async def create_page(self, wiki_name: str, title: str, content: str,
                          category: str = "concept",
                          related_pages: Optional[list[str]] = None) -> dict[str, Any]: ...  # line 643
    async def reingest_source(self, ...) -> ...: ...   # line 963
    async def query(self, ...) -> ...: ...             # line 304

# From packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py
class TelegramAgentWrapper:
    async def handle_voice(self, message: Message) -> None: ...   # line 3409
    #   registered at lines 305-317 for ContentType.VOICE and ContentType.AUDIO,
    #   private chats only
    #   line 3546: transcriber.transcribe_file(tmp_path, language=voice_config.language)
    #   line 3590: `with telegram_chat_scope(chat_id):` around _invoke_agent(...)
    def _register_agent_commands(self) -> None: ...               # line 742
    #   inner `agent_cmd_handler` at line 749; registered line 794.
    #   *** It does NOT enter telegram_chat_scope — this is the gap Option A fixes. ***

# From packages/ai-parrot-integrations/src/parrot/voice/transcriber/models.py:90
class TranscriptionResult(BaseModel):
    text: str                          # line 98
    language: str                      # line 102 — ISO 639-1
    duration_seconds: float            # line 106
    confidence: Optional[float]        # line 111
    processing_time_ms: int            # line 117

# From packages/ai-parrot-integrations/src/parrot/voice/transcriber/transcriber.py:30
class VoiceTranscriber:
    async def transcribe_file(self, ...) -> TranscriptionResult: ...   # line 114
```

#### Verified Imports

```python
# All confirmed to resolve:
from parrot.agents.obsidian import FirefliesObsidianAgent          # agents/fireflies_wiki.py:38
from parrot.registry import register_agent                          # agents/fireflies_wiki.py:39
from parrot.scheduler import ScheduleType, schedule                 # agents/fireflies_wiki.py:40
from parrot.tools import tool, AbstractTool, AbstractToolkit        # parrot/tools/__init__.py:142-144
from parrot.tools.obsidian import ObsidianToolkit                   # tools/obsidian.py:78
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit            # wiki/toolkit.py:46
from parrot.knowledge.wiki.models import WikiConfig                 # agents/fireflies_wiki.py:263
from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit   # agents/fireflies_wiki.py:259
from parrot.clients.factory import LLMFactory                       # agents/fireflies_wiki.py:355
from navconfig import config                                        # agents/fireflies_wiki.py:36

from parrot.integrations.telegram.decorators import telegram_command, discover_telegram_commands
#   ^ decorators.py:5 and :35
from parrot.integrations.telegram.context import (
    telegram_chat_scope, get_current_telegram_chat_id, current_telegram_chat_id
)   # ^ context.py:19, :30, :14
```

#### Key Attributes & Constants

- `FirefliesObsidianAgent.ANALYSIS_HEADING` → `"## Analysis"` (`agents/obsidian.py:74`)
- `FirefliesObsidianAgent.vault_path` → `Path` (`agents/obsidian.py:96`); env fallback `OBSIDIAN_VAULT_PATH`, default `~/vaults/notes`
- `FirefliesObsidianAgent.meetings_folder` → `str`, default `"meetings"` (`agents/obsidian.py:102`)
- `FirefliesObsidianAgent.obsidian_toolkit.allowed_operations` → `{"read","list","search","create","update"}` (`agents/obsidian.py:105-118`)
- `FirefliesWikiAgent._DEFAULT_LLM` → `"anthropic:claude-haiku-4-5"` (`agents/fireflies_wiki.py:146`)
- `FirefliesWikiAgent._WIKI_NAME` → env `FIREFLIES_WIKI_NAME`, default `"meetings"` (`agents/fireflies_wiki.py:150`)
- `FirefliesWikiAgent._WIKI_STORAGE_DIR` → env, default `~/.parrot/wikis/meetings` (`agents/fireflies_wiki.py:151`)
- `telegram_command(command, description="", parse_mode="keyword")` — `parse_mode` ∈ `{"keyword","positional","raw"}` (`decorators.py:5-22`)
- `current_telegram_chat_id` → `ContextVar[Optional[str]]`, default `None` (`context.py:14`); value is a **string**, not an int

### Does NOT Exist (Anti-Hallucination)

Verified absent — `grep -rn` over `packages/*/src` and `agents/` returned zero hits:

- ~~`capture_audio_note`~~ — no tool, method, or symbol by this name anywhere
- ~~`AudioNoteToolkit`~~ / ~~`parrot.tools.audio_notes`~~ — no such module or class
- ~~`AudioNoteAgent`~~ — does not exist
- ~~`FirefliesWikiAgent.capture_note()`~~ / ~~`.save_voice_note()`~~ — not real methods
- ~~`ObsidianToolkit.create_audio_note()`~~ — not a real method; use `create_note()`
- ~~`LLMWikiToolkit.ingest_text()`~~ / ~~`ingest_markdown()`~~ — do **not** exist. The
  available entry points are `ingest_source(wiki_name, source_path, ...)`
  (**path-based, not string-based**), `ingest_obsidian_vault(...)`, and
  `create_page(wiki_name, title, content, ...)`.
- ~~`ingest_obsidian_vault(..., folder=...)`~~ / ~~`subfolder=`~~ / ~~`include=`~~ —
  **no folder-filter parameter exists.** Verified signature is
  `(wiki_name, vault_path, incremental, extract_entities, granularity)`.
- ~~`TelegramAgentWrapper.handle_note()`~~ / ~~`note_mode`~~ / ~~`VoiceConfig.note_mode`~~ —
  no note-mode concept exists in the Telegram integration today
- ~~`TranscriptionResult.markdown`~~ / ~~`.segments`~~ / ~~`.speaker`~~ — not fields;
  the model has exactly `text`, `language`, `duration_seconds`, `confidence`,
  `processing_time_ms`
- ~~`agent_cmd_handler` receives `chat_id`~~ — it does **not**. It receives only
  `message` and parses `raw_args` from the text; it never enters
  `telegram_chat_scope`. Any design assuming an agent command can already
  resolve its chat is wrong.
- ~~`parrot/tools/` contains concrete toolkits~~ — mostly false. Core keeps only
  base machinery; concrete toolkits ship from `parrot_tools`. **`obsidian.py` is
  an exception that genuinely lives in core** at
  `packages/ai-parrot/src/parrot/tools/obsidian.py:78` — verified.

---

## Parallelism Assessment

- **Internal parallelism**: Limited but real. The feature splits into two
  loosely-coupled tracks: (1) the `telegram_chat_scope` fix in
  `ai-parrot-integrations`, which touches no other file and could land
  independently; and (2) the tool + notes-wiki plane + `/note` command, all
  concentrated in the single file `agents/fireflies_wiki.py`. Track 2's tasks
  edit one file and must run sequentially.
- **Cross-feature independence**: Mostly independent, with two watch points.
  **FEAT-450 (wiki-namespaces)** is the significant one — it reshapes wiki
  naming/registry, which is exactly what the new `notes` wiki plane declares;
  if FEAT-450 lands first, the notes plane should adopt its namespace API
  rather than a bare `wiki_name`. **FEAT-451 (wikitoolkit-ingest-documents)**
  changes the content-acquisition layer *inside* `ingest_source`, but not its
  signature, so this feature consumes it unchanged. No shared source files with
  either. `agents/fireflies_wiki.py` is not touched by any in-flight spec.
- **Recommended isolation**: `per-spec`
- **Rationale**: The overwhelming majority of the work lands in one gitignored
  file. Splitting that across worktrees would produce guaranteed conflicts for
  no parallelism gain. A single feature worktree, tasks executed sequentially,
  is the right shape — with the wrapper fix sequenced **first** since `/note`
  depends on it.

---

## Open Questions

- [x] Flow type and base branch — *Owner: Jesus Lara*: `type: feature`, `base_branch: dev`.
- [x] Where should capture logic live — *Owner: Jesus Lara*: an LLM-callable tool on the agent (Option A); no changes to `handle_voice`.
- [x] Note shape — *Owner: Jesus Lara*: LLM-structured (title, summary, key points, action items, tags, OKF frontmatter) with the verbatim transcript preserved in a `## Transcript` section.
- [x] Wiki write timing — *Owner: Jesus Lara*: immediate direct write at capture time, not deferred to the nightly job.
- [x] Save-vs-answer trigger — *Owner: Jesus Lara*: LLM intent detection, with `/note` as a deterministic override.
- [x] Vault layout — *Owner: Jesus Lara*: `audio-notes/YYYY-MM-DD-<slug>.md`, one note per capture, sequence suffix on same-day collision.
- [x] Wiki target — *Owner: Jesus Lara*: a **separate `notes` wiki** with its own name and storage dir, not the `meetings` wiki.
- [x] Telegram feedback — *Owner: Jesus Lara*: silent confirmation only (`✅ Saved: <title>`); no HITL approval, no inline edit buttons.
- [x] `/note` semantics — *Owner: Jesus Lara*: sticky per-chat mode, plus the small upstream `telegram_chat_scope` fix to `agent_cmd_handler`.
- [x] Original audio retention — *Owner: Jesus Lara*: discard. `handle_voice`'s existing `finally` block deletes the temp file; no audio at rest.
- [x] Language — *Owner: Jesus Lara*: body in the transcript's source language; title, tags and OKF frontmatter in English.
- [x] Tenancy — *Owner: Jesus Lara*: single user, one vault. No per-chat routing.

**Still unresolved:**

- [ ] **Vault bleed into the meetings wiki.** `sync_meetings_to_wiki` calls
  `ingest_obsidian_vault(self.wiki_name, str(self.vault_path), incremental=True)`
  (`agents/fireflies_wiki.py:425`) against the **whole vault**, and the verified
  signature has **no folder filter**. As written, the nightly job would sweep
  `audio-notes/` into the *meetings* wiki — directly defeating the decision to
  keep the planes separate. Candidate fixes: (a) narrow the nightly call to
  `vault_path / meetings_folder`, which the path-based API supports today and
  which is arguably a latent bug fix regardless of this feature; (b) put audio
  notes in a separate vault entirely; (c) add a folder-filter parameter upstream.
  Option (a) looks correct and cheapest — needs confirmation that nothing else
  relies on whole-vault ingest. — *Owner: Jesus Lara*
- [ ] **Sticky-mode reset policy.** Auto-expire after the next message,
  time-box it (e.g. 5 minutes), or require explicit `/note off`? A forgotten
  sticky mode silently swallowing a later question is the main failure mode.
  Leaning: consume-on-next-message, since it is the least surprising. — *Owner: Jesus Lara*
- [ ] **Confirm `ingest_source` over `create_page`.** The recommendation rests
  on manifest-based deduplication against the nightly incremental pass. Worth
  a single empirical check: capture a note, run an incremental vault ingest,
  confirm exactly one page exists for it. — *Owner: Jesus Lara*
- [ ] **FEAT-450 sequencing.** If wiki-namespaces lands before this feature, the
  notes plane should declare a namespace rather than a bare `wiki_name`. Decide
  whether to wait, or land now and adapt. — *Owner: Jesus Lara*
- [ ] **Does the `notes` wiki need `create_wiki()` bootstrapping?** Unclear
  whether `ingest_source` into a non-existent wiki auto-creates the layout or
  fails. `_build_wiki_toolkit` currently only `mkdir`s the storage dir. — *Owner: Jesus Lara*
