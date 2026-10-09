# TASK-4186: Integration config fields — `knowledge_upload` block on Telegram, MS Teams and Slack

**Feature**: FEAT-647 — Chat-driven document upload into Bookstore / LLM Wiki
**Spec**: `sdd/specs/teams-telegram-uploader-bookstore.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4182
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7. Each chat integration reads its per-bot configuration from a
`@dataclass` built by `from_dict(name, data)`. The upload feature is opt-in
and configured through one `knowledge_upload:` block per bot (spec §2 Data
Models, §7 Deployment). This task adds that field to the three integration
configs so the platform adapters (TASK-4187 Telegram, TASK-4188 Teams,
TASK-4189 Slack) can read `self.config.knowledge_upload`.

`KnowledgeUploadConfig` itself is created by TASK-4182 in
`parrot/integrations/knowledge_upload/models.py`.

---

## Scope

- Add `knowledge_upload: KnowledgeUploadConfig = field(default_factory=KnowledgeUploadConfig)` to
  `TelegramAgentConfig`, `MSTeamsAgentConfig` and `SlackAgentConfig`.
- Parse it in each `from_dict` with
  `KnowledgeUploadConfig.model_validate(data.get("knowledge_upload") or {})`.
- Write tests proving: absent block → disabled defaults (`enabled=False`,
  `max_size_mb=10`, empty allow-lists); present block → parsed values; invalid
  values (e.g. `max_size_mb: 0`) → `pydantic.ValidationError`.

**NOT in scope**: registering commands, building the service, changing
`max_document_size_mb` semantics (Telegram keeps it for the default document
path — spec §3 M7), YAML loaders outside `from_dict`, any `navigator-agent-server` file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` | MODIFY | field + `from_dict` parsing |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | field + `from_dict` parsing |
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` | MODIFY | field + `from_dict` parsing |
| `packages/ai-parrot-integrations/tests/knowledge_upload/test_config_fields.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from dataclasses import dataclass, field          # telegram/models.py:5, msteams/models.py:5, slack/models.py:3
from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig   # created by TASK-4182 (spec §2 Data Models)
from parrot.integrations.telegram.models import TelegramAgentConfig             # telegram/models.py:39
from parrot.integrations.msteams.models import MSTeamsAgentConfig               # msteams/models.py:15
from parrot.integrations.slack.models import SlackAgentConfig                   # slack/models.py:29
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py
@dataclass
class TelegramAgentConfig:                                           # :39
    max_document_size_mb: int = 20                                   # :128
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':   # :231
    # inside return cls(...):  max_document_size_mb=int(data.get('max_document_size_mb', 20)),   # :296
# Test precedent: TelegramAgentConfig.from_dict("bot", {"chatbot_id": "x"})  (tests/test_telegram_voice_reply.py:162)

# packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py
@dataclass
class MSTeamsAgentConfig:                                            # :15
    allowed_user_ids: Optional[List[str]] = None                     # :46
    def __post_init__(self): ...                                     # :65
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSTeamsAgentConfig":   # :130
    # inside return cls(...):  allowed_user_ids=data.get("allowed_user_ids"),       # :155

# packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py
@dataclass
class SlackAgentConfig:                                              # :29
    allowed_user_ids: Optional[List[str]] = None                     # :60
    def __post_init__(self): ...                                     # :80 (raises only for socket mode without app token)
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "SlackAgentConfig":     # :108
    # inside return cls(...):  allowed_user_ids=data.get("allowed_user_ids"),       # :126
