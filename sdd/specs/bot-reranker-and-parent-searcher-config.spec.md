# Feature Specification: DB-Persisted Reranker & Parent-Searcher Config for AI Bots

**Feature ID**: FEAT-133
**Date**: 2026-04-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: ai-parrot next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

`navigator.ai_bots` (`packages/ai-parrot/src/parrot/handlers/creation.sql:5`)
already persists `vector_store_config` JSONB, which lets a bot loaded from the
DB activate **FEAT-127** (contextual embedding headers) by simply forwarding
config kwargs to `PgVectorStore`. However, **FEAT-126** (local cross-encoder
reranker) and **FEAT-128** (parent-child retrieval via `AbstractParentSearcher`)
have no persistence path:

- `AbstractBot` accepts `reranker=`, `parent_searcher=`, and `expand_to_parent=`
  as constructor kwargs (`packages/ai-parrot/src/parrot/bots/abstract.py:398,
  407-408`), but these are **Python objects**, not JSON.
- `BotManager` (`packages/ai-parrot/src/parrot/manager/manager.py:340-375`)
  forwards a fixed set of named kwargs from `BotModel` to the bot constructor
  — there is no column for reranker/parent-searcher and no factory call.
- The factory pattern that resolves `vector_store_config` into a concrete
  `PgVectorStore` (`packages/ai-parrot/src/parrot/interfaces/vector.py:42-75`)
  has no equivalent for rerankers or parent searchers.

The consequence today: a bot row in `navigator.ai_bots` (e.g., `att_concierge`,
FEAT-131) cannot exercise FEAT-126/FEAT-128 even though the underlying code
paths are wired into `BaseBot.ask()` / `BaseBot.conversation()`. The features
work only when the bot is built imperatively in a Python script (e.g.
`examples/chatbots/att/bot.py`), not when loaded by `BotManager` from the DB.

This blocks production deployment of these features in `navigator-api`, where
all bots are DB-driven via `BotManager`.

### Goals

1. **G1** — Two new JSONB columns on `navigator.ai_bots` to persist reranker
   and parent-searcher configuration, with empty-dict defaults preserving full
   back-compatibility.
2. **G2** — Two new factories (`parrot.rerankers.factory.create_reranker`,
   `parrot.stores.parents.factory.create_parent_searcher`) that resolve a
   config dict into a concrete instance, branching on a `type` discriminator.
3. **G3** — `BotManager.create_bot()` invokes the factories before bot
   construction and forwards the resulting instances (plus
   `expand_to_parent`) as kwargs.
4. **G4** — A bot loaded from a DB row with valid `reranker_config` and
   `parent_searcher_config` ejecuta el path de FEAT-126 + FEAT-128
   exactly as the imperative script in `examples/chatbots/att/bot.py`.
5. **G5** — Unknown `type` values raise `ConfigError` at bot startup
   (fail-loud, no silent fallback) so misconfigurations are caught immediately.
6. **G6** — Existing rows (with empty `{}` configs) continue to load with
   `reranker=None`, `parent_searcher=None`, `expand_to_parent=False`, i.e.,
   identical behavior to today.

### Non-Goals (explicitly out of scope)

- **Bulk migration** of existing agents in `navigator.ai_bots` to populate
  the new columns. A separate post-feature flow will batch-update the rows
  for production agents.
- **UI/forms** to edit reranker/parent-searcher configs in any chatbot admin
  panel. The feature ships as code + DDL only; UI is a follow-up.
- **New reranker or parent-searcher implementations**. The factories register
  only types that already exist (`local_cross_encoder`, `llm`, `in_table`).
- **Single combined `rag_config` JSONB**. We deliberately use two separate
  columns to keep concerns orthogonal and mirror the existing
  `vector_store_config` pattern.
- **Config schema validation via Pydantic on the DB column**. The factories
  validate at instantiation time; persisting raw `dict` mirrors how
  `vector_store_config` is handled today.

---

## 2. Architectural Design

### Overview

Two new JSONB columns. Two new factories. One manager change. Zero changes
to bot retrieval code (already wired to use `self.reranker` and
`self.parent_searcher`).

