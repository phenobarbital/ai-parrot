# TASK-5586: Documentation — durable conversation memory (architecture page, operator notes, three page updates)

**Feature**: FEAT-886 — Durable Conversation Memory
**Spec**: sdd/specs/durable-conversation-memory.spec.md (Module 18; §10 Documentation; frontmatter `docs.pages`)
**Status**: done
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5585, TASK-5578 (documents storage/backfill.py)
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 18 and §10 (`docs.policy: required`). The feature changes an operator-visible contract:
a new default `memory_type="auto"`, a turn bus that needs a writable outbox directory, a backfill runbook
for legacy rows, durable tombstones, and stricter backend write semantics. This task documents the FINAL
behavior (every code task is done), creates the architecture page, updates three existing pages, and adds a
test that keeps the pages honest (they exist, name what they document, and what they name still exists).

---

## Scope

- CREATE `wiki/memory/durable-conversation-memory.md`: architecture, event flow, hydration, deletion
  protocol, operator settings, backfill runbook, migration notes.
- MODIFY `wiki/memory/conversation-history-ownership.md`: hydration path, `"auto"` memory default,
  emitter-owned ordering.
- MODIFY `wiki/memory/per-turn-conversation-compaction.md`: streaming commit, `TurnView.parts`, canonical text.
- MODIFY `wiki/stores/storage-backends.md`: failure contract, ordered window, tombstones, index state.
- CREATE `packages/ai-parrot/tests/docs/test_durable_memory_docs.py`.
- Docstring completeness for the seven `api_modules` (spec §10) is a *review* expectation: confirm each public
  symbol in them has a Google-style docstring; fix a missing one only inside these pages' scope (report others).

**NOT in scope**:
- Code changes of any kind. A documentation finding that reveals a code defect is reported, not patched.
- Stage 2 compaction, native provider tool blocks, a durable omission store (spec Non-Goals) — mention them
  only as "not part of this feature".
- Documentation for Agent Studio (other repo) beyond one sentence saying it consumes the bus subscriber.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `wiki/memory/durable-conversation-memory.md` | CREATE | architecture + operator guide |
| `wiki/memory/conversation-history-ownership.md` | MODIFY | hydration, `auto` default, ordering |
| `wiki/memory/per-turn-conversation-compaction.md` | MODIFY | streaming commit, `parts`, canonical text |
| `wiki/stores/storage-backends.md` | MODIFY | failure contract, ordered window, tombstones, index state |
| `packages/ai-parrot/tests/docs/test_durable_memory_docs.py` | CREATE | pages exist, name their symbols/settings, and those still exist |

> Drift note: the delegating brief lists `wiki/stores/storage-backends.md` as CREATE, but the file already
> exists in the tree (231 lines, "Storage Backends Guide") and spec §10 says "update". It is MODIFY here.
> Do not overwrite it; add sections.

---

## Codebase Contract (Anti-Hallucination)

> Documentation is only as good as its names. Every symbol and setting below is created by the earlier
> tasks of this feature; verify each with `python -c "from <module> import <name>"` (or `grep` for settings)
> BEFORE writing it into a page. Cite the task that created it only in the Completion Note, never in the pages.

### Verified Imports (existing, safe to cite today)
```python
from parrot.memory import ConversationHistory, ConversationMemory, ConversationTurn, HistoryMessage, TurnView   # verified: P/memory/__init__.py
from parrot.storage import ChatStorage, ConversationBackend                                                      # verified: P/storage/__init__.py
from parrot.bots.abstract import AbstractBot       # AbstractBot.save_conversation_turn / memory_key_id          # verified: P/bots/abstract.py
```

