---
kind: brief
slug: chatstorage-turn-record-gaps
key: chatstorage-turn-record-gaps
base_branch: dev
source:
  type: text
  ref: "live probe 2026-11-17 on origin/dev @ 80cc849fac: one tool-calling turn (BasicAgent + google:gemini-3-flash-preview + a city_population tool) through ChatStorage with a Redis hot tier and the SQLite cold backend; dump in artifacts/logs/chatstorage-probe.log"
  url: null
jira_issue_key: null
ledger_issue: null
created: "2026-11-17"
---

# Brief: Close the turn-record gaps between conversation history and ChatStorage

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/chatstorage-turn-record-gaps/tasks/. -->

## Problem

A live probe stored one turn with a real tool call and compared what conversation history, the
ChatStorage cold tier and the ChatStorage hot tier each hold. Tool calls and usage are stored in
all three, but four things were missing or inconsistent:

1. **Hot-tier reads drop tool detail.** `ChatStorage.load_conversation` served from Redis returned
   an assistant message with only `content`, `metadata`, `tools_used`, `role`, `timestamp` and
   `turn_id`. The cold read path returns `tool_invocations`, `tool_calls`, `usage`, `cost_usd`,
   `model`, `provider`, `response_time_ms`, `tenant`, `error`, `sequence` and `schema_version` as
   well. The same conversation therefore has two shapes depending on which tier answers.
2. **The cold row has `token_count: null`**, while history and the hot tier carry
   `{"user": 7, "assistant": 10, "tools": 28, "total": 45}`.
3. **Cost is never filled**: `presentation.cost_usd` and `usage.estimated_cost` were `null`, although
   a price for `gemini-3-flash-preview` is bundled.
4. **Turn `metadata.response_time` is `null`**; only `presentation.response_time_ms` (6630) had a value.

The probe also showed `tool_invocations[0].elapsed_ms == 0`. That is **not** a defect: the Gemini
client does time tool execution (`packages/ai-parrot-client-google/src/parrot/clients/google/client.py:2294`),
and the probe tool returned in under a millisecond. It is out of scope.

## Root cause

Source: the probe described above (text source; log `artifacts/logs/chatstorage-probe.log` in the main checkout).

1. `load_conversation` builds hot-tier messages by hand with a reduced key set
   (`packages/ai-parrot/src/parrot/storage/chat.py:432`), while the cold path goes through
   `ChatStorageTurn.to_messages()` (`packages/ai-parrot/src/parrot/storage/chat.py:475`). The hot
   turn already holds `tool_invocations` and the slim presentation subset in `metadata`
   (`ChatStorage._hot_tier_turn`), so the data is there and only the read shape is wrong.
2. `AbstractBot.save_conversation_turn` takes the event snapshot raw, before `add_turn` stamps the
   count (`packages/ai-parrot/src/parrot/bots/abstract.py:3004`; the comment on line 3003 says the
   snapshot MUST precede `add_turn`). The cold row is written from that snapshot.
3. `AbstractClient._compute_call_cost` returns `None` when no shared calculator is installed
   (`packages/ai-parrot/src/parrot/clients/base.py:865`). Only the observability bootstrap installs
   one, so a standalone bot never gets a cost.
4. `AIMessage.response_time` exists (`packages/ai-parrot/src/parrot/models/responses.py:163`) but no
   provider client sets it; the only writer is the generic factory parameter
   (`packages/ai-parrot/src/parrot/models/responses.py:1116`). `ConversationTurn.from_ai_message`
   copies the field into turn metadata, so it is always `None`.

## Research findings

- Symbols touched: `ChatStorage.load_conversation`, `AbstractBot.save_conversation_turn`,
  `AbstractClient._compute_call_cost`, and the `ask()` method of six provider clients.
- `ChatStorageTurn.to_messages()` (`packages/ai-parrot/src/parrot/storage/models.py`) is the
  reference shape for a conversation read.
- `count_turn(turn, counter)` (`packages/ai-parrot/src/parrot/memory/compaction/tokens.py:119`) and
  `ConversationMemory.token_counter` are the existing counting API.
- `ensure_shared_cost_calculator()` (`packages/ai-parrot/src/parrot/observability/cost/__init__.py:57`)
  already builds and caches a calculator from the bundled pricing tables.
- Every provider client calls `self._emit_after_call(..., duration_ms=...)` once per `ask()`, so each
  already has the elapsed time in hand at that point.
- `usage` is the total across model rounds (`extra_usage.rounds == 2` in the probe); no change needed.
- Open ledger issues on the touched files are unrelated to this brief (`issue:86d3647fdc26`,
  `issue:eabc58316d0a`, two lint duplicate-slug issues).

## Decisions

Answered by the owner on 2026-11-17:

1. **token_count**: count the raw snapshot, so the cold row carries a count. It counts the raw text,
   so it may differ slightly from the normalized count held in history.
2. **Cost**: fix it in the client layer. `clients/base.py` may be edited for this; the owner chose
   this knowing the file normally needs discussion first.
3. **response_time**: each provider client sets it from its own timer (model time, not bot time).

## Fix plan

- `HOTFIX-chatstorage-turn-record-gaps-1` — hot-tier reads return the same message shape as cold reads.
- `HOTFIX-chatstorage-turn-record-gaps-2` — the turn event snapshot carries a token count.
- `HOTFIX-chatstorage-turn-record-gaps-3` — the client computes cost without the observability bootstrap.
- `HOTFIX-chatstorage-turn-record-gaps-4` — provider clients set `AIMessage.response_time` in `ask()`.

The four tasks touch disjoint files and are independent.

## Validation commands

```bash
pytest packages/ai-parrot/tests/unit/storage/test_chat_hot_tier_metadata.py -q
pytest packages/ai-parrot/tests/unit/bots/test_turn_snapshot_token_count.py -q
pytest packages/ai-parrot/tests/unit/observability/test_cost_without_bootstrap.py -q
pytest packages/ai-parrot/tests/unit/clients/test_client_response_time.py -q
```