```

`KnowledgeUploadConfig` (TASK-4182, spec §2): Pydantic v2 model, fields
`enabled=False`, `allowed_usernames=[]`, `allowed_groups=[]`,
`max_size_mb=Field(10, gt=0)`, `allowed_extensions`, `max_concurrent_jobs`,
`slack_pending_window_s`, `bookstore: BookstoreTargetConfig | None`,
`wiki: WikiTargetConfig | None`.

### Does NOT Exist
- ~~`TelegramAgentConfig.knowledge_upload`~~ / ~~`MSTeamsAgentConfig.knowledge_upload`~~ / ~~`SlackAgentConfig.knowledge_upload`~~ — this task adds them
- ~~A Pydantic base for the integration configs~~ — they are `@dataclass`; do not convert them
- ~~`KnowledgeUploadConfig.from_dict`~~ — use `KnowledgeUploadConfig.model_validate(...)`
- ~~A shared integration config loader that already parses `knowledge_upload`~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-integrations/tests/knowledge_upload/test_config_fields.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py#TelegramAgentConfig.from_dict",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py#MSTeamsAgentConfig.from_dict",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py#SlackAgentConfig",
    "sym:packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py#SlackAgentConfig.from_dict"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Import cycle check**: `knowledge_upload/models.py` imports only `pydantic`
  and stdlib (TASK-4182 contract). Importing it from the three `models.py`
  files must not import any `telegram`/`msteams`/`slack` module. Verify with
  `python -c "import parrot.integrations.telegram.models, parrot.integrations.msteams.models, parrot.integrations.slack.models"`.
  If `knowledge_upload/__init__.py` pulls heavy modules (service, asyncdb),
  report it in the Completion Note — do NOT edit TASK-4182's files.
- The new field has a default, so dataclass field ordering stays valid
  (every following field already has a default).
- Do not touch `max_document_size_mb`.

---

## Implementation Blueprint

### Steps (in order)
1. Re-run the four `grep -c` checks below — *why*: anchors were verified at spec time and may have moved.
2. Add the module-level import to each of the three `models.py` — *why*: the dataclass field type must be importable at class-definition time.
3. Add the field after the anchor attribute and the `from_dict` kwarg after the anchor kwarg — *why*: keeps related settings grouped and the diff minimal.
4. Write the tests, run validation — *why*: AC1–AC3.

### `packages/ai-parrot-integrations/src/parrot/integrations/telegram/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from navconfig import config' telegram/models.py)
# AFTER — insert below `from navconfig import config` (verified: telegram/models.py:7)
from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig

# occurrences: 1 (verified: grep -c '    max_document_size_mb: int = 20' telegram/models.py)
# AFTER — insert below `    max_document_size_mb: int = 20` (verified: telegram/models.py:128)
    # Chat-driven knowledge upload (FEAT-647) — opt-in, disabled by default.
    knowledge_upload: KnowledgeUploadConfig = field(default_factory=KnowledgeUploadConfig)

# occurrences: 1 (verified: grep -c "            max_document_size_mb=int(data.get('max_document_size_mb', 20))," telegram/models.py)
# AFTER — insert below that line (verified: telegram/models.py:296)
            knowledge_upload=KnowledgeUploadConfig.model_validate(data.get('knowledge_upload') or {}),
```
**Why**: spec §3 M7 fixes the field name, type and parsing expression; `or {}` turns a YAML `knowledge_upload:` with no body (`None`) into the disabled default.

### `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from navconfig import config' msteams/models.py)
# AFTER — insert below `from navconfig import config` (verified: msteams/models.py:7)
from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig

# occurrences: 1 (verified: grep -c '    allowed_user_ids: Optional[List[str]] = None' msteams/models.py)
# AFTER — insert below that line (verified: msteams/models.py:46)
    # Chat-driven knowledge upload (FEAT-647) — opt-in, disabled by default.
    knowledge_upload: KnowledgeUploadConfig = field(default_factory=KnowledgeUploadConfig)

# occurrences: 1 (verified: grep -c '            allowed_user_ids=data.get("allowed_user_ids"),' msteams/models.py)
# AFTER — insert below that line (verified: msteams/models.py:155)
            knowledge_upload=KnowledgeUploadConfig.model_validate(data.get("knowledge_upload") or {}),
```
**Why**: same contract as Telegram; `__post_init__` (:65) does not need changes.

### `packages/ai-parrot-integrations/src/parrot/integrations/slack/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from navconfig import config' slack/models.py)
# AFTER — insert below `from navconfig import config` (verified: slack/models.py:5)
from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig

# occurrences: 1 (verified: grep -c '    allowed_user_ids: Optional[List[str]] = None' slack/models.py)
# AFTER — insert below that line (verified: slack/models.py:60)
    # Chat-driven knowledge upload (FEAT-647) — opt-in, disabled by default.
    knowledge_upload: KnowledgeUploadConfig = field(default_factory=KnowledgeUploadConfig)