### Names the pages must document (created by this feature — verify each exists before citing)
```text
parrot.memory.persistence  : TurnCompletedEvent (core/events/lifecycle/events/memory.py), TurnPresentation, TurnPublisher,
                             BusTurnPublisher, TURN_COMPLETED_TOPIC="conversation.turn.completed",
                             CONVERSATION_DELETED_TOPIC="conversation.deleted"                      (TASK-5569)
parrot.memory.hydration    : HydrationSource, SequenceAllocator, LocalSequenceAllocator, RedisSequenceAllocator,
                             HydrationError, HydrationUnavailableError, HydrationNotReadyError, SessionDeletedError  (TASK-5580)
parrot.memory.parts        : MessagePart, render_parts_text                                          (TASK-5572)
parrot.storage.errors      : StorageError, StorageUnavailableError, StorageWriteError, ConversationDeletedError,
                             IndexNotReadyError, InvalidTurnPayloadError                              (TASK-5570)
parrot.storage.models      : ChatStorageTurn (schema_version 2; legacy rows read as 1)               (TASK-5573)
parrot.storage.turn_bus    : TurnPersistence, setup_turn_persistence, shutdown_turn_persistence, replay_dead_letters  (TASK-5581)
parrot.storage.hydration   : ChatStorageHydrationSource                                              (TASK-5582)
parrot.storage.backfill    : run_backfill, BackfillReport; CLI `python -m parrot.storage.backfill`   (TASK-5578)
ConversationBackend (new)  : query_turn_window, max_sequence, put_tombstone, is_deleted, get_index_state, backfill_batch; BackfillBatch  (TASK-5570)
ChatStorage (new)          : store_turn, handle_turn_completed, handle_conversation_deleted, register_memory_cleaner;
                             delete_conversation / delete_turn tombstone-first; save_turn REMOVED   (TASK-5579)
ConversationMemory         : install_history (NX), ConversationTurn.sequence, RedisConversation.upsert_turn  (TASK-5580, TASK-5579)
AbstractBot                : turn_publisher, hydration_source, sequence_allocator, _load_or_hydrate_history; memory_type "auto"  (TASK-5583, TASK-5571)
HistoryMessage.parts / TurnView.parts / PrunedInvocation.parts                                         (TASK-5572)
Server                     : BotManager.setup_registry_only(turn_persistence=True), app["turn_persistence"]  (TASK-5584)

Settings (parrot.conf): REDIS_HISTORY_EXPLICIT (derived, read-only signal), REDIS_HISTORY_URL, CHAT_HOT_TTL_HOURS (default 48, 0 disables),
  PARROT_TURN_BUS_REDIS_URL, PARROT_TURN_BUS_OUTBOX_DIR (required, writable), PARROT_TURN_BUS_CHANNEL_PREFIX (default "parrot:turns:"),
  PARROT_TURN_BUS_DLQ_DSN (optional)                                                                   (TASK-5568, TASK-5571, TASK-5581)
```

