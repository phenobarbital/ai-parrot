---
type: Wiki Overview
title: 'TASK-1344: Satellite Package Scaffold'
id: doc:sdd-tasks-completed-task-1344-satellite-package-scaffold-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create the empty satellite package `packages/ai-parrot-integrations/`
relates_to:
- concept: mod:parrot.human.channels
  rel: mentions
- concept: mod:parrot.integrations
  rel: mentions
- concept: mod:parrot.voice
  rel: mentions
---

# TASK-1344: Satellite Package Scaffold

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Create the empty satellite package `packages/ai-parrot-integrations/`
with `pyproject.toml`, directory structure, and extras. This is the
foundation that all channel extraction tasks depend on.

Uses PEP 420 namespace extension (same pattern as FEAT-201
`ai-parrot-embeddings`). The package contributes to `parrot.integrations.*`
and `parrot.voice.*` and `parrot.human.channels.*` namespaces.

Implements **Spec Module 1**.

---

## Scope

- Create `packages/ai-parrot-integrations/` directory structure:
  ```
  packages/ai-parrot-integrations/
    pyproject.toml
    README.md
    src/
      parrot/
        integrations/    (NO __init__.py here yet — added in TASK-1347)
        voice/           (empty dir placeholder)
        human/
          channels/      (empty dir placeholder)
    tests/
      __init__.py
  ```
- Write `pyproject.toml` with:
  - Package metadata (name, version, description)
  - Dependency on `ai-parrot` (core)
  - Extras: `[slack|telegram|msteams|whatsapp|matrix|voice|messaging|all]`
  - `[tool.setuptools.packages.find]` with `include = ["parrot*"]`,
    `namespaces = true`
- **CRITICAL**: Do NOT create `src/parrot/__init__.py` — this would break
  PEP 420 namespace extension.
- Add workspace member to root `pyproject.toml` (`[tool.uv.sources]`
  and `[tool.uv.workspace]` if applicable).
- Write minimal README.md.

**NOT in scope**: Moving any source files (done in subsequent tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/pyproject.toml` | CREATE | Package config with extras |
| `packages/ai-parrot-integrations/README.md` | CREATE | Minimal readme |
| `packages/ai-parrot-integrations/src/parrot/integrations/.gitkeep` | CREATE | Placeholder |
| `packages/ai-parrot-integrations/src/parrot/voice/.gitkeep` | CREATE | Placeholder |
| `packages/ai-parrot-integrations/src/parrot/human/channels/.gitkeep` | CREATE | Placeholder |
| `packages/ai-parrot-integrations/tests/__init__.py` | CREATE | Test package |
| `pyproject.toml` (workspace root) | MODIFY | Add workspace member |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# parrot/__init__.py:9,12 — namespace extension already in place
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

### Existing Signatures to Use

```toml
# Reference: packages/ai-parrot-embeddings/pyproject.toml structure (FEAT-201)
# Use this as the template for pyproject.toml layout, setuptools config,
# and namespace package configuration.
```

### Does NOT Exist

- ~~`packages/ai-parrot-integrations/`~~ — does NOT exist yet; this task creates it
- ~~`src/parrot/__init__.py` in satellite~~ — must NEVER be created

---

## Implementation Notes

### Pattern to Follow

Reference `packages/ai-parrot-embeddings/pyproject.toml` for the exact
setuptools namespace configuration that works with `pkgutil.extend_path`.

Key pyproject.toml sections:
```toml
[project]
name = "ai-parrot-integrations"
version = "0.1.0"
description = "Messaging channel integrations for AI-Parrot"
requires-python = ">=3.10"
dependencies = ["ai-parrot"]

[project.optional-dependencies]
slack = ["slack-sdk>=3.0", "slack-bolt>=1.18"]
telegram = ["aiogram>=3.12"]
msteams = ["azure-teambots>=0.1.1", "parrot-formdesigner"]
whatsapp = ["pywa>=3.8.0"]
matrix = ["mautrix>=0.20", "python-olm>=3.2.16"]
voice = ["faster-whisper", "openai"]
messaging = [
    "ai-parrot-integrations[slack]",
    "ai-parrot-integrations[telegram]",
    "ai-parrot-integrations[msteams]",
    "ai-parrot-integrations[whatsapp]",
]
all = [
    "ai-parrot-integrations[messaging]",
    "ai-parrot-integrations[matrix]",
    "ai-parrot-integrations[voice]",
]

[tool.setuptools.packages.find]
where = ["src"]
include = ["parrot*"]
namespaces = true
```

### Key Constraints

- **NEVER** create `src/parrot/__init__.py` — breaks namespace extension.
- Verify with `ai-parrot-embeddings` layout for consistency.
- Extras must use exact version pins from the brainstorm.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-integrations/pyproject.toml` exists with all extras
- [ ] Directory structure created under `src/parrot/`
- [ ] NO `src/parrot/__init__.py` exists
- [ ] Workspace root `pyproject.toml` includes the new member
- [ ] `pip install -e packages/ai-parrot-integrations` succeeds (editable install)
- [ ] `import parrot.integrations` still works (from core)

---

## Test Specification

```python
def test_satellite_installable():
    import subprocess
    result = subprocess.run(
        ["pip", "install", "-e", "packages/ai-parrot-integrations"],
        capture_output=True, text=True
    )
    assert result.returncode == 0

def test_no_parrot_init_in_satellite():
    from pathlib import Path
    assert not Path("packages/ai-parrot-integrations/src/parrot/__init__.py").exists()
```

---

## Agent Instructions

When you pick up this task:

1. Read `packages/ai-parrot-embeddings/pyproject.toml` as reference
2. Create the directory structure (do NOT add `parrot/__init__.py`)
3. Write `pyproject.toml` with all extras
4. Update workspace root pyproject
5. Test editable install

---

## Completion Note

*(Agent fills this in when done)*