```
[navigator.ai_bots row]
   ├── reranker_config        JSONB  ──┐
   └── parent_searcher_config JSONB ───┤
                                       │
                                       ▼
                          [BotManager.create_bot]
                                       │
                              ┌────────┴────────┐
                              ▼                 ▼
                    create_reranker()   create_parent_searcher(store=...)
                              │                 │
                              ▼                 ▼
                       AbstractReranker   AbstractParentSearcher
                              │                 │
                              └────────┬────────┘
                                       ▼
                          BaseBot(reranker=..., parent_searcher=...,
                                  expand_to_parent=...)
                                       │
                                       ▼
                  ask() / conversation() → already calls reranker
                  (abstract.py:1734) and _expand_to_parents (abstract.py:1771)
```

### Component Diagram

```
parrot/
├── rerankers/
│   ├── factory.py            ◄── NEW
│   ├── abstract.py
│   ├── local.py              (existing — LocalCrossEncoderReranker)
│   └── llm.py                (existing — LLMReranker)
├── stores/parents/
│   ├── factory.py            ◄── NEW
│   ├── abstract.py
│   └── in_table.py           (existing — InTableParentSearcher)
├── handlers/
│   ├── creation.sql          ◄── MODIFIED (ALTER TABLE + new columns in CREATE)
│   ├── models/bots.py        ◄── MODIFIED (BotModel new fields + to_bot_config)
│   └── bots.py               ◄── MODIFIED (POST/PUT validation, _provision_*)
├── manager/
│   └── manager.py            ◄── MODIFIED (factory invocations + kwarg forward)
└── bots/
    ├── abstract.py           (no change — kwargs already accepted)
    ├── base.py               ◄── VERIFY (kwargs passthrough to super().__init__)
    └── chatbot.py            ◄── VERIFY (kwargs passthrough)
```

### Integration Points

| Caller                                                | Callee                                  | Change |
|-------------------------------------------------------|-----------------------------------------|--------|
| `BotManager.create_bot` (`manager.py:340`)            | `create_reranker(reranker_config)`      | NEW    |
| `BotManager.create_bot` (`manager.py:340`)            | `create_parent_searcher(cfg, store)`    | NEW    |
| `BotManager.create_bot` → bot constructor             | passes `reranker=`, `parent_searcher=`, `expand_to_parent=` kwargs | NEW |
| `bot.configure()`                                      | already calls `configure_store()` then bot is ready | NO CHANGE |
| `BaseBot.ask` / `BaseBot.conversation`                | reads `self.reranker`, `self.parent_searcher`, `self.expand_to_parent` | NO CHANGE |

**Order of operations inside `BotManager.create_bot`** (critical):

1. Build `BaseBot(...)` with `reranker=` injected (factory called *before*
   construction; reranker has no dependency on the store).
2. `await bot.configure(app)` — this is where `configure_store()` runs and
   `self.store` becomes available.
3. Build `parent_searcher = create_parent_searcher(parent_cfg, store=bot.store)`
   *after* configure() because `InTableParentSearcher.__init__` requires the
   already-instantiated store (`stores/parents/in_table.py:83`).
4. Set `bot.parent_searcher = parent_searcher` and
   `bot.expand_to_parent = parent_cfg.get('expand_to_parent', False)`.

This is the only non-trivial sequencing change.

### Data Models

**`reranker_config` JSONB** — opt-in, default `{}`:

```jsonc
// type=local_cross_encoder
{
  "type": "local_cross_encoder",
  "model_name": "cross-encoder/ms-marco-MiniLM-L-12-v2",
  "device": "cpu",
  "rerank_oversample_factor": 4
}

// type=llm
{
  "type": "llm",
  "client_ref": "<llm-name-already-on-bot>",
  "rerank_oversample_factor": 4
}
```

**`parent_searcher_config` JSONB** — opt-in, default `{}`:

```jsonc
// type=in_table
{
  "type": "in_table",
  "expand_to_parent": true
}
```

**Empty dict** (`{}`) → factory returns `None` → bot retains today's behavior
(no reranker, no parent expansion).

### New Public Interfaces

```python
# parrot/rerankers/factory.py
def create_reranker(
    config: dict,
    *,
    bot_llm_client: Optional[AbstractClient] = None,
) -> Optional[AbstractReranker]:
    """Instantiate a reranker from a config dict.

    Args:
        config: Reranker config (typically loaded from
            ``navigator.ai_bots.reranker_config``). An empty dict means
            "no reranker" and returns ``None``.
        bot_llm_client: Reused for ``type=llm`` when ``client_ref="bot"``
            (avoids a second LLM client instantiation).

    Returns:
        The reranker instance, or ``None`` if config is empty.

    Raises:
        ConfigError: If ``config['type']`` is missing or unknown.
    """
    ...
```