### Does NOT Exist (do not document these as features)
- ~~Stage 2 / LLM summaries, `TurnState.SUMMARIZED` producers~~ — non-goal; only "reserved" (already documented in the compaction page).
- ~~Native provider `tool_use` / `tool_result` blocks from `HistoryMessage.parts`~~ — Phase 2 follow-up; today every client sends `content` only.
- ~~A durable `OmissionStore` in the cold tier~~ — follow-up.
- ~~`ChatStorage.save_turn`~~ — removed; docs must say `store_turn` / the bus subscriber.
- ~~`apps/<name>/` packages~~ — never instruct creating one (ARCHITECTURE.md Rule 3).
- ~~A Postgres-less dropped DLQ~~ — spec §7 "DLQ needs Postgres" says exhausted envelopes are "dropped" without a DSN; that bullet predates Q15 and M10. The decided behavior (spec §8 Q15, §3 M10) is: **retained as dead letters in the per-pod SQLite outbox, never dropped**. Document Q15 / M10, and note the contradiction in the Completion Note.
- ~~A Studio wiring in this repo~~ — Studio agents live in `StudioRuntimeCache`; `add_bot` refuses them.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "wiki/memory/durable-conversation-memory.md", "action": "CREATE"},
    {"path": "wiki/memory/conversation-history-ownership.md", "action": "MODIFY"},
    {"path": "wiki/memory/per-turn-conversation-compaction.md", "action": "MODIFY"},
    {"path": "wiki/stores/storage-backends.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/docs/test_durable_memory_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
- Tone and structure of `wiki/memory/conversation-history-ownership.md` (FEAT-524) and
  `wiki/memory/per-turn-conversation-compaction.md` (FEAT-525): a header line with the FEAT id and the version
  it ships in, a link to the spec, short sections, one ASCII flow diagram, tables for settings.
- The new page starts with a YAML front matter block `---\ntitle: "Durable Conversation Memory"\n---` like
  the compaction page (the other two pages being edited keep their current header).
- Code samples must be runnable against the final API; copy signatures from the source, not from the spec.

### Key Constraints
- English; no emojis; no "TODO" or placeholder text left in a page.
- Describe behavior, not tasks: do not mention TASK ids, worktrees or SDD in the pages.
- State the migration traps explicitly (they are the reason the docs policy is `required`): `auto` selects Redis
  only with an EXPLICIT history URL or an injected connection; hosts that relied on host/port defaults must set
  `REDIS_HISTORY_URL`, inject a connection, or keep `memory_type="redis"`; the outbox directory must be on a
  volume that survives a container restart for crash recovery to hold; legacy rows are not hydratable until the
  backfill has run (a session without a ready index reads as NOT READY, never as empty).
- `parrot sdd techwiki check` must report all four declared pages present (it is non-blocking but is the
  documentation gate the spec cites).

### References in Codebase
- `wiki/memory/conversation-history-ownership.md` — insert before `## Breaking changes in 0.29.0`
- `wiki/memory/per-turn-conversation-compaction.md` — insert after `## Rendered text formats`, update `## Non-goals (v1)`
- `wiki/stores/storage-backends.md` — insert before `## Known Limitations`
- `wiki/_index.yaml` — section ordering only; no per-page registration is needed

---

## Implementation Blueprint

### Steps (in order)
1. For every name in the Contract list run its import / `grep`; drop or fix any name that moved — *why*: pages must not document a symbol that does not exist.
2. Write `wiki/memory/durable-conversation-memory.md` from the outline below — *why*: the single authoritative page.
3. Update the three existing pages at the anchors below — *why*: each page's reader must learn the new contract where they already look.
4. Write the docs test; run it; run `parrot sdd techwiki check` — *why*: keeps pages honest and satisfies the §5 documentation criterion.
5. Mutation-check the test (rename a documented symbol in a page copy -> RED).

### `wiki/memory/durable-conversation-memory.md` (CREATE) — outline (write full prose; every heading is mandatory)
```markdown
---
title: "Durable Conversation Memory"
---

# Durable Conversation Memory

**FEAT-886** · shipped in **<release from pyproject>** · design: [`sdd/specs/durable-conversation-memory.spec.md`](...)

<3-5 sentences: the problem — the UI showed a conversation the agent did not remember; two stores, no bridge.>

## Two stores, one bridge
<table: ChatStorage (audit, never summarized, hot Redis tier + cold backend) vs ConversationHistory (working thread:
 summarized/limited/compacted). Rule: they are connected by events and hydration only. The bot package never imports ChatStorage.>

## Event flow
<ASCII diagram from spec §2 "Component Diagram"; then: TurnPublisher -> BusTurnPublisher -> SqliteOutbox -> Redis Streams ->
 ChatStorage.handle_turn_completed -> put_turn (cold) -> upsert_turn (hot). At-least-once; both tiers upsert by turn_id;
 retryable StorageError -> retry/backoff (3 attempts) -> DLQ; terminal errors (ConversationDeletedError,
 InvalidTurnPayloadError) are acknowledged. The event is NOT emitted through EventRegistry (payload holds conversation content).>

## Ordering fields
<emitter-owned: UTC timestamp + monotonic per-(agent, user, session) sequence from a SequenceAllocator (Redis INCR shared across
 workers; Local for in-memory/file); recovery from the durable maximum after counter loss; immutable across retries; gaps allowed.>

## Identity: agent name vs chatbot id
<ChatStorage is keyed by agent NAME; history is keyed by memory_key_id; the event carries both; hydration queries by name and
 installs under memory_key_id.>

## Hydration
<on a working-memory miss: is_deleted guard first -> load_turns (newest budget-sized window, applied descending at the backend,
 returned ascending) -> install_history (NX, atomic, never partial) -> guard recheck. Outcomes table:
 None / HydrationNotReadyError / HydrationUnavailableError / SessionDeletedError and what the bot does with each
 (pending history retried on a later round; deleted and unverifiable guard fail closed).>

## Deletion protocol
<tombstone first (durable, outside TTL and cascade, retained indefinitely, session ids not reused) -> clear turns, chrono
 companions, artifacts, hot tier, registered working-memory cleaners -> publish CONVERSATION_DELETED_TOPIC for idempotent cleanup.
 Turn-scoped tombstones for delete_turn. Subscribers, DLQ replay, backfill and hydration reject tombstoned identities.>

## What a stored turn contains
<ChatStorageTurn fields: tool_invocations with output/error/elapsed, usage, cost, model, provider, output_mode, data, code,
 sources, response_time_ms, tenant; schema_version 2; tolerant reader for pre-existing rows -> schema_version 1.>

## Structured history parts
<MessagePart, render_parts_text, TurnView.parts, HistoryMessage.parts; Phase 1: every client still receives `content` once;
 with compaction disabled output is byte-identical and parts is None.>

## Operator settings
<table with the Settings list of the Contract: name | default | meaning. Include how `auto` resolves memory_type
 (injected connection or explicit REDIS_HISTORY_URL -> Redis; else in-memory; an explicit memory_type always wins;
 a configured Redis failure surfaces, no fallback).>

## Backfill runbook
<python -m parrot.storage.backfill: resumable (cursor file), batched (--batch-size), safe next to live writes, reports invalid
 sessions (missing/unparseable timestamps stay 'invalid' -> unready). Order of operations for an existing deployment.
 get_index_state: 'ready' | 'pending' | 'invalid'; new sessions are 'ready'. Not-ready is never reported as empty.>

## Migration notes
<bulleted: auto default; shared host/port Redis hosts; outbox directory + volume; PARROT_TURN_BUS_DLQ_DSN set -> Postgres DLQ, unset ->
 dead letters retained in the SQLite outbox (replay_dead_letters reads whichever store holds them); CHAT_HOT_TTL_HOURS; hard cut:
 ChatStorage.save_turn is gone, AgentTalk writes nothing; Agent Studio consumes the bus subscriber (separate repo).>

## Failure modes
<table: situation | behavior (cold tier down, outbox full -> publish logged at ERROR and the round still succeeds, bus fails to start
 -> server runs without persistence, hydration source down -> pending history, deleted session).>

## Not part of this feature
<Stage 2 summaries, native provider tool blocks, durable omission store, merging the two stores.>
```
**Why this shape**: the section list is the spec §10 list for this page (architecture, event flow, hydration,
deletion protocol, operator settings, backfill runbook, migration notes) plus the identity, ordering, stored-turn
and failure-mode sections an operator needs to debug it. Keep each section short; link instead of repeating the
two older pages.

### `wiki/memory/conversation-history-ownership.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c -x -F '## Breaking changes in 0.29.0' wiki/memory/conversation-history-ownership.md)
# INSERT a new section immediately BEFORE that heading:

## Hydration, ordering and the `auto` memory default (FEAT-886)
<- `memory_type` now defaults to `"auto"` ... (resolution table)
<- A bot with a `hydration_source` hydrates a missing history from ChatStorage once ... (link to durable-conversation-memory.md)
<- `save_conversation_turn` stamps a UTC timestamp and a sequence, then publishes the turn event after `add_turn` ...
<- The bot is still the only writer; AgentTalk no longer injects a memory or writes ChatStorage.>
```
Also update the "How a bot persists a turn" section (heading `## How a bot persists a turn`, occurrences: 1) with one
paragraph: the optional `presentation=` argument and the publish-after-save step, with a link to the new page.
**Why**: this page is where readers learn who writes history; it must not leave them believing the handler persists it.

### `wiki/memory/per-turn-conversation-compaction.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c -x -F '## Rendered text formats' wiki/memory/per-turn-conversation-compaction.md)
# INSERT a new section AFTER the "Rendered text formats" section (i.e. before the next `---` + `## The write path` block):

## Streaming commit and structured parts (FEAT-886)
<- `ask_stream` now commits compaction state (boundary, calibration, `stage2_needed`) exactly like `ask`; the partial-save on
   error keeps `compaction=None`.
<- `TurnView.parts` / `PrunedInvocation.parts`: already-budgeted parts; `assistant_suffix == render_parts_text(parts)`;
   the token counter measures that exact text; RAW / PRUNED / dropped behavior; a custom `PrunePolicy` that returns no parts yields
   one text part; `HistoryMessage.parts` is informational in Phase 1 and every `_format_history` consumes `content` once.
<- Disabled compaction: byte-identical output, `parts is None`.>

# occurrences: 1 (verified: grep -c -x -F '## Non-goals (v1)' ...)
# In that section, change the `ChatStorage` bullet to say ChatStorage is still never compacted, and add one bullet:
#   hydration from ChatStorage fills the working history with RAW turns that then pass through the normal budget pass.
```
**Why**: readers of the compaction page must know the streaming path and parts exist, and that ChatStorage remains uncompacted by design.

### `wiki/stores/storage-backends.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c -x -F '## Known Limitations' wiki/stores/storage-backends.md)
# INSERT these sections immediately BEFORE that heading (keep the `---` separators the page uses):

