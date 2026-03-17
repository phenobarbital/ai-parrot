# TASK-346: Replace Direct Registry Internals Access with get_metadata()

**Feature**: API Bot Creation — Normalization & Provisioning
**Feature ID**: FEAT-049
**Spec**: `sdd/specs/new-api-bot-creation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Encapsulation cleanup for FEAT-049. The handler directly accesses `registry._registered_agents` (a protected dict) in multiple places. Replace all reads with the public `registry.get_metadata(name)` method.
> Implements spec Section 3 — Module 2, change #3.

---

## Scope

- In `parrot/handlers/bots.py`, find ALL occurrences of `registry._registered_agents` and replace:
  - **Reads**: `registry._registered_agents.get(name)` → `registry.get_metadata(name)`
  - **Dict iteration**: `registry._registered_agents.items()` — check if a public method exists (e.g., `registry.list_bots()` or `registry.iter_agents()`). If not, use the appropriate public API.
  - **Writes**: `registry._registered_agents[name] = BotMetadata(...)` — leave these as-is for now (Open Question #2 in spec). Add a `# TODO: replace with registry.register() once signature confirmed` comment.

- Verify `registry.get_metadata(name)` returns `Optional[BotMetadata]` (returns `None` if not found) — matches the existing `.get(name)` behavior.

**NOT in scope**: Naming utilities (TASK-345), handler normalization logic (TASK-347), vector store provisioning (TASK-348).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/bots.py` | MODIFY | Replace `_registered_agents` reads with `get_metadata()` |

---

## Implementation Notes

- `get_metadata(name)` is defined at `parrot/registry/registry.py:294-295`:
  ```python
  def get_metadata(self, name: str) -> Optional[BotMetadata]:
      return self._registered_agents.get(name)
  ```
  This is a direct drop-in replacement for `.get(name)`.

- For iteration patterns (e.g., listing all registry agents in GET), check if `registry.list_bots()` or similar exists. If so, use it. If not, document the gap but keep the iteration as-is with a TODO.

- The `registry.has(name)` method (used in `_check_duplicate`) is already a public method — no change needed there.

---

## Acceptance Criteria

- [x] Zero occurrences of `_registered_agents` in `parrot/handlers/bots.py` for READ operations.
- [x] Write operations have a `# TODO` comment noting future cleanup.
- [x] All existing handler behavior is preserved (GET, PUT, POST, DELETE work identically).
- [x] No changes to `parrot/registry/registry.py`.