```python
# parrot/stores/parents/factory.py
def create_parent_searcher(
    config: dict,
    *,
    store: AbstractStore,
) -> Optional[AbstractParentSearcher]:
    """Instantiate a parent searcher from a config dict.

    Args:
        config: Parent searcher config (from
            ``navigator.ai_bots.parent_searcher_config``). Empty dict
            returns ``None``.
        store: The bot's already-configured store; required for
            ``type=in_table`` because ``InTableParentSearcher`` queries the
            same table where chunks live.

    Returns:
        The parent searcher instance, or ``None`` if config is empty.

    Raises:
        ConfigError: If ``config['type']`` is missing or unknown, or
            ``store`` is None when required.
    """
    ...
```

Both factories also expose a registry hook for future types:

```python
# in each factory module
RERANKER_TYPES: dict[str, Callable[..., AbstractReranker]] = {
    "local_cross_encoder": _build_local_cross_encoder,
    "llm":                 _build_llm_reranker,
}
```

---

## 3. Module Breakdown

### Module 1: `parrot/rerankers/factory.py` (NEW)

- `create_reranker(config, *, bot_llm_client=None)` per signature above.
- Internal builders `_build_local_cross_encoder`, `_build_llm_reranker`.
- Empty-dict guard returns `None` early.
- Unknown `type` → `ConfigError` (imported from `parrot.exceptions`).
- Re-exports nothing — call from manager only.

### Module 2: `parrot/stores/parents/factory.py` (NEW)

- `create_parent_searcher(config, *, store)` per signature above.
- Internal builder `_build_in_table`.
- Empty-dict guard returns `None`.
- `store=None` when type requires it → `ConfigError`.
- Unknown type → `ConfigError`.

### Module 3: `parrot/handlers/creation.sql` (MODIFIED)

Two changes:

1. Add to `CREATE TABLE navigator.ai_bots`:
   ```sql
   reranker_config        JSONB DEFAULT '{}'::JSONB,
   parent_searcher_config JSONB DEFAULT '{}'::JSONB,
   ```

2. Append idempotent ALTERs (so existing deployments pick them up):
   ```sql
   ALTER TABLE navigator.ai_bots
       ADD COLUMN IF NOT EXISTS reranker_config        JSONB DEFAULT '{}'::JSONB;
   ALTER TABLE navigator.ai_bots
       ADD COLUMN IF NOT EXISTS parent_searcher_config JSONB DEFAULT '{}'::JSONB;

   COMMENT ON COLUMN navigator.ai_bots.reranker_config        IS 'FEAT-133 — reranker factory config (FEAT-126)';
   COMMENT ON COLUMN navigator.ai_bots.parent_searcher_config IS 'FEAT-133 — parent searcher factory config (FEAT-128)';
   ```

### Module 4: `parrot/handlers/models/bots.py` (MODIFIED)

In `BotModel` (line 208 area), next to `vector_store_config`:

```python
reranker_config: dict = Field(
    default_factory=dict,
    required=False,
    ui_help="The bot's reranker config (FEAT-126). See sdd/specs/bot-reranker-and-parent-searcher-config.spec.md.",
)
parent_searcher_config: dict = Field(
    default_factory=dict,
    required=False,
    ui_help="The bot's parent-searcher config (FEAT-128).",
)
```

Update `to_bot_config()` (line 304) to include both keys.

### Module 5: `parrot/manager/manager.py` (MODIFIED)

Around line 340-375, change the bot construction sequence per "Order of
operations" above. Pseudocode:

