# F003 — HITL infrastructure for "rep confirm" and "manager PIN"

**Confidence:** high (rep-confirm), medium (manager-PIN)

A mature HITL stack already exists and is the right substrate for the gated tools:

- `HumanInteractionManager` at `packages/ai-parrot/src/parrot/human/manager.py:51`
  — `request_human_input(interaction, channel)` blocks on an `asyncio.Future`
  and returns an `InteractionResult` (per FEAT-211 spec audit).
- `InteractionType.APPROVAL = "approval"`
  (`packages/ai-parrot/src/parrot/human/models.py:60,66`) yields a boolean
  decision; validation enforces a bool result (models.py:489).
- The Telegram channel already renders inline **✅ Approve / ❌ Reject**
  (`integrations/.../human/channels/telegram.py:290`, per FEAT-211 spec).
- Central tool gating: `ToolManager.execute_tool(tool_name, parameters,
  permission_context)` (`tools/manager.py:1126`) is the single dispatch for ALL
  agent tool calls and can return `ToolResult(status="forbidden")` — the place a
  grant/approval guard lives (lifecycle `BeforeToolCallEvent` is observational,
  NO veto).
- Tool marking: `routing_meta` on `AbstractTool`
  (`tools/abstract.py:100,140`) can flag a tool `requires_grant`.
- `@requires_permission("odoo.write")` (`tools/decorators.py:9`) attaches
  `_required_permissions` and is the existing coarse gate; `PermissionContext`/
  `UserSession` (`auth/permission.py`) flow into tools.

**FEAT-211 (Tool Grants & Bounded Approval Windows, status: approved)** adds a
`Grant` model + `GrantStore` + bounded automation windows
(`request → review → grant → observe → revoke`). This is the natural home for
"manager PIN" semantics: one validated approval opens a time-boxed window during
which `validate_loading_pick` / `validate_returns` can run.

**Gap / unknown:** there is NO numeric-PIN primitive in the repo. "manager PIN"
must map onto one of: (a) `InteractionType.APPROVAL` (manager taps ✅ in
Telegram — already built), (b) a new PIN verified against Odoo `res.users`
credentials, or (c) a FEAT-211 grant. The spec must pick one.

**Citations:** `packages/ai-parrot/src/parrot/human/manager.py:51`;
`packages/ai-parrot/src/parrot/human/models.py:60,66,489`;
`packages/ai-parrot/src/parrot/tools/manager.py:1126`;
`packages/ai-parrot/src/parrot/tools/decorators.py:9`;
`packages/ai-parrot/src/parrot/tools/abstract.py:100,140`;
`sdd/specs/FEAT-211-tool-grants-bounded-approval.spec.md`
