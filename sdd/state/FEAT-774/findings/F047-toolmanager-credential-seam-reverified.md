---
id: F047
query_id: F044-f1
type: grep
intent: "Depth-2: re-verify the ToolManager _broker / _cred_channel / _cred_user_id seam line numbers (TASK-1685 anchors were from 2026-05)"
executed_at: 2026-10-30T15:29:44Z
duration_ms: 0
parent_id: F044
depth: 2
---

# F047 — ToolManager seam re-verified: set_broker at :517, exec_kwargs injection at :2178-2183

## Summary

The propagation seam exists unchanged but has moved: `ToolManager.set_broker` is at manager.py:517 (attribute `_broker` initialised at :389, property at :515), and the per-call injection is at :2178-2183 — `exec_kwargs["_broker"] = self._broker` guarded by `if self._broker is not None`, then `_cred_channel` / `_cred_user_id` read from `permission_context`. A clone path copies `_broker` at :2870-2871. TASK-1685's :320 / :1305-1316 anchors are stale by ~870 lines.

## Citations

- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 389, 515-523
  symbol: `ToolManager.set_broker`
  excerpt: |
    self._broker: Optional[Any] = None            # :389
    def set_broker(self, broker: Any) -> None:    # :517
        self._broker = broker                     # :523
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2178-2183
  symbol: `ToolManager (exec_kwargs credential injection)`
  excerpt: |
    if self._broker is not None:
        exec_kwargs["_broker"] = self._broker
        exec_kwargs.setdefault("_cred_channel", getattr(permission_context, "channel", "unknown"))
        exec_kwargs.setdefault("_cred_user_id", getattr(permission_context, "user_id", None))
- path: `packages/ai-parrot/src/parrot/tools/manager.py`
  lines: 2870-2871
  symbol: `ToolManager (clone copies _broker)`
  excerpt: |
    if self._broker is not None:
        new_tm._broker = self._broker

## Notes

Verified inline by the parent (grep). Supersedes the line numbers quoted in F044. The injection happens only when a broker is set — a stdio server with no broker never gets `_cred_user_id` either.