```python
from parrot.rerankers.factory import create_reranker
from parrot.stores.parents.factory import create_parent_searcher

# 1. Build reranker BEFORE construction (independent of store)
reranker = create_reranker(
    bot_model.reranker_config,
    bot_llm_client=None,  # filled post-construction if type=llm
)

bot_instance = bot_class(
    ...,
    vector_store_config=bot_model.vector_store_config,
    reranker=reranker,  # NEW
    # parent_searcher injected after configure() because it needs bot.store
    expand_to_parent=bool(
        bot_model.parent_searcher_config.get('expand_to_parent', False)
    ),  # NEW
    ...,
)

await bot_instance.configure(app)

# 2. Inject parent_searcher AFTER configure (depends on bot.store)
parent_searcher = create_parent_searcher(
    bot_model.parent_searcher_config,
    store=bot_instance.store,
)
if parent_searcher is not None:
    bot_instance.parent_searcher = parent_searcher
```

The `bot_llm_client` for `type=llm` reranker can be patched onto the
reranker post-construction if needed (e.g.,
`reranker.client = bot_instance.llm_client`); spec defers to implementation.

### Module 6: `parrot/handlers/bots.py` (MODIFIED)

POST/PUT/PATCH endpoints accept and persist the two new fields. Validation
strategy: **shallow** — only verify `isinstance(value, dict)`. Deep validation
(known types, required fields per type) happens at factory-call time. This
matches how `vector_store_config` is currently handled.

`_provision_vector_store` is **not** modified. Reranker and parent-searcher
have no DB-side provisioning.

### Module 7: `parrot/bots/base.py` and `parrot/bots/chatbot.py` (VERIFY ONLY)

Confirm both `BaseBot.__init__` and `Chatbot.__init__` end with
`super().__init__(**kwargs)` (or equivalent kwargs forwarding) so the new
constructor kwargs reach `AbstractBot.__init__` (`abstract.py:398, 407-408`).
If they don't, add the passthrough explicitly. No new logic.

### Module 8: Unit + integration tests

- `tests/rerankers/test_factory.py` — covers empty config, valid configs,
  unknown type → ConfigError, missing `type` → ConfigError.
- `tests/stores/parents/test_factory.py` — same matrix + `store=None` guard.
- `tests/manager/test_bot_loading_with_factories.py` — integration: a stub
  `BotModel` with both configs populated → loaded bot has non-None
  `agent.reranker` and `agent.parent_searcher`, and a fake retrieval call
  exercises both code paths.
- `tests/handlers/test_bot_endpoints_factories.py` — POST a bot with the
  new fields, GET it back, verify roundtrip.

---

## 4. Test Specification

### Unit Tests

```python
# tests/rerankers/test_factory.py
def test_empty_config_returns_none():
    assert create_reranker({}) is None

def test_local_cross_encoder_config_returns_instance():
    cfg = {"type": "local_cross_encoder", "model_name": "...",  "device": "cpu"}
    r = create_reranker(cfg)
    assert isinstance(r, LocalCrossEncoderReranker)

def test_unknown_type_raises_config_error():
    with pytest.raises(ConfigError, match="unknown reranker type"):
        create_reranker({"type": "magic"})

def test_missing_type_raises_config_error():
    with pytest.raises(ConfigError, match="missing 'type'"):
        create_reranker({"model_name": "..."})
```

```python
# tests/stores/parents/test_factory.py
def test_empty_config_returns_none(fake_store):
    assert create_parent_searcher({}, store=fake_store) is None

def test_in_table_config_returns_instance(fake_store):
    cfg = {"type": "in_table", "expand_to_parent": True}
    s = create_parent_searcher(cfg, store=fake_store)
    assert isinstance(s, InTableParentSearcher)

def test_in_table_requires_store():
    with pytest.raises(ConfigError, match="requires store"):
        create_parent_searcher({"type": "in_table"}, store=None)
```

### Integration Tests

```python
# tests/manager/test_bot_loading_with_factories.py
async def test_bot_loaded_with_reranker_and_parent_searcher(tmp_pg):
    """End-to-end: insert bot row with both configs, load via manager,
    verify the in-memory bot has reranker + parent_searcher and that
    BaseBot.ask() exercises both paths."""
    # Arrange: insert a row with reranker_config + parent_searcher_config + vector_store_config
    # Act: BotManager.load_bot('test_bot')
    # Assert: bot.reranker is not None, bot.parent_searcher is not None,
    #         bot.expand_to_parent is True
    # Act: await bot.ask("question") with patched store returning N candidates
    # Assert: reranker.rerank called once; _expand_to_parents called once
```

### Test Data / Fixtures

