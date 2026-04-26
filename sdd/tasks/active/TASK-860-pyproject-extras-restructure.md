# TASK-860: Pyproject Extras Restructure — Dedicated `claude-agent` Extra

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 6. Currently `claude-agent-sdk` ships bundled inside the `anthropic`
> extra (line 347) and `llms` extra (line 371). The bundled CLI is heavyweight —
> not all consumers want it. This task splits it into a dedicated `[claude-agent]`
> extra, keeping the `anthropic` extra focused on the API SDK only.

---

## Scope

- In `packages/ai-parrot/pyproject.toml`:
  - Remove `claude-agent-sdk>=0.1.0,!=0.1.49` from the `anthropic` extra (line 347).
  - Remove `claude-agent-sdk>=0.1.0,!=0.1.49` from the `llms` extra (line 371).
  - Create a new `claude-agent` extra: `claude-agent = ["claude-agent-sdk>=0.1.68"]`.
  - Add `claude-agent-sdk>=0.1.68` back to the `llms` extra (kitchen-sink umbrella).
- In the top-level `pyproject.toml` (`/home/jesuslara/proyectos/ai-parrot/pyproject.toml`):
  - Add `claude-agent = ["ai-parrot[claude-agent]"]` re-export (near line 24).
- Verify `uv pip install -e "packages/ai-parrot[anthropic]"` does NOT pull in `claude-agent-sdk`.
- Verify `uv pip install -e "packages/ai-parrot[claude-agent]"` installs `claude-agent-sdk>=0.1.68`.

**NOT in scope**: code changes to any Python files, test changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/pyproject.toml` | MODIFY | Restructure extras: split `claude-agent-sdk` into dedicated extra |
| `pyproject.toml` (top-level) | MODIFY | Add `claude-agent` re-export |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Existing Signatures to Use
```toml
# packages/ai-parrot/pyproject.toml — CURRENT state (lines 345-373)
[project.optional-dependencies]
anthropic = [
    "anthropic[aiohttp]==0.61.0",        # L346 — TASK-855 changes to >=0.97.0
    "claude-agent-sdk>=0.1.0,!=0.1.49",  # L347 — REMOVE from here
]

llms = [
    "google-genai>=1.61.0",              # L367
    "openai==2.8.1",                     # L368
    "groq==0.33.0",                      # L369
    "anthropic[aiohttp]==0.61.0",        # L370 — TASK-855 changes
    "claude-agent-sdk>=0.1.0,!=0.1.49",  # L371 — REMOVE, replace with >=0.1.68
    "xai-sdk>=0.1.0",                    # L372
]

# Top-level pyproject.toml — CURRENT re-exports
# Line 24: anthropic = ["ai-parrot[anthropic]"]
# Line 27: llms = ["ai-parrot[llms]"]
```

### Does NOT Exist
- ~~`claude-agent` extra~~ — does not exist yet (this task creates it)
- ~~`claude-agent` re-export in top-level pyproject.toml~~ — does not exist yet

---

## Implementation Notes

### Target State
```toml
# packages/ai-parrot/pyproject.toml — AFTER this task
anthropic = [
    "anthropic[aiohttp]>=0.97.0,<1.0.0",  # (set by TASK-855)
    # claude-agent-sdk REMOVED from here
]

claude-agent = [
    "claude-agent-sdk>=0.1.68",
]

llms = [
    "google-genai>=1.61.0",
    "openai==2.8.1",
    "groq==0.33.0",
    "anthropic[aiohttp]>=0.97.0,<1.0.0",  # (set by TASK-855)
    "claude-agent-sdk>=0.1.68",            # kept in umbrella
    "xai-sdk>=0.1.0",
]

# Top-level pyproject.toml — AFTER this task
[project.optional-dependencies]
anthropic = ["ai-parrot[anthropic]"]
claude-agent = ["ai-parrot[claude-agent]"]  # NEW
llms = ["ai-parrot[llms]"]
```

### Key Constraints
- Pin `claude-agent-sdk>=0.1.68` — the `!=0.1.49` exclusion is no longer needed
  since `>=0.1.68` already moves past it
- The `anthropic` extra must NOT include `claude-agent-sdk` after this change
- The `llms` umbrella keeps `claude-agent-sdk` for kitchen-sink installs
- If TASK-855 has already run, the `anthropic[aiohttp]` pin will be `>=0.97.0,<1.0.0`;
  if not, leave it as-is and TASK-855 will change it independently

### References in Codebase
- `packages/ai-parrot/pyproject.toml:345-373` — extras section
- `/home/jesuslara/proyectos/ai-parrot/pyproject.toml:24-27` — top-level re-exports

---

## Acceptance Criteria

- [ ] `claude-agent-sdk` is NOT in the `anthropic` extra
- [ ] New `claude-agent` extra exists with `claude-agent-sdk>=0.1.68`
- [ ] `llms` extra includes `claude-agent-sdk>=0.1.68`
- [ ] Top-level `pyproject.toml` has `claude-agent = ["ai-parrot[claude-agent]"]` re-export
- [ ] `uv pip install -e "packages/ai-parrot[anthropic]"` does NOT install `claude-agent-sdk`
- [ ] `uv pip install -e "packages/ai-parrot[claude-agent]"` installs `claude-agent-sdk>=0.1.68`

---

## Test Specification

```bash
# Verification — run after install
source .venv/bin/activate

# Test 1: anthropic extra does NOT include claude-agent-sdk
uv pip install -e "packages/ai-parrot[anthropic]"
python -c "import claude_agent_sdk" 2>&1 | grep -q "ModuleNotFoundError" && echo "PASS: not in anthropic extra"

# Test 2: claude-agent extra includes it
uv pip install -e "packages/ai-parrot[claude-agent]"
python -c "import claude_agent_sdk; print('version:', claude_agent_sdk.__version__)" && echo "PASS: claude-agent extra works"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none (parallel to TASK-855)
3. **Verify the Codebase Contract** — confirm pyproject.toml lines are as described
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the extras restructure
6. **Verify** install behavior for both extras
7. **Move this file** to `tasks/completed/TASK-860-pyproject-extras-restructure.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