## Failure contract
<`put_turn` returns only after a durable write or raises a typed StorageError (StorageUnavailableError when disconnected,
 StorageWriteError when the write fails, ConversationDeletedError when tombstoned); `query_turns` raises instead of returning []
 when disconnected. Applies to all four backends (DynamoDB no longer swallows ClientError/BotoCoreError).>

## Ordered window and index state
<`query_turn_window(limit)`: newest-N by (timestamp, sequence, turn_id), limit applied descending at the backend, returned ascending;
 per-backend implementation table: SQLite/Postgres composite index + ORDER BY ... DESC LIMIT; Mongo compound index;
 DynamoDB chronological companion item in the same partition written in one TransactWriteItems with the canonical item and the
 tombstone ConditionCheck. `get_index_state`: ready | pending | invalid; IndexNotReadyError; legacy rows -> backfill runbook link.>

## Tombstones
<`put_tombstone` / `is_deleted`; session and turn scope; own table/collection/items so `delete_thread_cascade` and TTL cannot remove
 them (DynamoDB tombstone items carry no `ttl`); `put_turn` is atomic with the tombstone check.>
```
Also add one row/sentence to `## Known Limitations`: backends are now abstract on the new operations, so a custom
`ConversationBackend` subclass must implement them (`query_turn_window`, `max_sequence`, `put_tombstone`, `is_deleted`,
`get_index_state`, `backfill_batch`).
**Why**: the storage guide is where backend authors and operators look; the new abstract methods are a breaking
change for custom backends and must be stated there.