- `tests/fixtures/bot_rows/with_reranker.sql` — sample row with full configs.
- `tests/fixtures/bot_rows/empty_configs.sql` — sample row with `{}` for both
  (back-compat regression).

---

## 5. Acceptance Criteria

- [ ] **AC1** — `creation.sql` adds `reranker_config` and
  `parent_searcher_config` to the `CREATE TABLE` and includes idempotent
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for existing deployments. Both
  default to `'{}'::JSONB`. Existing rows are unaffected (no migration of
  values required).
- [ ] **AC2** — `BotModel` (`handlers/models/bots.py`) declares both fields
  with `default_factory=dict` and roundtrips them via `to_bot_config()`.
- [ ] **AC3** — `parrot.rerankers.factory.create_reranker` exists and:
  - Returns `None` for `{}`.
  - Builds `LocalCrossEncoderReranker` for
    `{"type": "local_cross_encoder", ...}`.
  - Builds `LLMReranker` for `{"type": "llm", ...}`.
  - Raises `ConfigError` for missing or unknown `type`.
- [ ] **AC4** — `parrot.stores.parents.factory.create_parent_searcher` exists
  and:
  - Returns `None` for `{}`.
  - Builds `InTableParentSearcher` for `{"type": "in_table", ...}` when a
    `store` is provided.
  - Raises `ConfigError` for missing or unknown `type`, or for a type that
    requires `store` when `store=None`.
- [ ] **AC5** — `BotManager.create_bot` invokes both factories and forwards
  the resulting instances + `expand_to_parent` to the bot constructor in the
  correct order (reranker before construction; parent_searcher after
  `configure()`).
- [ ] **AC6** — A test bot row with non-empty configs, loaded via
  `BotManager`, exposes `bot.reranker is not None`,
  `bot.parent_searcher is not None`, and `bot.expand_to_parent is True`.
- [ ] **AC7** — A test bot row with `{}` for both columns loads with
  `bot.reranker is None`, `bot.parent_searcher is None`,
  `bot.expand_to_parent is False` — identical to pre-FEAT-133 behavior.
- [ ] **AC8** — Loading a bot row with `reranker_config={"type": "magic"}`
  raises `ConfigError` at `BotManager.create_bot` time (fail-loud).
- [ ] **AC9** — Unit + integration tests pass: `pytest packages/ai-parrot/tests/rerankers/test_factory.py packages/ai-parrot/tests/stores/parents/test_factory.py packages/ai-parrot/tests/manager/test_bot_loading_with_factories.py -v`.
- [ ] **AC10** — `ruff check .` clean. `mypy parrot/rerankers/factory.py
  parrot/stores/parents/factory.py parrot/manager/manager.py` clean.

---

## 6. Codebase Contract

### Verified Imports (2026-04-28)

```python
from parrot.rerankers import LocalCrossEncoderReranker, LLMReranker
from parrot.rerankers.abstract import AbstractReranker
from parrot.stores.parents import InTableParentSearcher
from parrot.stores.parents.abstract import AbstractParentSearcher
from parrot.stores.abstract import AbstractStore
from parrot.exceptions import ConfigError
```

### Existing Class Signatures (re-verified 2026-04-28)

- `LocalCrossEncoderReranker.__init__(model_name: str, device: str = "cpu", ...)` — `parrot/rerankers/local.py:50`
- `LLMReranker.__init__(client: AbstractClient, ...)` — `parrot/rerankers/llm.py`
- `InTableParentSearcher.__init__(store: AbstractStore)` — `parrot/stores/parents/in_table.py:83`
- `AbstractBot.__init__(**kwargs)` reads `reranker`, `parent_searcher`, `expand_to_parent`, `rerank_oversample_factor` — `parrot/bots/abstract.py:397-408`
- `BotModel` is a `Model` (datamodel) — `parrot/handlers/models/bots.py:208`
- `BotManager.create_bot` flow — `parrot/manager/manager.py:340-379`

### Integration Points (existing, NOT modified)

- `AbstractBot.get_vector_context` — invokes `self.reranker.rerank(...)` at
  `abstract.py:1734-1751` and `self._expand_to_parents(...)` at
  `abstract.py:1769-1771`. Already wired; no change needed.
- `AbstractBot._build_vector_context` (router path) — same hooks at
  `abstract.py:2632-2665`.
