# TASK-4125: Nullable `language` in both bot models, both DDLs, migration, and FEAT-621 gate rebaseline

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 6**. Design research **S2** found the brainstorm had named only
one of two persistence paths: `BotModel` **and** `UserBotModel` both default `language` to
`"en"`, and the *executed* `ai_bots` DDL is `creation.sql:64` (the one at `bots.py:89` sits
inside the `BotModel` docstring, lines 23-95). Both models already forward `language` into
bot kwargs (`bots.py:308` in `to_bot_config()`, `users_bots.py:203` in `to_bot_kwargs()`),
so once TASK-4119 lands the DB value reaches `AbstractBot` with no further wiring.

Left as `"en"`, every DB-backed bot would start forcing English output the moment the prompt
layer ships. The user decided (spec §8): drop the default to NULL everywhere, and migrate
existing `'en'` rows to NULL so deployed bots keep today's mirror-the-user behavior.

FEAT-621's release gate AC17 (`test_storage_gates.py::test_load_database_bots_untouched`)
pins the `ai_bots` DDL in **both** `bots.py` and `creation.sql` byte-for-byte to the
`origin/dev` merge-base. The user decided to rebaseline it. This task does that with an
explicit, named, auditable allowance for exactly this delta — not by loosening the gate.

**Exclusive (`parallel: false`)**: it modifies another feature's release gate and two DDL
files — shared state outside this feature's own modules. Review the gate edit by hand.

---

## Scope

- `BotModel.language` and `UserBotModel.language` → `Optional[str]`, default `None`.
- Drop `DEFAULT 'en'` from the `language` column in `bots.py` (docstring DDL), `creation.sql`, `users_bots_creation.sql`.
- Create `sdd/migrations/FEAT-638-bot-language-nullable.sql`.
- Rebaseline FEAT-621 AC17 with a named FEAT-638 allowance.
- Write model-default tests.

**NOT in scope**: running the migration against any database; the AgentStudio UI field
(`TabsGeneral.svelte:82-86` already maps an empty input to `null`); any other column.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` | MODIFY | Field default + docstring DDL |
| `packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py` | MODIFY | Field default |
| `packages/ai-parrot-server/src/parrot/handlers/creation.sql` | MODIFY | Drop `DEFAULT 'en'` |
| `packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql` | MODIFY | Drop `DEFAULT 'en'` |
| `sdd/migrations/FEAT-638-bot-language-nullable.sql` | CREATE | Drop defaults + NULL existing `'en'` rows |
| `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | MODIFY | Named FEAT-638 allowance in AC17 |
| `packages/ai-parrot-server/tests/test_bot_language_default.py` | CREATE | Model default tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.handlers.models.bots import BotModel              # verified: tests/test_botmodel_tooling_fields.py:8
from parrot.handlers.models.users_bots import UserBotModel    # verified: users_bots.py:26 (class UserBotModel(Model))
# test_storage_gates.py already imports `re` (line 8).
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/models/bots.py
class BotModel(Model):                                         # line 22; docstring DDL lines 23-95
    #   docstring line 89:  "        language VARCHAR(10) DEFAULT 'en',"
    language: str = Field(default="en", required=False, ui_help="The bot’s language.")   # line 245 (note U+2019 in bot’s)
    def to_bot_config(self) -> dict: ...                       # carries "language": self.language at line 308
# construction in tests: BotModel(name="x")                    # verified: test_botmodel_tooling_fields.py:14

# packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py
class UserBotModel(Model):                                     # line 26; required: user_id: int, name: str
    language: str = Field(required=False, default="en")        # line 107
    def to_bot_kwargs(self) -> dict: ...                       # line 165; carries "language": self.language at line 203

# packages/ai-parrot-server/src/parrot/handlers/creation.sql:6   CREATE TABLE IF NOT EXISTS navigator.ai_bots (
#   line 64:  "    language VARCHAR(10) DEFAULT 'en',"
# packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql:7   CREATE TABLE IF NOT EXISTS navigator.users_bots (
#   line 66:  "    language       VARCHAR(10) DEFAULT 'en',"

# packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py
def _ai_bots_ddl(source: str) -> str: ...                     # line 118 — regex-extracts the ai_bots CREATE TABLE
def test_load_database_bots_untouched(): ...                   # line 124 — AC17
    assert _ai_bots_ddl(new_bots) == _ai_bots_ddl(old_bots), "navigator.ai_bots DDL changed in handlers/models/bots.py"  # line 136
    assert (REPO / CREATION_SQL).read_text(encoding="utf-8") == old_sql, "handlers/creation.sql changed"              # line 137