### `packages/ai-parrot/tests/docs/test_durable_memory_docs.py` (CREATE)
```python
"""FEAT-886 documentation gate: the pages exist, name what they document, and what they name is real."""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]   # same convention as tests/docs/test_cli_connections_docs.py
SPEC = ROOT / "sdd" / "specs" / "durable-conversation-memory.spec.md"

_REQUIRED = {
    "wiki/memory/durable-conversation-memory.md": [
        "TurnCompletedEvent", "TurnPresentation", "BusTurnPublisher", "HydrationSource", "SequenceAllocator",
        "ChatStorageTurn", "setup_turn_persistence", "run_backfill", "python -m parrot.storage.backfill",
        "memory_type", "auto", "REDIS_HISTORY_EXPLICIT", "CHAT_HOT_TTL_HOURS", "PARROT_TURN_BUS_REDIS_URL",
        "PARROT_TURN_BUS_OUTBOX_DIR", "PARROT_TURN_BUS_CHANNEL_PREFIX", "PARROT_TURN_BUS_DLQ_DSN",
        "conversation.turn.completed", "tombstone", "MessagePart",
    ],
    "wiki/memory/conversation-history-ownership.md": ["hydrat", "auto", "sequence"],
    "wiki/memory/per-turn-conversation-compaction.md": ["ask_stream", "parts", "render_parts_text"],
    "wiki/stores/storage-backends.md": ["StorageWriteError", "query_turn_window", "put_tombstone", "get_index_state", "IndexNotReadyError"],
}
_SYMBOLS = {
    "parrot.memory.persistence": ["TurnPresentation", "TurnPublisher", "BusTurnPublisher", "TURN_COMPLETED_TOPIC"],
    "parrot.memory.hydration": ["HydrationSource", "SequenceAllocator", "SessionDeletedError"],
    "parrot.memory.parts": ["MessagePart", "render_parts_text"],
    "parrot.storage.errors": ["StorageError", "StorageWriteError", "ConversationDeletedError", "IndexNotReadyError"],
    "parrot.storage.turn_bus": ["setup_turn_persistence", "shutdown_turn_persistence"],
    "parrot.storage.hydration": ["ChatStorageHydrationSource"],
    "parrot.storage.backfill": ["run_backfill", "BackfillReport"],
}


@pytest.mark.parametrize("rel,needles", sorted(_REQUIRED.items()))
def test_page_exists_and_names_its_subjects(rel: str, needles: list[str]) -> None:
    """Each declared page exists and mentions the symbols/settings it is responsible for."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    missing = [n for n in needles if n not in text]
    assert not missing, f"{rel} does not mention: {missing}"


def test_spec_declared_pages_all_exist() -> None:
    """Every page in the spec frontmatter `docs.pages` list exists (spec §5 documentation criterion)."""
    # FILL IN: parse the lines between `pages:` and `api_modules:` of SPEC with a regex (`- wiki/...`);
    #          assert the list is non-empty and every path exists under ROOT — bounded by spec §10.


@pytest.mark.parametrize("module,names", sorted(_SYMBOLS.items()))
def test_documented_symbols_exist(module: str, names: list[str]) -> None:
    """What the pages cite is importable (docs cannot describe a symbol that does not exist)."""
    mod = importlib.import_module(module)
    assert [n for n in names if not hasattr(mod, n)] == []


def test_documented_settings_exist_in_conf() -> None:
    """The settings the operator page lists are declared in parrot.conf (source check: names are read via config.get)."""
    # FILL IN: read `parrot/conf.py` text via importlib.util.find_spec("parrot.conf").origin and assert each of
    #          REDIS_HISTORY_EXPLICIT, CHAT_HOT_TTL_HOURS, PARROT_TURN_BUS_REDIS_URL, PARROT_TURN_BUS_OUTBOX_DIR,
    #          PARROT_TURN_BUS_CHANNEL_PREFIX, PARROT_TURN_BUS_DLQ_DSN appears — bounded by spec §3 M10 / M12 and the page's settings table.


def test_pages_have_no_placeholders_or_sdd_ids() -> None:
    """Pages describe behavior: no TODO/TBD, no TASK-/FEAT- worktree chatter beyond the single FEAT-886 header reference."""
    # FILL IN: for the four pages assert no "TODO", "TBD", "TASK-" substring; at most one "FEAT-886" in the new page header
    #          and the section titles that cite it — bounded by Key Constraints above.
```
**Why this shape**: three independent checks (page exists + names subjects; names are real; no placeholders) so a
rename in code or a stale page fails CI. The checks read text and import modules only; nothing touches the network.

