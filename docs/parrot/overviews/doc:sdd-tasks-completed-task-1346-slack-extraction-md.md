---
type: Wiki Overview
title: 'TASK-1346: Slack Channel Extraction'
id: doc:sdd-tasks-completed-task-1346-slack-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move the Slack channel integration (9 Python files, ~288 KB) from
relates_to:
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.integrations.models
  rel: mentions
- concept: mod:parrot.integrations.parser
  rel: mentions
- concept: mod:parrot.integrations.slack
  rel: mentions
- concept: mod:parrot.integrations.slack.assistant
  rel: mentions
- concept: mod:parrot.integrations.slack.wrapper
  rel: mentions
---

# TASK-1346: Slack Channel Extraction

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1345
**Assigned-to**: unassigned

---

## Context

Move the Slack channel integration (9 Python files, ~288 KB) from
`parrot/integrations/slack/` to the satellite package. Slack has been
dormant since monorepo migration — low risk.

Implements **Spec Module 2**.

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/slack/` →
  `packages/ai-parrot-integrations/src/parrot/integrations/slack/`
  (byte-identical, no functional changes).
- Update any internal imports within slack files that reference other
  integrations modules (now resolved via satellite's own package).
- Move related tests:
  - `packages/ai-parrot/tests/integrations/slack/` → satellite tests
  - `packages/ai-parrot/tests/test_slack_integration.py` → satellite tests
- Remove the old directory from core.

**NOT in scope**: Changing Slack wrapper logic. Updating pyproject extras
(done in TASK-1354).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/slack/` | CREATE (move) | 9 Python files |
| `packages/ai-parrot-integrations/tests/integrations/slack/` | CREATE (move) | Slack tests |
| `packages/ai-parrot/src/parrot/integrations/slack/` | DELETE | Removed from core |
| `packages/ai-parrot/tests/integrations/slack/` | DELETE | Tests moved |
| `packages/ai-parrot/tests/test_slack_integration.py` | DELETE (move) | Test moved |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Consumers of slack (must keep working via PEP 420):
from parrot.integrations.slack.assistant import ...  # used in tests
from parrot.integrations import SlackAgentConfig     # via __init__.py lazy

# Internal to slack/:
# Check each file's imports — some may use relative imports to
# parrot.integrations.models or parrot.integrations.parser
```

### Does NOT Exist

- ~~`parrot.integrations.slack.SlackBot`~~ — verify actual class names by reading files
- ~~`parrot.integrations.slack.WebhookHandler`~~ — may or may not exist; verify

---

## Implementation Notes

### Key Constraints

- Use `git mv` for file moves to preserve history.
- Slack files may import from `..models` or `..parser` (relative) — these
  should now resolve within the satellite package (since common files were
  moved in TASK-1345).
- Verify `from parrot.integrations.slack.wrapper import SlackWrapper`
  works after the move (PEP 420).

---

## Acceptance Criteria

- [ ] All 9 slack Python files present in satellite
- [ ] `from parrot.integrations.slack.wrapper import SlackWrapper` works
- [ ] `from parrot.integrations import SlackAgentConfig` works
- [ ] Old `parrot/integrations/slack/` removed from core
- [ ] Moved tests pass: `pytest packages/ai-parrot-integrations/tests/`
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*