```

### Does NOT Exist
- ~~alembic / an automatic migration runner~~ — migrations are hand-written SQL in `sdd/migrations/` (precedent: `FEAT-593-ai-bots-tooling-columns.sql`); this task only writes the file.
- ~~Executed DDL in `bots.py`~~ — the `bots.py:89` line is docstring documentation of production DDL; `creation.sql` is what runs.
- ~~A users_bots gate in `test_storage_gates.py`~~ — AC17 covers `ai_bots` (`bots.py` + `creation.sql`) only.
- ~~Skipping or deleting AC17~~ — forbidden; add a named allowance for exactly this delta.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-server/src/parrot/handlers/models/bots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/creation.sql", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql", "action": "MODIFY"},
    {"path": "sdd/migrations/FEAT-638-bot-language-nullable.sql", "action": "CREATE"},
    {"path": "packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/tests/test_bot_language_default.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/bots.py#BotModel",
    "sym:packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py#UserBotModel",
    "sym:packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py#test_load_database_bots_untouched"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The row migration is lossy by design.** A row deliberately set to `'en'` is indistinguishable
  from one that took the old default, so both become NULL. That is the decided trade-off; the
  migration header says so, and operators who want English artifacts set `'en'` again afterwards.
- **Rollout step (record it in the Completion Note):** the existing Spanish standup deployment
  must set `language = 'es'` explicitly — after this feature, unset renders English for
  Python-authored messages (TASK-4124).
- The AC17 allowance rewrites only the **merge-base** side, and only the `language` column line.
  Once FEAT-638 is on `dev` the merge-base already has the new DDL and the allowance becomes a
  no-op; it can be removed in a later cleanup.

---

## Implementation Blueprint

### Steps (in order)
1. Change both model fields — *why*: model defaults decide what a new bot row carries.
2. Change the three DDL lines — *why*: fresh tables must match the models.
3. Write the migration — *why*: existing rows hold `'en'` and would otherwise force English.
4. Add the named AC17 allowance — *why*: the user chose to rebaseline, not to skip.
5. Write the model tests.

### `packages/ai-parrot-server/src/parrot/handlers/models/bots.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    language: str = Field(default="en", required=False, ui_help="The bot’s language.")' bots.py)
# REPLACE line 245 with (keep the U+2019 apostrophe in "bot’s"):
    language: Optional[str] = Field(default=None, required=False, ui_help="The bot’s language.")

# occurrences: 1 (verified: grep -cF "        language VARCHAR(10) DEFAULT 'en'," bots.py)
# REPLACE docstring line 89 with:
        language VARCHAR(10),
```
`Optional` is already imported (verified: `bots.py:5` — `from typing import List, Optional`).

### `packages/ai-parrot-server/src/parrot/handlers/models/users_bots.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    language: str = Field(required=False, default="en")' users_bots.py)
# REPLACE line 107 with:
    language: Optional[str] = Field(required=False, default=None)
```
`Optional` is already imported (verified: `users_bots.py:16` — `from typing import Any, List, Optional`).

### `packages/ai-parrot-server/src/parrot/handlers/creation.sql` (MODIFY)
```sql
-- occurrences: 1 (verified: grep -cF "    language VARCHAR(10) DEFAULT 'en'," creation.sql)
-- REPLACE line 64 with:
    language VARCHAR(10),
```

### `packages/ai-parrot-server/src/parrot/handlers/models/users_bots_creation.sql` (MODIFY)
```sql
-- occurrences: 1 (verified: grep -cF "    language       VARCHAR(10) DEFAULT 'en'," users_bots_creation.sql)
-- REPLACE line 66 with (keep the column alignment):
    language       VARCHAR(10),