### FILL IN checklist
- [ ] `durable-conversation-memory.md` — release/version in the header line (read `packages/ai-parrot/pyproject.toml` `version`); bounded by the spec's "Target version: 2.2.0" (use it only if the package version agrees)
- [ ] `durable-conversation-memory.md` Operator settings — exact defaults from the final `parrot/conf.py`; bounded by spec §3 M10/M12 and Q10
- [ ] `durable-conversation-memory.md` Backfill runbook — real CLI flags from `parrot/storage/backfill.py --help`; bounded by TASK-5578's final CLI
- [ ] `test_spec_declared_pages_all_exist` / `test_documented_settings_exist_in_conf` / `test_pages_have_no_placeholders_or_sdd_ids` — bodies as described
- [ ] Docstring review of the seven `api_modules` — list any public symbol without a docstring in the Completion Note

---

## Acceptance Criteria

- [ ] The four pages declared in spec §10 exist and each covers its bullet of §10 (`parrot sdd techwiki check` reports no missing page).
- [ ] The new page contains every mandatory section of the outline, with the migration traps stated explicitly (auto default, outbox volume, backfill before hydration, DLQ with and without a DSN).
- [ ] Every symbol and setting a page names exists (`test_documented_symbols_exist`, `test_documented_settings_exist_in_conf`).
- [ ] The pages follow spec §8 Q15 / §3 M10 for the DLQ without a Postgres DSN (retained in the SQLite outbox, never dropped), and the stale §7 bullet is reported.
- [ ] No TODO / TBD / TASK- text in any page.
- [ ] Mutation check: rename `render_parts_text` in the compaction page copy (or delete the `## Backfill runbook` heading's `python -m parrot.storage.backfill` line) -> `test_page_exists_and_names_its_subjects` goes RED.
- [ ] `ruff check packages/ai-parrot/tests/docs/test_durable_memory_docs.py` is clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/docs/test_durable_memory_docs.py -q`

---

## Test Specification

The docs test above is the specification. Its three checks map to the acceptance criteria: existence and
naming (`test_page_exists_and_names_its_subjects`, `test_spec_declared_pages_all_exist`), truthfulness
(`test_documented_symbols_exist`, `test_documented_settings_exist_in_conf`) and hygiene
(`test_pages_have_no_placeholders_or_sdd_ids`). No fixtures beyond `ROOT`.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug durable-conversation-memory --feature-id FEAT-886`)
2. **Read the spec** (§2 all pieces, §7 Known Risks, §8 Q10/Q14/Q15/Q16, §10)
3. **Check dependencies** — TASK-5585 must be `"done"` in `sdd/tasks/index/durable-conversation-memory.json`
   (it is the last code task, so every name below exists)
