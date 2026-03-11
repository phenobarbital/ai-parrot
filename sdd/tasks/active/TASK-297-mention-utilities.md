# TASK-297 — Matrix Mention Parsing and Formatting Utilities

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: high
**Effort**: S
**Depends on**: (none)
**Parallel**: true
**Parallelism notes**: Pure utility functions with no imports from other new crew modules. Can run in parallel with TASK-296 (config models).

---

## Objective

Create mention parsing and formatting utilities for Matrix, handling both plain text `@localpart` mentions and Matrix HTML pill mentions (`<a href="https://matrix.to/#/@user:server">name</a>`).

## Files to Create/Modify

- `parrot/integrations/matrix/crew/mention.py` — new file

## Implementation Details

### parse_mention(body: str, server_name: str) -> str | None

Extract the agent localpart from a Matrix message body.

Handle two formats:
1. **Plain text**: `"@analyst what is AAPL?"` → `"analyst"`
2. **Matrix pill (HTML)**: `<a href="https://matrix.to/#/@analyst:example.com">analyst</a>` → `"analyst"`

Use regex patterns:
- Plain: `r"@(\w+)(?:\s|$)"` — extract first word after `@`
- Pill: `r'href="https://matrix\.to/#/@(\w+):([^"]+)"'` — extract localpart and verify server_name matches

Return `None` if no mention found.

### format_reply(agent_mxid: str, display_name: str, text: str) -> str

Format a reply with the agent's identity:
```
<display_name>
<text>
```

### build_pill(mxid: str, display_name: str) -> str

Build a Matrix "pill" HTML mention:
```html
<a href="https://matrix.to/#/@analyst:example.com">Financial Analyst</a>
```

Used for rich-text responses that mention other agents.

## Acceptance Criteria

- [ ] `parse_mention()` extracts localpart from plain text `@mention`.
- [ ] `parse_mention()` extracts localpart from Matrix pill HTML.
- [ ] `parse_mention()` returns `None` when no mention present.
- [ ] `parse_mention()` ignores mentions for other servers when `server_name` doesn't match.
- [ ] `build_pill()` produces valid Matrix pill HTML.
- [ ] `format_reply()` formats agent name + response text.
