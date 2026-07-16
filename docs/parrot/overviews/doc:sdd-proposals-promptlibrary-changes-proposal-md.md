---
type: Wiki Overview
title: 'FEAT-167 — Prompt Library: `agent_id` support + new `UserPrompts` model'
id: doc:sdd-proposals-promptlibrary-changes-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. The full source is at
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

---
id: FEAT-167
title: "Prompt Library: agent_id support + new UserPrompts model"
slug: promptlibrary-changes
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-05-13
  summary_oneline: "PromptLibrary supports public per-chatbot prompts only; need agent_id support and a new UserPrompts model for per-user prompts."
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-167/
created: 2026-05-13
updated: 2026-05-13
---

# FEAT-167 — Prompt Library: `agent_id` support + new `UserPrompts` model

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-167/`](../state/FEAT-167/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at
`sdd/state/FEAT-167/source.md`.

> # Prompt Library Changes
>
> Current `PromptLibrary` model only cover "public" prompts, prompts are
> per-chatbot and publicily available for all users. But we need then a
> new model, `UserPrompts` for saving per-user and per-agent prompts.
>
> # changes:
> - prompt_library uses chatbot_id as uuid, but manually-created (by code)
>   and AgentRegistry agents doesn't have chatbot_id as uuid, change to use
>   chatbot_id or agent_id (for agents).
> - modify `PromptLibraryManagement` to filter by chatbot_id or agent_id
>   when GET retrieved a single bot instance
> - Add the "ALTER TABLE" documentation to change the current
>   `navigator.prompt_library` table.
> - Create a new model `UserPrompts` with api `/api/v1/agents/user_prompts`
>   allow users to save own prompts. constraint is user_id / chatbot_id
>   (can be an string, not uuid)
> - add in model documentation the "create table sentence", table will be
>   `navigator.users_prompts`.

**Initial signals** (extracted, not interpreted):
- Verbs: "change", "modify", "add", "create" → suggests enrichment (additive)
- Named entities: `PromptLibrary`, `PromptLibraryManagement`, `UserPrompts`,
  `navigator.prompt_library`, `navigator.users_prompts`,
  `/api/v1/agents/user_prompts`, `AgentRegistry`, `chatbot_id`, `agent_id`
- Components / labels: n/a (inline source)
- Acceptance criteria provided: 5 bullet items

---

## 1. Synthesis Summary

`PromptLibrary` today binds every prompt to a DB-backed bot via a strict
UUID `chatbot_id`, which excludes registry/code-defined agents whose
identity is a string `agent_id` (verified at `agents/demo.py:161`,
`bots/search.py:69`, `bots/product.py:53`, `bots/agent.py:54`,
`handlers/agent.py:90`). The fix is two-pronged: (1) **enrich**
`navigator.prompt_library` with a nullable `agent_id VARCHAR` column and a
CHECK constraint enforcing that exactly one of `(chatbot_id, agent_id)` is
set, and teach `PromptLibraryManagement` to GET-filter by either key; and
(2) **introduce** `UserPrompts` — a new per-user model at
`navigator.users_prompts` (composite PK `(user_id, prompt_id)`, FK
`auth.users(user_id) ON DELETE CASCADE`) with `chatbot_id` typed as
`VARCHAR` so it can store either a UUID string or a registry slug. The
new handler `UserPromptsManagement` is exposed at
`/api/v1/agents/user_prompts` and mirrors the established `UserBotModel`
sibling pattern in `handlers/models/users_bots.py` and
`handlers/models/users_bots_creation.sql`.

---

## 2. Codebase Findings

> All entries here are grounded in research findings persisted at
> `sdd/state/FEAT-167/findings/`. Each cites the finding ID(s).

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/handlers/models/bots.py` | `PromptLibrary` | 558-598 | Model to alter (add `agent_id`, relax `chatbot_id`) | F001 |
| 2 | `packages/ai-parrot/src/parrot/handlers/bots.py` | `PromptLibraryManagement` | 96-110 | Handler to extend with GET filtering by either key | F002 |
| 3 | `packages/ai-parrot/src/parrot/handlers/models/__init__.py` | module exports | 3-34 | Add `UserPrompts` export | F004 |
| 4 | `packages/ai-parrot/src/parrot/handlers/models/users_bots.py` | `UserBotModel` | 26-117 | Reference pattern for per-user model + composite PK | F004 |
| 5 | `packages/ai-parrot/src/parrot/handlers/models/users_bots_creation.sql` | `navigator.users_bots` DDL | 7-91 | Reference DDL pattern (FK CASCADE, indexes, trigger, comments) | F004 |
| 6 | `app.py` | `PromptLibraryManagement.configure` | 135 | Existing route wiring; add `UserPromptsManagement.configure` here | F002 |

### 2.2 Constraints Discovered

- **`agent_id` is always a Python `str`** (registry slug), never a UUID.
  *Implication*: the new `prompt_library.agent_id` column must be `VARCHAR`,
  not `UUID`. *Evidence*: F003

