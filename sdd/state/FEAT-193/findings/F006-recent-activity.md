---
id: F006
intent: Recent activity on the google client subpackage
query_ids: [Q012]
---

# F006 — Recent activity (3 months)

`git log --since="3 months ago" -- packages/ai-parrot/src/parrot/clients/google/`:

```
c6333cb5 fix(agnostic-prompt-caching-abstraction): address code-review issues
1428411a feat(agnostic-prompt-caching-abstraction): TASK-1224 — Google/Gemini client cache translator
47c68d22 feat(lifecycle-events-system): TASK-1194 — Integrate EventEmitterMixin into AbstractClient
32d8221d adding more lazy-imports for heavy imports in components
e7b9850c fix(clients): apply context filtering to request-scoped tools
8bea2542 more fixes in google client
4b87acf3 wip: fix multi-turn on stateless calls
2cbde0f7 fix on PandasAgent for avoid answer tool calls
315585ad fix when google pro models are echoing thoughts
```

## Notes

- No recent commit touches the **two-phase reformat path** specifically.
  The flow has been stable; this proposal is the first attempt to add a
  combined-call shortcut.
- Recent surface-area changes: prompt caching (FEAT-181), lifecycle events
  (FEAT-176), request-scoped tools, multi-turn fixes. None conflict with
  the proposed change, but the new code path must keep:
  - the cache hint integration (`_pending_cache_segs` at client.py:2120-2157)
  - the lifecycle events (`_emit_after_call` etc.)
  intact for the combined-mode branch.
- `315585ad` (pro models echoing thoughts) is a reminder that pro models
  have quirky behaviour around `thinking_config`. The combined-mode path
  must still apply `_requires_thinking()` correctly.
