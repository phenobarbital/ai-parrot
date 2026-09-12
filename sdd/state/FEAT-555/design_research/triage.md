# Design research triage — dev-loop-slack (FEAT-555)

Model: gpt-5.6-luna · codex-cli 0.154.0 · reasoning high · Status: completed
Every affected path passed repository containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Use an explicit topology discriminator (architecture) | CONFIRM | Verified: `console._load_brief` (console.py:687) only knows `parse_brief`; `DevRequestBrief` has no base-branch field. The spec routes the headless loader on the brief's `kind` and adds `flow_type`/`base_branch`. | §3 M2 `load_headless_brief`, M3, M5 |
| S2 | Extract a package-owned dev-flow builder (architecture) | CONFIRM | Verified: `server_dev.py:_on_startup` imports sibling example modules (server_dev.py:40-42). Builder returns the exact `dev_loop_flow_kwargs`; example delegates. | §3 M2 (`DevFlowRuntime.dev_loop_flow_kwargs`) |
| S3 | Split preflight by topology (risk) | CONFIRM | Verified: `PreflightResult.ok = all(c.passed)` (bootstrap.py:223) and Jira is a hard check (:202) while the dev-flow treats Jira as optional; Redis check only tests URL presence (:92-105). | §3 M2 `preflight(topology=…)`, §7 |
| S4 | Enforce initiator authorization outside the REST contract (risk) | CONFIRM | Verified: `commands.py:19` documents the routes as auth-agnostic and the handlers trust `resolved_by`. Ownership already persisted in the Redis registry; the per-run bearer token is now required in BOTH socket and TCP modes. | §3 M1/M6, §7 endpoint & auth |
| S5 | Fix Slack ingress authentication and mode parity first (risk) | CONFIRM | Verified: `interactive.py` has no signature verification and the route is mounted directly (wrapper.py:144); `socket_handler.py:243,279` call `_is_authorized(channel)` without the user. Pre-existing gaps the new gate actions would widen. | §3 M9, §4, §5 AC20 |
| S6 | Add a gate-reply interceptor before normal message handling (architecture) | CONFIRM | Verified: both paths go straight to `_safe_answer` (wrapper.py:305, socket_handler.py:255). Already designed as `add_message_interceptor` consulted in both modes. | §3 M9, M11 |
| S7 | Make cancellation terminate the child flow (risk) | CONFIRM | Verified: `cancel_run` only applies `RunCancelled` (runner.py:1064-1067); no node consumes `cancel_requested_by`; `wait_gate` wakes only on gate events (session_state.py:1394-1400). Headless child cancels its run task after a 200 cancel; parent escalates to SIGTERM/SIGKILL. | §3 M1, M6, M8, §7 |
| S8 | Specify a bounded subprocess supervisor (risk) | CONFIRM | Stdout handshake needs continuous pipe draining; tail must stop on child exit; deterministic socket cleanup. | §3 M6, M8, §7 |
| S9 | Add integration-level admission control (architecture) | REJECT | The user explicitly decided "unlimited" concurrency in discovery (brainstorm §Open Questions); the spec already provides an opt-in `max_concurrent_runs` and TTL cleanup of pending confirmations, and documents unlimited as the explicit default. | — |
| S10 | Extend the Slack wrapper for debounced status updates (api) | CONFIRM | Verified: `_post_message` returns None (wrapper.py:585); Slack API calls stay in the wrapper (`post_message`/`update_message`), debounce in the transport. | §3 M9, M13 |
| S11 | Test the real cross-process contract (testing) | CONFIRM | Existing tests are in-process; added explicit integration rows: Unix-site/client contract, first-writer 409, cancel, crash before terminal, Redis loss, socket cleanup, Slack auth in both modes. | §4 Integration Tests |
| S12 | Declare Redis in the devloop integration extra (risk) | CONFIRM | Verified: `redis>=5.0` only under `msteams` and `broadcast` extras (pyproject.toml:56,104). `[devloop]` extra + install-path test. | §3 M12, §7 External Dependencies |

Summary: **11** confirmed · **1** rejected · **0** escalated.