- **Per-user resources use composite PK with FK CASCADE.**
  `users_bots` is keyed by `(user_id, chatbot_id)` with
  `REFERENCES auth.users(user_id) ON DELETE CASCADE`.
  *Implication*: `users_prompts` must follow the same pattern for
  credential hygiene and account-deletion correctness. *Evidence*: F004

- **DDL convention is a separate `<model>_creation.sql` file**, not
  embedded in the model's docstring. `PromptLibrary` is the exception;
  the new `users_prompts` model must follow the dominant pattern.
  *Evidence*: F004

- **User identity is read via `await self.get_userid(session=self._session)`**
  (seen at `handlers/bots.py:109,182,790`).
  *Implication*: `UserPromptsManagement` reuses this accessor to populate
  `user_id` and `created_by`. *Evidence*: F005

- **Route wiring lives in `app.py`**, not the class `path` attribute.
  `PromptLibraryManagement.configure(self.app, '/api/v1/chatbots/prompt_library')`
  overrides the class default `/api/v1/prompt_library`. The new
  `UserPromptsManagement` must be wired explicitly. *Evidence*: F002

- **Zero existing test coverage for `PromptLibrary`.** A `grep` of both
  `packages/ai-parrot/tests/` and `tests/` returns no hits.
  *Implication*: ship at least a minimal smoke test alongside the new
  model. *Evidence*: F005

### 2.3 Recent History (Relevant)

`git log --since=180d` on `models/bots.py`, `handlers/bots.py`, and
`models/users_bots_creation.sql` shows recent additive activity around
`BotModel` (reranker configs, embedding-model fold, PBAC permissions) and
the introduction of `users_bots` itself (commit `8367fe1b — feat:
per-user defined bots with encrypted credentials at rest`). There are
**no recent commits touching `PromptLibrary`**, confirming the model has
been stable and the proposed changes are not racing concurrent work.
*Evidence*: F005 (git_log query Q012)

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`navigator.users_prompts` table + `UserPrompts` model** —
  per-user, per-bot/agent prompt store with composite PK
  `(user_id, prompt_id)` and `chatbot_id VARCHAR` so either UUIDs or
  registry slugs work.
- **`UserPromptsManagement(ModelView)`** — handler at
  `/api/v1/agents/user_prompts` mirroring `PromptLibraryManagement`'s
  shape but with `user_id` enforced from session on every write.
- **New DDL file**
  `packages/ai-parrot/src/parrot/handlers/models/users_prompts_creation.sql`
  following the `users_bots_creation.sql` template (DDL + trigger +
  comments).

### What Changes

- **`packages/ai-parrot/src/parrot/handlers/models/bots.py`::`PromptLibrary`**
  — add `agent_id: Optional[str]` field; relax `chatbot_id` to
  `Optional[uuid.UUID]`. Update the embedded `CREATE TABLE` docstring
  and add an **ALTER TABLE** migration block for the existing table.
  *Evidence*: F001
- **`packages/ai-parrot/src/parrot/handlers/bots.py`::`PromptLibraryManagement`**
  — extend GET behaviour to filter by `chatbot_id` OR `agent_id` query
  parameter when retrieving the prompts for a single bot/agent instance.
  *Evidence*: F002
- **`packages/ai-parrot/src/parrot/handlers/models/__init__.py`** —
  export `UserPrompts` alongside the existing models.
  *Evidence*: F004
- **`app.py`** — wire `UserPromptsManagement.configure(self.app,
  '/api/v1/agents/user_prompts')` next to the existing
  `PromptLibraryManagement.configure(...)` call at line 135.
  *Evidence*: F002

### What's Untouched (Non-Goals)

- **`BotModel` / `UserBotModel`** — these are bot-definition tables and
  are unaffected.
- **`PromptCategory` enum** — values stay as today (TECH, IDEA, EXPLAIN,
  …); both `PromptLibrary` and `UserPrompts` reuse it.
- **Public-to-private migration** — no automatic copying of existing
  `prompt_library` rows into `users_prompts`. Users start with an empty
  per-user store.
- **PBAC integration** — `UserPrompts` is implicitly scoped by
  authenticated `user_id`; no per-row policy rules in this iteration.

### Patterns to Follow

- **Sibling-model template**:
  `packages/ai-parrot/src/parrot/handlers/models/users_bots.py` (Python)
  and `users_bots_creation.sql` (DDL). *Evidence*: F004
- **Authenticated-user accessor**: `self.get_userid(session=self._session)`
  per `handlers/bots.py:109,790`. *Evidence*: F005
- **Schema constant**: import `PARROT_SCHEMA` from `parrot.conf` rather
  than hard-coding `"navigator"`. *Evidence*: F004
- **`updated_at` trigger**: copy the
  `trigger_users_bots_updated_at`/`update_users_bots_updated_at()`
  pattern from `users_bots_creation.sql:79-91` for the new table.
  *Evidence*: F004