- `interfaces/vector.py:_get_database_store` — pattern reused
  conceptually for the new factories (config dict → instance via type
  discriminator).

### Does NOT Exist (Anti-Hallucination)

- ❌ `parrot.rerankers.factory` — to be created in this feature.
- ❌ `parrot.stores.parents.factory` — to be created in this feature.
- ❌ Any column on `navigator.ai_bots` named `reranker_config` or
  `parent_searcher_config` — to be added.
- ❌ Any kwarg parsing for reranker/parent_searcher in
  `BotManager.create_bot` — to be added.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Mirror `interfaces/vector.py:_get_database_store` for the type-dispatch
  approach inside both factories.
- Mirror `parrot/rerankers/__init__.py:42-49` (lazy imports) so the factory
  doesn't pull torch/transformers when only `type=llm` is used or when both
  configs are empty.
- Reuse `parrot.exceptions.ConfigError` (already imported by `BotManager`).
- Type hints + Google-style docstrings throughout (project rule).

### Known Risks / Gotchas

- **R1 — Sequencing in `BotManager`.** `parent_searcher` requires `bot.store`,
  which only exists after `await bot.configure(app)`. Tests must cover the
  ordering explicitly.
- **R2 — Lazy imports.** `LocalCrossEncoderReranker` requires `transformers`
  + `torch`; the factory must NOT import it eagerly. Use the same lazy
  pattern as `parrot/rerankers/__init__.py`.
- **R3 — `expand_to_parent` location.** The flag lives inside
  `parent_searcher_config` (semantic coupling: irrelevant without a
  searcher). Document this clearly so admins don't try to set it elsewhere.
- **R4 — Back-compat for existing rows.** ALTER TABLE with `DEFAULT '{}'`
  + factory's empty-dict guard guarantee that pre-FEAT-133 rows behave
  identically. Add a regression test (AC7).
- **R5 — `LLMReranker` client reuse.** If `type=llm` and the bot already has
  an `llm_client`, reuse it (avoids double instantiation + double quota).
  Implementation detail; spec leaves the exact wiring to the implementer
  but flags it.

### External Dependencies

None new. Both `transformers`/`torch` (for local reranker) and the LLM
client deps are already pinned via FEAT-126.

---

## 8. Open Questions

1. **Q1** — Should `reranker_config` support a `rerank_oversample_factor`
   override at the bot level, or stay at the reranker level? The bot
   constructor already accepts `rerank_oversample_factor=` (default 4) at
   `abstract.py:399-401`. Recommended: keep inside `reranker_config` for
   data locality; the manager forwards it as a separate kwarg if present.

2. **Q2** — Should the manager log INFO when a bot is loaded with
   reranker/parent_searcher configured (operational visibility)? Recommended:
   yes — `self.logger.info("Bot %s: reranker=%s, parent_searcher=%s",
   name, type(reranker).__name__, type(searcher).__name__)`.

3. **Q3** — Migration of existing `att_concierge` and other production agents
   is explicitly out of scope per author. The migration script will run as a
   separate flow after this feature merges.

---

## Worktree Strategy

Standard SDD worktree off `dev`:

```bash
git checkout dev && git pull origin dev
git worktree add -b feat-132-bot-reranker-and-parent-searcher-config \
  .claude/worktrees/feat-132-bot-reranker-and-parent-searcher-config HEAD
cd .claude/worktrees/feat-132-bot-reranker-and-parent-searcher-config
```

Tasks decomposed via `/sdd-task sdd/specs/bot-reranker-and-parent-searcher-config.spec.md`.

Suggested task ordering:

1. DDL: ALTER TABLE script + creation.sql update.
2. `parrot/rerankers/factory.py` + unit tests.
3. `parrot/stores/parents/factory.py` + unit tests.
4. `BotModel` field additions + `to_bot_config` update.
5. `BotManager.create_bot` factory invocation + sequencing.
6. `BaseBot` / `Chatbot` kwargs passthrough verification.
7. POST/PUT handler validation (shallow).
8. Integration tests (full DB-loaded bot exercising FEAT-126 + FEAT-128).
9. Documentation updates (CHANGELOG, README snippet for the new JSONB shape).

---

## Revision History

| Date       | Author      | Change                                            |
|------------|-------------|---------------------------------------------------|
| 2026-04-28 | Jesus Lara  | Initial spec — approved.                          |
