---
type: Wiki Overview
title: 'TASK-1079: Add `config_file` field to CloudSploitConfig'
id: doc:sdd-tasks-completed-task-1079-cloudsploit-config-file-field-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Per FEAT-160 proposal §3 ("What Changes" → first bullet) and §2.1 (Localization
  row 1):'
relates_to:
- concept: mod:parrot.conf
  rel: mentions
---

# TASK-1079: Add `config_file` field to CloudSploitConfig

**Feature**: FEAT-160 — CloudSploit `--config` support for run_scan
**Spec**: `sdd/proposals/cloudsploit-config-support.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Per FEAT-160 proposal §3 ("What Changes" → first bullet) and §2.1 (Localization row 1):
`CloudSploitConfig` currently has no slot for a credentials-config file path. We need a
per-instance default that toolkit-level `run_scan(config=...)` falls back to. The
existing `gcp_credentials_path` field is the precedent to mirror.

This task is the foundation for downstream tasks (TASK-1082 reads this field; TASK-1083
reads it from the toolkit). It touches only `models.py` and is the only `parallel: true`
task in this feature.

---

## Scope

- Add a single `config_file: Optional[str] = None` field to `CloudSploitConfig`,
  positioned next to `gcp_credentials_path` (i.e., in the "credentials path" group, not
  in the "Docker settings" group).
- Field description: "Path to a CloudSploit JS credentials file (passed as
  `--config=<path>`). When set, takes precedence over env-var credentials."
- Add a couple of test cases in `tests/cloudsploit/test_models.py` covering default
  (None) and explicit assignment.

**NOT in scope**:
- Reading or parsing the file's contents — that's CloudSploit's job.
- Wiring the field into the executor or toolkit — TASK-1082 / TASK-1083.
- Any volume-mount logic — TASK-1080.
- Auto-discovering a default path from parrot.conf — keep it Optional[str] = None.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py` | MODIFY | Append `config_file` field to `CloudSploitConfig` |
| `packages/ai-parrot-tools/tests/cloudsploit/test_models.py` | MODIFY | Add ~2 tests for the new field |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in models.py — no new imports needed
from typing import Optional
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:81
class CloudSploitConfig(BaseModel):
    """Configuration for CloudSploit execution."""
    # Existing field at line ~145 (insert config_file next to this):
    gcp_credentials_path: Optional[str] = Field(
        default=None,
        description="Path to GCP service account JSON file"
    )
```

### Does NOT Exist
- ~~`CloudSploitConfig.config_file`~~ — this is what we are adding.
- ~~`parrot.conf.CLOUDSPLOIT_CONFIG_FILE`~~ — not defined; do NOT add a default lookup.
- ~~`CloudSploitConfig.credential_file`~~ — wrong field name; the upstream calls it
  `--config` on the CLI side but our Python field is `config_file`.

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:145-148 (existing precedent)
gcp_credentials_path: Optional[str] = Field(
    default=None,
    description="Path to GCP service account JSON file"
)

# Add immediately below this group:
config_file: Optional[str] = Field(
    default=None,
    description=(
        "Path to a CloudSploit JS credentials file (passed as "
        "`--config=<path>` to the CLI). When set, takes precedence over "
        "env-var credentials."
    ),
)
```

### Key Constraints
- Pydantic field; `Optional[str]` with `default=None`.
- Do not introduce any new imports.
- Do not change the description wording on neighbouring fields.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:145` — closest precedent.

---

## Acceptance Criteria

- [ ] `CloudSploitConfig().config_file is None` is true.
- [ ] `CloudSploitConfig(config_file="/path/x.js").config_file == "/path/x.js"`.
- [ ] All existing tests in `packages/ai-parrot-tools/tests/cloudsploit/test_models.py`
  still pass.
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py` clean.

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/cloudsploit/test_models.py
def test_config_file_defaults_to_none():
    """CloudSploitConfig.config_file defaults to None."""
    cfg = CloudSploitConfig()
    assert cfg.config_file is None


def test_config_file_accepts_path():
    """CloudSploitConfig.config_file holds an arbitrary path string."""
    cfg = CloudSploitConfig(config_file="/etc/cloudsploit/config.js")
    assert cfg.config_file == "/etc/cloudsploit/config.js"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the proposal** at `sdd/proposals/cloudsploit-config-support.proposal.md` §3.
2. **Verify the Codebase Contract** by reading
   `packages/ai-parrot-tools/src/parrot_tools/cloudsploit/models.py:81-161`.
3. **Implement** the single field addition per the pattern above.
4. **Run tests**: `pytest packages/ai-parrot-tools/tests/cloudsploit/test_models.py -v`.
5. **Move this file** to `sdd/tasks/completed/TASK-1079-cloudsploit-config-file-field.md`.
6. **Update** the per-spec index `sdd/tasks/index/cloudsploit-config-support.json`.
7. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-05-12
**Notes**: Added `config_file: Optional[str] = Field(default=None, ...)` to `CloudSploitConfig` immediately after `gcp_credentials_path`. Two new tests pass: `test_config_file_defaults_to_none` and `test_config_file_accepts_path`. One pre-existing failure (`test_default_values`) unrelated to this task (env-specific AWS region).

**Deviations from spec**: none