4. **Verify the Codebase Contract** — run the import/grep for every listed name; fix the pages and the test, not the code
5. **Update status** in the per-spec index -> `"in-progress"`
6. **Implement** from the Blueprint; complete every `# FILL IN:`
7. **Verify** all acceptance criteria, including `parrot sdd techwiki check`
8. **Commit the docs** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5586 durable-conversation-memory verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Created wiki/memory/durable-conversation-memory.md (all mandatory headings; no release number, per the repo owner's rule that releases are theirs to announce), added FEAT-886 sections to conversation-history-ownership.md, per-turn-conversation-compaction.md (+ updated its ChatStorage non-goal) and storage-backends.md (MODIFY, the file already existed), and tests/docs/test_durable_memory_docs.py.

**Completed by**: sdd-worker (sequential fallback)
**Date**: 2026-11-13
**Tests**: test_durable_memory_docs 9 passed (pages exist and are clean, mandatory headings, every documented symbol / method / setting exists and is named, `save_turn` only mentioned as removed). `parrot sdd techwiki check --spec ...` -> "Docs: required — ok". Mutation: renaming a documented symbol in the page -> RED.
**Notes**: (1) spec §7 "DLQ needs Postgres" says exhausted envelopes are dropped without a DSN; that predates spec §8 Q15 / M10, and the page documents the decided behavior (retained as dead letters in a local SQLite store, never dropped). (2) Docstring review of the seven api_modules: only LocalSequenceAllocator.next and RedisSequenceAllocator.next lack their own docstring (they inherit the ABC's); left as is (code is out of this task's scope). (3) The docs say "SQLite dead-letter store next to the outbox" — that is what turn_bus implements. (4) Items documented as NOT covered: DynamoDB backend (TASK-5577) is described by its design in storage-backends.md but was not implemented/verified in this run if still pending — see the DONE file.

**Deviations from spec**: none
