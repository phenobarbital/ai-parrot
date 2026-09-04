# TASK-2806: Core Extras & Workspace Update

**Feature**: FEAT-523 — PEP 420 LLM Client Extraction
**Spec**: `sdd/specs/pep-420-llm-clients.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2796, TASK-2797, TASK-2798, TASK-2799, TASK-2800, TASK-2801, TASK-2802, TASK-2803, TASK-2804, TASK-2805
**Assigned-to**: unassigned

---

## Context

After all 10 satellite packages are scaffolded (TASK-2796–TASK-2805), the
core `pyproject.toml` extras must be rewritten to pull satellite packages
instead of listing SDK dependencies inline. The root workspace
`pyproject.toml` must also register the new packages as workspace members.
Implements spec Module 7.

---

## Scope

- **Core `packages/ai-parrot/pyproject.toml`**:
  - Rewrite per-provider extras to pull the corresponding satellite package:
    ```toml
    [project.optional-dependencies]
    openai = ["ai-parrot-client-openai"]
    anthropic = ["ai-parrot-client-anthropic"]
    google = ["ai-parrot-client-google"]
    amazon = ["ai-parrot-client-amazon"]
    groq = ["ai-parrot-client-groq"]
    grok = ["ai-parrot-client-grok"]
    zai = ["ai-parrot-client-zai"]
    nvidia = ["ai-parrot-client-nvidia"]
    local = ["ai-parrot-client-local"]
    hf = ["ai-parrot-client-hf"]
    ```
  - Rewrite `llms` extra to pull all 10 satellites:
    ```toml
    llms = [
        "ai-parrot-client-openai",
        "ai-parrot-client-anthropic",
        "ai-parrot-client-google",
        "ai-parrot-client-amazon",
        "ai-parrot-client-groq",
        "ai-parrot-client-grok",
        "ai-parrot-client-zai",
        "ai-parrot-client-nvidia",
        "ai-parrot-client-local",
        "ai-parrot-client-hf",
    ]
    ```
  - Remove SDK dependencies (openai, anthropic, google-genai, groq, etc.)
    from core extras — these now live in each satellite's `pyproject.toml`.
  - Keep the `all` extra as-is or ensure it transitively includes `llms`.

- **Root `pyproject.toml`**:
  - Add all 10 satellite packages to `[tool.uv.workspace] members`:
    ```toml
    members = [
        "packages/*",  # if using glob — verify existing pattern
    ]
    ```
  - The `all` extra in root pulls `ai-parrot[llms]` transitively (not each
    satellite individually — resolved decision).

- Verify `uv pip install -e packages/ai-parrot[llms]` installs all satellites.

**NOT in scope**: modifying factory.py (TASK-2795), moving files (TASK-2796–2805),
writing tests (TASK-2807).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Rewrite extras to pull satellites, remove SDK deps from extras |
| `pyproject.toml` (root) | MODIFY | Add satellite packages to workspace members |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Not applicable — this task modifies pyproject.toml files only
```

### Existing Signatures to Use
```toml
# Root pyproject.toml — workspace declaration
[tool.uv.workspace]
members = ["packages/*"]
# Verify exact current pattern before modifying
```

### Does NOT Exist
- ~~Root-level `all` extra listing each satellite~~ — resolved to use
  transitive `ai-parrot[llms]` instead

---

## Implementation Notes

### Pattern to Follow
```toml
# Each satellite's pyproject.toml already declares its own SDK deps.
# Core extras just pull the satellite package — the transitive deps
# bring in the SDK.
#
# BEFORE (core pyproject.toml):
# openai = ["openai==3.3.1"]
#
# AFTER:
# openai = ["ai-parrot-client-openai"]
```

### Key Constraints
- Do NOT remove SDK deps from the core `[project.dependencies]` section —
  only from `[project.optional-dependencies]` (extras). Core deps like
  `aiohttp` stay.
- The `all` extra in root `pyproject.toml` pulls `ai-parrot[llms]`
  transitively — this is the resolved decision.
- Workspace members pattern may already use `"packages/*"` glob — verify
  before adding individual entries.

### References in Codebase
- `packages/ai-parrot/pyproject.toml` — current extras section
- `pyproject.toml` (root) — workspace member list

---

## Acceptance Criteria

- [ ] `pip install ai-parrot[llms]` installs all 10 satellite packages
- [ ] `pip install ai-parrot[openai]` installs `ai-parrot-client-openai`
- [ ] `pip install ai-parrot[anthropic]` installs `ai-parrot-client-anthropic`
- [ ] Root `pyproject.toml` includes all satellite packages as workspace members
- [ ] Root `all` extra transitively includes `ai-parrot[llms]`
- [ ] No SDK-specific dependencies remain in core's optional-dependencies
- [ ] `uv pip install -e packages/ai-parrot[llms]` succeeds in workspace

---

## Test Specification

```bash
# Manual verification:
uv pip install -e "packages/ai-parrot[llms]"
python -c "from parrot.clients.gpt import OpenAIClient; print('OK')"
python -c "from parrot.clients.claude import AnthropicClient; print('OK')"
python -c "from parrot.clients.google import GoogleGenAIClient; print('OK')"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/pep-420-llm-clients.spec.md` for full context
2. **Check dependencies** — verify TASK-2796 through TASK-2805 are completed
3. **Verify the Codebase Contract** — read both pyproject.toml files
4. **Update status** in `sdd/tasks/index/pep-420-llm-clients.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2806-core-extras-workspace-update.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
