# TASK-628: Add trafilatura dependency to ai-parrot-loaders

**Feature**: vector-store-handler-scraping
**Spec**: `sdd/specs/vector-store-handler-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This is the prerequisite task for FEAT-091. Before any extraction code can be written,
> `trafilatura` must be available as a dependency. It's added as an optional dependency
> under the `scraping` extra group in the loaders package, and a graceful import guard
> is established so the loader degrades to markdownify if trafilatura is not installed.
>
> Implements: Spec Module 3.

---

## Scope

- Add `trafilatura>=1.12` to `packages/ai-parrot-loaders/pyproject.toml` under `[project.optional-dependencies]` as a new `scraping` extra group
- Add `scraping` to the `all` extras list
- Install the dependency in the dev environment: `source .venv/bin/activate && uv pip install trafilatura>=1.12`
- Verify the import works: `python -c "import trafilatura; print(trafilatura.__version__)"`

**NOT in scope**: Writing any extraction logic (that's TASK-629). Only dependency management.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-loaders/pyproject.toml` | MODIFY | Add `scraping` optional-dependency group with `trafilatura>=1.12` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# After this task, the following import MUST work:
import trafilatura  # new dependency
```

### Existing Signatures to Use

```python
# packages/ai-parrot-loaders/pyproject.toml (current structure)
# [project.optional-dependencies] section contains:
#   youtube = [...]      # line 34
#   audio = [...]        # line 39
#   pdf = [...]          # line 52
#   web = [...]          # line 53
#   ebook = [...]        # line 54
#   video = [...]        # line 55
#   document = [...]     # line 56
#   ml = [...]           # line 59
#   ml-heavy = [...]     # line 69
#   all = [...]          # line 82
```

### Does NOT Exist

- ~~`scraping` optional-dependency group~~ — does not exist yet; must be created
- ~~`trafilatura` in any existing dependency group~~ — not present anywhere in pyproject.toml

---

## Implementation Notes

### Pattern to Follow

Follow the same pattern as existing optional-dependency groups:

```toml
scraping = [
    "trafilatura>=1.12",
    "beautifulsoup4>=4.12",
    "markdownify>=0.11",
]
```

Note: `beautifulsoup4` and `markdownify` are already indirect dependencies via the `web` group, but listing them explicitly in `scraping` makes the group self-contained.

### Key Constraints

- Use `uv` for package management (project rule)
- Always activate venv first: `source .venv/bin/activate`
- Verify import works after installation

---

## Acceptance Criteria

- [ ] `trafilatura>=1.12` added to `pyproject.toml` under `[project.optional-dependencies].scraping`
- [ ] `scraping` added to the `all` extras list
- [ ] `python -c "import trafilatura"` succeeds in the venv
- [ ] No existing dependencies broken

---

## Test Specification

```python
# No code tests needed — just verify the import works:
# python -c "import trafilatura; print(trafilatura.__version__)"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/vector-store-handler-scraping.spec.md` for full context
2. **Check dependencies** — this task has none (it's the first task)
3. **Verify the Codebase Contract** — read `packages/ai-parrot-loaders/pyproject.toml` to confirm the structure
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope above
6. **Verify** the acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-628-trafilatura-dependency.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
