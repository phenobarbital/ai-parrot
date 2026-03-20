# TASK-026: FilesystemTransportConfig Pydantic Model

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This is the foundational task for the FilesystemTransport feature. All other modules depend on this config model for their settings. The config also supports loading from `parrot.yaml` transport section (per owner decision).

Implements **Module 1** from the spec.

---

## Scope

- Implement `FilesystemTransportConfig` Pydantic v2 `BaseModel` with all transport settings
- Include `field_validator` for `root_dir` path resolution (resolve to absolute path)
- Support loading from `parrot.yaml` via a `from_yaml()` classmethod or compatible with existing YAML config patterns
- Write unit tests for config defaults and path resolution

**NOT in scope**: Other modules, transport logic, hook config (that's TASK-034)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/__init__.py` | CREATE | Empty init for transport package |
| `parrot/transport/filesystem/__init__.py` | CREATE | Minimal init (just config export for now) |
| `parrot/transport/filesystem/config.py` | CREATE | `FilesystemTransportConfig` Pydantic model |
| `tests/transport/__init__.py` | CREATE | Empty init for test package |
| `tests/transport/filesystem/__init__.py` | CREATE | Empty init |
| `tests/transport/filesystem/test_config.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
```python
from __future__ import annotations
from pathlib import Path
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator

class FilesystemTransportConfig(BaseModel):
    root_dir: Path = Field(default=Path(".parrot"), description="...")
    presence_interval: float = Field(default=10.0, description="...")
    # ... all fields from spec section 6.1

    @field_validator("root_dir", mode="before")
    @classmethod
    def resolve_path(cls, v):
        return Path(v).resolve()
```

### Key Constraints
- Use Pydantic v2 `BaseModel` (not v1)
- All fields must have `Field()` with `description`
- `root_dir` must resolve to absolute path via validator
- No external dependencies beyond pydantic

### References in Codebase
- `parrot/autonomous/hooks/models.py` — existing Pydantic config patterns (e.g., `WhatsAppRedisHookConfig`)
- Proposal spec Section 6.1 for full field list

---

## Acceptance Criteria

- [ ] `FilesystemTransportConfig()` creates valid config with all defaults
- [ ] `root_dir` is resolved to absolute path
- [ ] All fields match the spec (presence_interval, stale_threshold, scope_to_cwd, poll_interval, use_inotify, message_ttl, keep_processed, feed_retention, default_channels, reservation_timeout, routes)
- [ ] Tests pass: `pytest tests/transport/filesystem/test_config.py -v`
- [ ] Import works: `from parrot.transport.filesystem.config import FilesystemTransportConfig`

---

## Test Specification

```python
# tests/transport/filesystem/test_config.py
import pytest
from pathlib import Path
from parrot.transport.filesystem.config import FilesystemTransportConfig


class TestFilesystemTransportConfig:
    def test_defaults(self):
        """All default values are set correctly."""
        config = FilesystemTransportConfig()
        assert config.presence_interval == 10.0
        assert config.stale_threshold == 60.0
        assert config.poll_interval == 0.5
        assert config.use_inotify is True
        assert config.message_ttl == 3600.0
        assert config.keep_processed is True
        assert config.feed_retention == 500
        assert config.default_channels == ["general"]
        assert config.reservation_timeout == 300.0
        assert config.routes is None

    def test_path_resolution(self, tmp_path):
        """root_dir is resolved to absolute path."""
        config = FilesystemTransportConfig(root_dir="relative/path")
        assert config.root_dir.is_absolute()

    def test_custom_values(self, tmp_path):
        """Custom values override defaults."""
        config = FilesystemTransportConfig(
            root_dir=tmp_path,
            poll_interval=1.0,
            use_inotify=False,
            feed_retention=100,
        )
        assert config.root_dir == tmp_path
        assert config.poll_interval == 1.0
        assert config.use_inotify is False
        assert config.feed_retention == 100
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — this task has none
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-026-filesystem-transport-config.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `FilesystemTransportConfig` with all 12 fields from spec Section 6.1. Used `model_validator(mode="after")` instead of `field_validator` to ensure `root_dir` is resolved to absolute path even when using the default value. All 7 unit tests pass.

**Deviations from spec**: Used `model_validator` instead of `field_validator` for path resolution — `field_validator` with `mode="before"` does not run on Pydantic default values, so `model_validator(mode="after")` was required to ensure the default `.parrot` path is also resolved.