# occurrences: 1 (verified: grep -c '            allowed_user_ids=data.get("allowed_user_ids"),' slack/models.py)
# AFTER — insert below that line (verified: slack/models.py:126)
            knowledge_upload=KnowledgeUploadConfig.model_validate(data.get("knowledge_upload") or {}),
```
**Why**: Slack uses the field for `slack_pending_window_s` too (TASK-4189).

### `packages/ai-parrot-integrations/tests/knowledge_upload/test_config_fields.py` (CREATE)
```python
"""FEAT-647 TASK-4186 — knowledge_upload block on the integration configs."""
import pytest
from pydantic import ValidationError

from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.slack.models import SlackAgentConfig
from parrot.integrations.telegram.models import TelegramAgentConfig

CONFIGS = [TelegramAgentConfig, MSTeamsAgentConfig, SlackAgentConfig]

BLOCK = {
    "enabled": True,
    "allowed_usernames": ["jlara"],
    "allowed_groups": ["odoo_curators"],
    "max_size_mb": 5,
    "bookstore": {"library_dir": "/tmp/library"},
}


@pytest.mark.parametrize("cls", CONFIGS)
def test_absent_block_is_disabled(cls):
    cfg = cls.from_dict("bot", {"chatbot_id": "x"})
    assert isinstance(cfg.knowledge_upload, KnowledgeUploadConfig)
    assert cfg.knowledge_upload.enabled is False
    assert cfg.knowledge_upload.max_size_mb == 10
    # FILL IN: assert empty allow-lists and bookstore/wiki None — bounded by AC2


@pytest.mark.parametrize("cls", CONFIGS)
def test_block_is_parsed(cls):
    cfg = cls.from_dict("bot", {"chatbot_id": "x", "knowledge_upload": BLOCK})
    # FILL IN: assert enabled, lists, max_size_mb=5, bookstore.library_dir — bounded by AC1


@pytest.mark.parametrize("cls", CONFIGS)
def test_empty_yaml_block_means_defaults(cls):
    cfg = cls.from_dict("bot", {"chatbot_id": "x", "knowledge_upload": None})
    assert cfg.knowledge_upload.enabled is False


@pytest.mark.parametrize("cls", CONFIGS)
def test_invalid_block_raises(cls):
    with pytest.raises(ValidationError):
        cls.from_dict("bot", {"chatbot_id": "x", "knowledge_upload": {"max_size_mb": 0}})
```
**Why**: parametrized over the three classes so a missed `from_dict` edit fails loudly. If `SlackAgentConfig`/`MSTeamsAgentConfig` need extra keys to construct, add the minimum in a per-class dict — do not mock `from_dict`.

### FILL IN checklist
- [ ] `test_absent_block_is_disabled` — remaining default asserts; bounded by AC2
- [ ] `test_block_is_parsed` — asserts for every key in `BLOCK`; bounded by AC1

---

## Acceptance Criteria

- [ ] AC1 — `from_dict` on all three configs parses a `knowledge_upload` block into `KnowledgeUploadConfig`.
- [ ] AC2 — Absent or `null` block yields `KnowledgeUploadConfig()` defaults (`enabled=False`, `max_size_mb=10`).
- [ ] AC3 — Invalid values raise `pydantic.ValidationError` from `from_dict`.
- [ ] AC4 — Importing the three `models.py` modules raises no circular import.
- [ ] AC5 — Existing config tests (`tests/test_telegram_voice_reply.py`) still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot-integrations/tests/knowledge_upload/test_config_fields.py -q`
- `pytest packages/ai-parrot-integrations/tests/test_telegram_voice_reply.py -q`

---

## Test Specification

See the CREATE block above (`test_config_fields.py`): four parametrized tests
× three config classes. No network, no navconfig secrets required (bot tokens
fall back to env lookups that may be empty).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug teams-telegram-uploader-bookstore --feature-id FEAT-647`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-4182 must be `"done"` in
   `sdd/tasks/index/teams-telegram-uploader-bookstore.json`
4. **Verify the Codebase Contract** before writing any code; re-run every `grep -c`
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`
7. **Verify** with the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src` inside the worktree)
8. **Commit the code** — stage only the files listed above
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4186 teams-telegram-uploader-bookstore verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