### Integration Risks

- **Backward compatibility on `prompt_library.chatbot_id`.** Relaxing
  `chatbot_id` to nullable means existing reads that assume `NOT NULL`
  may break. *Mitigation*: the ALTER TABLE keeps current rows with
  `chatbot_id` set; the `CHECK ((chatbot_id IS NOT NULL) <> (agent_id IS
  NOT NULL))` constraint guarantees every row still has exactly one key
  set. *Evidence*: F001

- **GET filter ambiguity.** Today the handler relies on `ModelView`'s
  generic filter; teaching it about `agent_id` must not break existing
  query strings using `chatbot_id`. *Mitigation*: prefer the explicit
  query param `agent_id=<slug>`; fall back to `chatbot_id=<uuid>`; if
  both are present, 400. *Evidence*: F002

- **VARCHAR `chatbot_id` on `users_prompts`** mixes UUID strings and
  registry slugs into one column. *Mitigation*: store as plain VARCHAR
  with index; let the handler normalise/coerce at write time. The user
  explicitly requested this shape. *Evidence*: F003

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | `PromptLibrary` lives at `handlers/models/bots.py:558-598` and is the only model to alter | F001 | high | direct grep + read confirmation |
| C2 | `PromptLibraryManagement` at `handlers/bots.py:96-110` is the only handler to extend | F002 | high | direct read; `grep PromptLibraryManagement` is exhaustive |
| C3 | `agent_id` is always `str` across bots/agents | F003 | high | grep returns consistent `str` annotations across 6 files |
| C4 | `users_bots` is the canonical reference pattern for per-user models | F004 | high | only existing sibling model; pattern is consistent |
| C5 | Route wiring is in `app.py:135`, not the class `path` attribute | F002 | high | `grep PromptLibraryManagement app.py` confirms |
| C6 | `self.get_userid(session=...)` is the user-id accessor | F005 | high | used at 3 distinct call sites in same file |
| C7 | `CHECK ((chatbot_id IS NOT NULL) <> (agent_id IS NOT NULL))` is acceptable to the requester | F001, F003 | medium | inferred design from explicit requirements; not stated literally |
| C8 | `users_prompts.chatbot_id` should be `VARCHAR` (not UUID) | F003 | high | explicit user requirement; aligns with `agent_id: str` precedent |
| C9 | No existing tests for `PromptLibrary` | F005 | high | exhaustive grep returns zero hits |

Distribution: **8** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Uniqueness on the public `PromptLibrary`: should
  `(chatbot_id|agent_id, title)` be UNIQUE?** — *Resolved*: Yes — add
  UNIQUE constraint on (bot_or_agent, title).
  *Resolves claim*: C7

- [x] **Should `UserPrompts` mirror `PromptLibrary`'s `prompt_category`
  and `prompt_tags`?** — *Resolved*: Mirror — keep both for parity with
  the public library.
  *Resolves claim*: hypothesis H2 (synthesis)

- [x] **Add a future-proof `is_public BOOLEAN` flag on `UserPrompts`
  (defaults FALSE)?** — *Resolved*: Yes — add `is_public BOOLEAN
  DEFAULT FALSE` so prompts can later be promoted to public.
  *Resolves claim*: hypothesis H2 (synthesis)

### Unresolved (defer to spec / implementation)

- None.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-167`** — *Rationale*: localization is high-confidence
(C1, C2, C5), the sibling-model template is already in the tree (C4),
and all three open questions resolved during this proposal. The spec
can codify the ALTER TABLE migration, the new `users_prompts` DDL, the
handler filter contract, and the test scaffolding without further
architectural exploration.

### Alternatives

- **`/sdd-brainstorm FEAT-167`** — only if you want to explore an
  alternative to the dual-column `(chatbot_id, agent_id) + CHECK`
  approach (e.g., a single polymorphic `target_id VARCHAR` column with a
  `target_kind` discriminator). Not recommended — the explicit-column
  approach matches the user's request more directly.
- **`/sdd-task FEAT-167`** — only acceptable if you want to land just
  one of the two pillars (e.g., the ALTER TABLE first, then `UserPrompts`
  later). The two pillars are independent enough to split if scheduling
  pressure requires it.
- **Manual review** — not warranted; confidence is high and unknowns
  are resolved.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-167/state.json` |
| Source (raw) | `sdd/state/FEAT-167/source.md` |
| Research plan | `sdd/state/FEAT-167/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-167/findings/F001-prompt-library-model.md`, `F002-prompt-library-handler.md`, `F003-agent-id-is-string.md`, `F004-user-bot-sibling-pattern.md`, `F005-user-identity-and-tests.md` |
| Synthesis (JSON) | `sdd/state/FEAT-167/synthesis.json` |

**Budget consumed**:
- Files read: 6 / 40
- Grep calls: 12 / 25
- Git calls: 1 / 10
- Wall time: ~120s / 300s
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (request uses
additive verbs "change", "add", "create"; no negation, no bug).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara |
