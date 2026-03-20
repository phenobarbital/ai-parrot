# TASK-023: Extend SlackAgentConfig Model

**Feature**: Slack Wrapper Integration Enhancements
**Spec**: `sdd/specs/slack-wrapper-integration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> This task extends the `SlackAgentConfig` dataclass with new fields required by all other modules in this feature.
> Reference: Spec Section 2 (Data Models) and Section 3 (Module 9).

The existing config only has basic fields. We need to add:
- `app_token` for Socket Mode
- `connection_mode` to switch between webhook/socket
- `enable_assistant` for Agents & AI Apps
- `suggested_prompts` for assistant prompts
- `max_concurrent_requests` for concurrency limiting

---

## Scope

- Extend `SlackAgentConfig` dataclass with new fields
- Add validation in `__post_init__` for Socket Mode requirements
- Update `from_dict` factory method to parse new fields
- Add docstrings for all new fields

**NOT in scope**:
- Implementing Socket Mode handler (TASK-027)
- Implementing Assistant handler (TASK-029)
- Changes to wrapper.py (separate tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/slack/models.py` | MODIFY | Add new fields to SlackAgentConfig |
| `tests/unit/test_slack_models.py` | CREATE | Unit tests for config validation |

---

## Implementation Notes

### Pattern to Follow
```python
@dataclass
class SlackAgentConfig:
    # ... existing fields ...

    # New fields
    app_token: Optional[str] = None
    connection_mode: str = "webhook"  # "webhook" | "socket"
    enable_assistant: bool = False
    suggested_prompts: Optional[list[Dict[str, str]]] = None
    max_concurrent_requests: int = 10

    def __post_init__(self):
        # ... existing logic ...
        if not self.app_token:
            self.app_token = config.get(f"{self.name.upper()}_SLACK_APP_TOKEN")
        if self.connection_mode == "socket" and not self.app_token:
            raise ValueError(
                f"Socket Mode requires app-level token (xapp-...) for '{self.name}'."
            )
```

### Key Constraints
- Maintain backward compatibility — all new fields must have defaults
- Use `Optional` typing for nullable fields
- Environment variable fallback pattern must match existing `bot_token` pattern

### References in Codebase
- `parrot/integrations/slack/models.py` — current implementation
- `parrot/integrations/telegram/models.py` — similar config pattern

---

## Acceptance Criteria

- [x] `SlackAgentConfig` has all 5 new fields with proper types
- [x] `connection_mode="socket"` without `app_token` raises `ValueError`
- [x] `from_dict()` parses all new fields correctly
- [x] Existing configs without new fields still work (backward compatible)
- [x] All tests pass: `pytest tests/unit/test_slack_models.py -v`
- [x] No linting errors: `ruff check parrot/integrations/slack/models.py`

---

## Test Specification

```python
# tests/unit/test_slack_models.py
import pytest
from parrot.integrations.slack.models import SlackAgentConfig


class TestSlackAgentConfig:
    def test_default_values(self):
        """New fields have sensible defaults."""
        config = SlackAgentConfig(name="test", chatbot_id="bot")
        assert config.connection_mode == "webhook"
        assert config.enable_assistant is False
        assert config.max_concurrent_requests == 10
        assert config.app_token is None
        assert config.suggested_prompts is None

    def test_socket_mode_requires_app_token(self):
        """Socket mode raises error without app_token."""
        with pytest.raises(ValueError, match="Socket Mode requires"):
            SlackAgentConfig(
                name="test", chatbot_id="bot",
                connection_mode="socket", app_token=None
            )

    def test_socket_mode_with_app_token(self):
        """Socket mode works with app_token."""
        config = SlackAgentConfig(
            name="test", chatbot_id="bot",
            connection_mode="socket", app_token="xapp-123"
        )
        assert config.connection_mode == "socket"

    def test_from_dict_parses_new_fields(self):
        """from_dict correctly parses all new fields."""
        data = {
            "chatbot_id": "bot",
            "connection_mode": "socket",
            "app_token": "xapp-123",
            "enable_assistant": True,
            "suggested_prompts": [{"title": "Help", "message": "Help me"}],
            "max_concurrent_requests": 5,
        }
        config = SlackAgentConfig.from_dict("test", data)
        assert config.connection_mode == "socket"
        assert config.enable_assistant is True
        assert len(config.suggested_prompts) == 1

    def test_backward_compatibility(self):
        """Old configs without new fields still work."""
        data = {"chatbot_id": "bot"}
        config = SlackAgentConfig.from_dict("test", data)
        assert config.connection_mode == "webhook"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-023-slack-config-model.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-24
**Notes**: Extended SlackAgentConfig with 5 new fields:
- `app_token` - Slack app-level token for Socket Mode
- `connection_mode` - "webhook" or "socket" mode selector
- `enable_assistant` - Enable Slack Agents & AI Apps feature
- `suggested_prompts` - List of prompt dicts for assistant
- `max_concurrent_requests` - Concurrency limit (default: 10)

Added validation that Socket Mode requires app_token. All tokens now support
environment variable fallback. Created 11 unit tests covering all new functionality
and backward compatibility.

**Deviations from spec**: none
