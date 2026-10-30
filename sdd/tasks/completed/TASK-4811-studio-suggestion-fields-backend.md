# TASK-4811: Agent Studio backend — `BotModel` chip fields, DB migration, both kwarg whitelists

**Feature**: FEAT-752 — Follow-up Suggestion Chips
**Spec**: `sdd/specs/followup-suggestion-chips.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec rev 0.3, §3 Module 10 (backend half), G9, Q5. Database-stored agents are rebuilt through two hard-coded key
lists — `BotModel.to_bot_config()` (create/update via `handlers/bots.py`) and `BotManager._build_database_bot()`
(startup/reload). A field missing from either is silently dropped (today `use_kb` is: grep finds it in neither).
This task adds the five chip settings to `BotModel`, both lists, and an idempotent `navigator.ai_bots` migration.
Defaults equal TASK-4800's constructor defaults so a stored agent behaves like a code-built one.

---

## Scope

- `BotModel`: five fields (+ DDL lines in the docstring) and five `to_bot_config()` entries.
- `_build_database_bot`: five constructor kwargs.
- New migration `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql`.
- Tests in `packages/ai-parrot-server/tests/test_botmodel_suggestion_fields.py`.

**NOT in scope**: applying the migration to any database (operator step — document it, TASK-4805);
`BotWritePayload` / UI (TASK-4812); fixing the pre-existing `use_kb` drop (report it in the Completion Note only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bots.py` | MODIFY | Fields, DDL doc, `to_bot_config` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `_build_database_bot` kwargs |
| `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` | CREATE | Idempotent `ALTER TABLE` |
| `packages/ai-parrot-server/tests/test_botmodel_suggestion_fields.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.models.bots import BotModel   # re-export shim (handlers/models/bots.py:10) — same import as
                                                   # tests/test_botmodel_tooling_fields.py:7; source: parrot/models/bots.py:100
# bots.py already imports Field (datamodel) and Optional.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/bots.py
class BotModel(...):                                                                   # :100 ; Meta.strict = True (:442)
#   DDL docstring: `        use_conversation_history BOOLEAN DEFAULT TRUE,` :155 (1 occurrence)
#   field: `    use_conversation_history: bool = Field(` :297-299, its 2nd line
#          `        default=True, required=False, ui_help="Whether the bot’s conversation history is enabled or not."` :298 (1)
#   def to_bot_config(self) -> dict: ... `            "use_conversation_history": self.use_conversation_history,` :386 (1)
# packages/ai-parrot-server/src/parrot/manager/manager.py
async def _build_database_bot(self, bot_model: Any, app: web.Application) -> AbstractBot:   # :471
#   `            use_conversation_history=bot_model.use_conversation_history,` :570 (1 occurrence)
# Migration precedent: sdd/migrations/FEAT-593-ai-bots-tooling-columns.sql (BEGIN; ALTER ... ADD COLUMN IF NOT EXISTS;
#   COMMENT ON COLUMN; COMMIT; rollback comment)
# Test precedents: tests/test_botmodel_tooling_fields.py, tests/manager/test_build_database_bot_tools.py
```

### Does NOT Exist
- ~~`BotModel.enable_suggestions` & co.~~ / ~~the migration~~ — created here.
- ~~an automatic DB migration runner~~ — the SQL is applied by an operator.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/models/bots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/manager/manager.py", "action": "MODIFY"},
    {"path": "sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/test_botmodel_suggestion_fields.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/bots.py#BotModel",
    "sym:packages/ai-parrot/src/parrot/models/bots.py#BotModel.to_bot_config",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._build_database_bot"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Migration file — *why*: deploy order is migration first (`BotModel` reads fail on a missing column).
2. `BotModel` fields + DDL doc lines + `to_bot_config` entries — *why*: create/update path.
3. `_build_database_bot` kwargs — *why*: startup/reload path.
4. Tests; run Validation Commands.

### `sdd/migrations/FEAT-752-ai-bots-suggestion-columns.sql` (CREATE)
```sql
-- FEAT-752 (TASK-4811): follow-up suggestion chip settings on navigator.ai_bots (Agent Studio).
--
-- Apply BEFORE deploying the code: BotModel selects these columns and fails on a missing one.
-- Idempotent: safe to re-run on any environment. Defaults match AbstractBot's constructor defaults.

BEGIN;

ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS enable_suggestions   BOOLEAN DEFAULT FALSE;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS suggest_followups    BOOLEAN DEFAULT FALSE;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS suggestion_timeout_s REAL    DEFAULT 4.0;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS max_suggestions      INTEGER DEFAULT 6;
ALTER TABLE navigator.ai_bots ADD COLUMN IF NOT EXISTS suggestion_model     VARCHAR;

-- FILL IN: one COMMENT ON COLUMN per column ('FEAT-752 — ...'), same style as FEAT-593.

COMMIT;

-- Rollback:
--   ALTER TABLE navigator.ai_bots DROP COLUMN IF EXISTS suggestion_model;   -- FILL IN: the other four
```

### `bots.py` (MODIFY — DDL docstring)
```python
# occurrences: 1 (verified: grep -c '        use_conversation_history BOOLEAN DEFAULT TRUE,' bots.py)
# AFTER — insert below that line (bots.py:155)
        -- Follow-up suggestion chips (FEAT-752)
        enable_suggestions BOOLEAN DEFAULT FALSE,
        suggest_followups BOOLEAN DEFAULT FALSE,
        suggestion_timeout_s REAL DEFAULT 4.0,
        max_suggestions INTEGER DEFAULT 6,
        suggestion_model VARCHAR,
```

### `bots.py` (MODIFY — fields)
```python
# occurrences: 1 (verified: grep -c 'ui_help="Whether the bot’s conversation history is enabled or not."' bots.py)
# AFTER — insert below the `    )` that closes the use_conversation_history Field (bots.py:299)
    # Follow-up suggestion chips (FEAT-752) — defaults equal AbstractBot's constructor defaults.
    enable_suggestions: bool = Field(
        default=False, required=False, ui_help="Offer deterministic follow-up chips (view as table/chart, explain)."
    )
    suggest_followups: bool = Field(
        default=False, required=False, ui_help="Also ask the lightweight LLM for follow-up questions (one extra call)."
    )
    suggestion_timeout_s: float = Field(default=4.0, required=False, ui_help="Timeout in seconds for the LLM chip call.")
    max_suggestions: int = Field(default=6, required=False, ui_help="Maximum number of chips per answer.")
    suggestion_model: Optional[str] = Field(
        default=None, required=False, ui_help="Optional model for the chip call (defaults to the lightweight model)."
    )
```

### `bots.py` (MODIFY — to_bot_config)
```python
# occurrences: 1 (verified: grep -c '            "use_conversation_history": self.use_conversation_history,' bots.py)
# AFTER — insert below that line (bots.py:386)
            "enable_suggestions": self.enable_suggestions,
            "suggest_followups": self.suggest_followups,
            "suggestion_timeout_s": self.suggestion_timeout_s,
            "max_suggestions": self.max_suggestions,
            "suggestion_model": self.suggestion_model,
```

### `manager.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            use_conversation_history=bot_model.use_conversation_history,' manager.py)
# AFTER — insert below that line (manager.py:570)
            # Follow-up suggestion chips (FEAT-752)
            enable_suggestions=bot_model.enable_suggestions,
            suggest_followups=bot_model.suggest_followups,
            suggestion_timeout_s=bot_model.suggestion_timeout_s,
            max_suggestions=bot_model.max_suggestions,
            suggestion_model=bot_model.suggestion_model,
```
**Why**: bots built before TASK-4800 lands simply ignore unknown kwargs (`AbstractBot.__init__` takes `**kwargs`), so
this task has no code dependency on TASK-4800 — only the defaults must match it.

### FILL IN checklist
- [ ] Migration comments + rollback lines.
- [ ] Test bodies below.

---

## Acceptance Criteria

- [ ] `BotModel(name="x")` has the five defaults (`False`, `False`, `4.0`, `6`, `None`).
- [ ] `to_bot_config()` contains the five keys with the model's values.
- [ ] `_build_database_bot` passes the five kwargs (extend the harness of `test_build_database_bot_tools.py`).
- [ ] Migration file present and idempotent (`ADD COLUMN IF NOT EXISTS` only).
- [ ] Existing `test_bot_model_fields.py` / `test_build_database_bot_tools.py` / `test_botmodel_tooling_fields.py`
      stay green; `ruff check` clean on touched files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_botmodel_suggestion_fields.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_build_database_bot_tools.py -q`
- `pytest packages/ai-parrot/tests/handlers/test_bot_model_fields.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_botmodel_suggestion_fields.py
from parrot.handlers.models.bots import BotModel

FIELDS = {"enable_suggestions": False, "suggest_followups": False, "suggestion_timeout_s": 4.0,
          "max_suggestions": 6, "suggestion_model": None}


def test_defaults_match_constructor() -> None:
    model = BotModel(name="x")
    assert {k: getattr(model, k) for k in FIELDS} == FIELDS


def test_to_bot_config_forwards_fields() -> None:
    model = BotModel(name="x", enable_suggestions=True, suggest_followups=True, suggestion_timeout_s=2.5,
                     max_suggestions=3, suggestion_model="gemini-2.5-flash-lite")
    cfg = model.to_bot_config()
    assert cfg["suggest_followups"] is True and cfg["max_suggestions"] == 3
    assert cfg["suggestion_model"] == "gemini-2.5-flash-lite"


async def test_build_database_bot_passes_fields() -> None:
    # FILL IN: copy the harness of tests/manager/test_build_database_bot_tools.py; assert the captured constructor
    #          kwargs contain the five keys with the BotModel values
    ...
```

---

## Agent Instructions

Follow `sdd/templates/task.md` § Agent Instructions (worktree via `ensure_worktree --slug followup-suggestion-chips
--feature-id FEAT-752`, `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`, commit only listed files,
`scripts/sdd/close_task.sh TASK-4811 followup-suggestion-chips verified`). Do NOT run the migration against any
database.

---

## Completion Note

Delivered by the native sonnet seat, attempt 1; merged by hand (sequential fallback, MCP server disconnected).
Verified on the attempt branch: `test_botmodel_suggestion_fields.py` + `manager/test_build_database_bot_tools.py` + `test_botmodel_tooling_fields.py` = 12 passed; ruff clean; four task files only (a stray foreign `sdd/ledger/events.jsonl` line auto-staged by the pre-commit hook was already on the branch and produced no net change on merge).
Deviation (accepted): `_build_database_bot` reads the five new fields with `getattr(bot_model, "<f>", <default>)` because the existing test builds the bot model from a SimpleNamespace; defaults equal the `BotModel` defaults.
Not re-checked: the task's note about the pre-existing `use_kb` drop. The SQL migration was not run against any database.
No coder_record_review recorded (engine unavailable).