```

### `sdd/migrations/FEAT-638-bot-language-nullable.sql` (CREATE)
```sql
-- FEAT-638: bot-level output language — `language` becomes nullable with no default.
--
-- NULL means "mirror the user" (today's behavior for LLM-authored text). Until now the
-- column defaulted to 'en' and the value was inert (it never reached a prompt), so an
-- existing 'en' is almost always the untouched default. It is reset to NULL.
--
-- LOSSY BY DESIGN: a row deliberately set to 'en' cannot be told apart from the default
-- and is reset too. Deployments that want English artifacts set language = 'en' again
-- after running this; the Spanish standup deployment sets language = 'es'.
BEGIN;

ALTER TABLE navigator.ai_bots ALTER COLUMN language DROP DEFAULT;
UPDATE navigator.ai_bots SET language = NULL WHERE language = 'en';

ALTER TABLE navigator.users_bots ALTER COLUMN language DROP DEFAULT;
UPDATE navigator.users_bots SET language = NULL WHERE language = 'en';

COMMIT;
```

### `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF 'def _ai_bots_ddl(source: str) -> str:' test_storage_gates.py)
# BEFORE — insert above `def _ai_bots_ddl(source: str) -> str:` (verified: test_storage_gates.py:118)
# FEAT-638 sanctioned delta: the `language` column drops its DEFAULT 'en'. Applied to the
# merge-base copy only, so AC17 still catches any OTHER change to the ai_bots DDL.
_FEAT638_LANGUAGE_DEFAULT = re.compile(r"(language\s+VARCHAR\(10\))\s+DEFAULT\s+'en',")


def _with_sanctioned_deltas(source: str) -> str:
    """Apply sanctioned DDL deltas to a merge-base copy before AC17 compares it."""
    return _FEAT638_LANGUAGE_DEFAULT.sub(r"\1,", source)


# occurrences: 1 each (lines 136 and 137). REPLACE them with:
    assert _ai_bots_ddl(new_bots) == _ai_bots_ddl(_with_sanctioned_deltas(old_bots)), (
        "navigator.ai_bots DDL changed in handlers/models/bots.py"
    )
    assert (REPO / CREATION_SQL).read_text(encoding="utf-8") == _with_sanctioned_deltas(old_sql), (
        "handlers/creation.sql changed"
    )
```
**Why**: the allowance is named after the feature that sanctioned it and touches only the one
column line, so the gate keeps its full strength for every other change. **Human review required.**

### `packages/ai-parrot-server/tests/test_bot_language_default.py` (CREATE)
```python
"""FEAT-638: bot models default `language` to None (TASK-4125)."""
from parrot.handlers.models.bots import BotModel
from parrot.handlers.models.users_bots import UserBotModel


def test_bot_model_language_defaults_none():
    assert BotModel(name="x").language is None


def test_user_bot_model_language_defaults_none():
    assert UserBotModel(user_id=1, name="x").language is None


def test_explicit_language_is_kept():
    assert BotModel(name="x", language="es").language == "es"
    assert UserBotModel(user_id=1, name="x", language="es").language == "es"


def test_bot_config_carries_none_language():
    # FILL IN: assert BotModel(name="x").to_bot_config()["language"] is None; for UserBotModel,
    #   call to_bot_kwargs() only if it needs no further required fields, else skip that half
    #   with a one-line comment — bounded by spec AC "BotModel/UserBotModel default to None".
    pass


def test_creation_sql_has_no_language_default():
    # FILL IN: read creation.sql and users_bots_creation.sql (paths relative to this file) and
    #   assert no line matching r"language\s+VARCHAR\(10\)\s+DEFAULT" remains — bounded by spec AC.
    pass
```

### FILL IN checklist
- [ ] `test_bot_config_carries_none_language` — `to_bot_config()` (+ `to_bot_kwargs()` if constructible)
- [ ] `test_creation_sql_has_no_language_default` — both SQL files

---

## Acceptance Criteria

- [ ] `BotModel().language` and `UserBotModel().language` are `None` by default; explicit values are kept.
- [ ] No `language … DEFAULT 'en'` remains in `bots.py`, `creation.sql` or `users_bots_creation.sql`.
- [ ] `sdd/migrations/FEAT-638-bot-language-nullable.sql` drops both defaults and NULLs existing `'en'` rows in both tables, inside one transaction, with the lossy-by-design note.
- [ ] FEAT-621 AC17 passes via a named FEAT-638 allowance that rewrites only the merge-base `language` line.
- [ ] Completion Note records the rollout step (Spanish deployment sets `language = 'es'`).
- [ ] `ruff check` clean on both model files and the test files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/test_bot_language_default.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py -q`
- `pytest packages/ai-parrot-server/tests/test_botmodel_tooling_fields.py -q`

---

## Test Specification

See the `test_bot_language_default.py` blueprint block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug jiraspecialist-agent-multilang --feature-id FEAT-638`)
2. **Read the spec** at `sdd/specs/jiraspecialist-agent-multilang.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/jiraspecialist-agent-multilang.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor check; a count of `0` means the anchor is gone — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/jiraspecialist-agent-multilang.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (add `packages/ai-parrot-server/src` for server files)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> jiraspecialist-agent-multilang verified`
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
