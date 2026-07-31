---
type: Wiki Overview
title: 'Brainstorm: Workday Conversational Agent over Telegram (Phases 3–5)'
id: doc:sdd-proposals-workday-conversational-agent-telegram-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The boss's 5-phase plan replicates Workday's reference conversational bridge
  so a
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.integrations.telegram.context
  rel: mentions
- concept: mod:parrot.stores.kb.user
  rel: mentions
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools.workday.tool
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Workday Conversational Agent over Telegram (Phases 3–5)

**Date**: 2026-06-08
**Author**: Juan (from Jesus Lara's initiative)
**Status**: exploration
**Recommended Option**: B (session-derived identity resolved in the toolkit)

> Replicates the architecture of [Workday/ai-conversation-bridge](https://github.com/Workday/ai-conversation-bridge)
> (Chat App → Connector → orchestration → Workday tools; current user resolved
> from the authenticated chat session). Builds on **FEAT-230** (merged), which
> already homologated the `WorkdayToolkit` onto the vendored composable interface
> and exposes 11 agent-facing tools. **Phases 1 & 2 of the boss's plan are
> complete via FEAT-230.** This brainstorm covers **Phases 3–5**.

---

## Problem Statement

The boss's 5-phase plan replicates Workday's reference conversational bridge so a
worker can use Workday from a chat app instead of a separate web UI:

1. Homologate the parrot Workday toolkit onto the flowtask composable — ✅ **done (FEAT-230)**.
2. Make the toolkit delegate to that composable — ✅ **done (FEAT-230)**.
3. **Verify the homologated methods work end-to-end against a live Workday tenant**
   (e.g. a worker retrieving their real PTO balances). FEAT-230's 50 tests are
   **all mocked** — there is zero evidence the delegation works against real Workday.
4. **Expose a Workday agent over Telegram** so a worker can chat with it. The
   Telegram integration is mature, but **no Workday agent is registered** and there
   is no `telegram_bots.yaml` entry for it.
5. **Resolve `worker_id` from the user's session** so the worker never types their
   employee id. FEAT-230 made session-derived identity an **explicit Non-Goal**
   (every tool requires an explicit `worker_id`). Without Phase 5 the agent would
   have to ask the worker for their id — bad UX and unsafe (anyone could query
   anyone's PTO).

**Affected users**: employees and managers (self-service HR over chat); the
platform/agents team (new agent + integration wiring).

**Why now**: FEAT-230 delivered the tool surface; it is unverified and unusable
end-to-end until an agent, a channel, and session identity are wired.

---

## Constraints & Requirements

(Resolved via two interactive discovery rounds — see Open Questions for the record.)

- **C1 — Live-tenant verification (Phase 3)**: verify against an **implementation
  tenant whose `WORKDAY_*` credentials already resolve from `parrot.conf`**. PTO
  balance retrieval for a real worker is the canonical acceptance scenario.
- **C2 — Identity is session-derived (Phase 5)**: `worker_id` becomes **optional**;
  when omitted it is resolved from the authenticated session via the
  `AbstractToolkit._pre_execute` hook + a session ContextVar, looking up
  `UserInfo` (`auth.vw_users.associate_id`). Backwards compatible: an explicit
  `worker_id` still works.
- **C3 — Authorization enforced IN CODE, fail-closed**: the toolkit (not the LLM
  prompt) enforces that a caller may only access **their own data or their
  first-level direct reports'** data. Requests for any other `worker_id` are
  denied before any Workday call.
- **C4 — Authentication required, fail-closed**: **Azure/OAuth2 SSO** must
  establish `nav_user_id` before ANY Workday tool runs. No authenticated session →
  no Workday access (and no identity to resolve).
- **C5 — Writes are self-only with explicit confirmation**: `request_my_time_off`
  may submit only for the worker themselves, and only after an explicit in-chat
  confirmation (summary + yes/no) flips `dry_run=False`. No manager-on-behalf writes.
- **C6 — No breaking change to FEAT-230's public API**: existing explicit-`worker_id`
  callers keep working; the 11 tool names/return shapes are unchanged.
- **C7 — Program structure**: **two specs** — (A) Phase 3 + Phase 4 together
  (verify live + Workday agent over Telegram, using explicit/SSO-bound identity),
  and (B) Phase 5 separately (session-derived identity + authorization), since it
  is the delicate cross-cutting architectural piece.
- **C8 — The Workday agent must NOT live in the ai-parrot (public) repo**: no
  Workday agent exists yet (confirmed). ai-parrot is the **public framework** —
  it ships only generic, non-sensitive pieces (the `WorkdayToolkit`, the Telegram
  integration, the session-identity/authorization mechanism). The **agent itself**
  — its `@register_agent` definition, system prompts, tenant-specific config and
  `telegram_bots.yaml` binding — is **sensitive/company-specific** and must be
  created in a **private repo** (the company keeps its agents in
  `navigator-plugins`, e.g. `docs/`, via `@register_agent`). **Exact target
  location is TBD — to be decided later.** This split is a hard boundary: nothing
  agent-specific or tenant-specific may be committed to ai-parrot.

---

## Options Explored

> The decisive architectural axis is **where `worker_id` is resolved from the
> session** (Phase 5). The three options below are framed around that axis; Phases
> 3 and 4 are largely common across them.

### Option A: Resolve identity in the integration layer (Telegram wrapper)

The `TelegramAgentWrapper` resolves `worker_id` from `UserInfo` after SSO login and
injects it into the agent's per-user context (it already clones a per-user agent via
`clone_for_user(user_context)`). The toolkit stays as-is (explicit `worker_id`); the
wrapper or a thin prompt-preamble supplies the value.

✅ **Pros:**
- Toolkit untouched — smallest change to FEAT-230 code.
- Reuses the existing per-user isolation path in the wrapper.

❌ **Cons:**
- **Identity logic duplicated per channel** — Slack/Teams/WhatsApp would each
  re-implement resolution. Doesn't scale to the multi-channel reference architecture.
- Authorization (C3) leaks toward the prompt/LLM unless re-implemented per channel —
  weak, not fail-closed.
- The resolved `worker_id` tends to surface in the dialogue (LLM must carry it),
  which is exactly the UX/safety smell we want to avoid.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `aiogram` | Telegram bot runtime | already used by the telegram integration |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-integrations/.../telegram/wrapper.py:1398` — `clone_for_user(user_context)` per-user agent path.
- `packages/ai-parrot/src/parrot/stores/kb/user.py:43` — `UserInfo.search(query, user_id)`.

---

### Option B: Resolve identity in the toolkit via `_pre_execute` + session ContextVar  ⭐

`worker_id` becomes `Optional[str] = None`. The toolkit overrides
`AbstractToolkit._pre_execute(tool_name, **kwargs)` to: (1) read the authenticated
session from a `ContextVar` (set by whatever integration is driving the agent),
(2) resolve the caller's `worker_id` from `UserInfo` (`associate_id`), (3) when the
tool arg is omitted, inject the caller's own id, and (4) enforce authorization
(self or first-level direct report via `manager_id`/`get_direct_reports`),
fail-closed. This is **exactly the pattern `JiraToolkit._pre_execute` already uses**
to resolve per-user `oauth2_3lo` credentials from `_permission_context`.

✅ **Pros:**
- **Channel-agnostic** — Telegram, Slack, Teams all benefit with no per-channel work;
  matches the multi-channel reference architecture.
- **Authorization enforced in one place, in code, fail-closed** (C3) — the LLM never
  decides who you are or what you may see.
- `worker_id` need never appear in the dialogue; the LLM just calls
  `get_current_user_time_off_balance()` and identity is resolved underneath.
- **Proven pattern in this codebase** (`JiraToolkit._pre_execute`, jiratoolkit.py:866) —
  low architectural risk.
- Backwards compatible (C6): explicit `worker_id` still honored (and still authorized).

❌ **Cons:**
- Requires a small, careful contract: a session/identity `ContextVar` that every
  integration sets around `agent.ask()` (the telegram `telegram_chat_scope` pattern
  is the template, so this is incremental, not novel).
- Touches `WorkdayToolkit` (the FEAT-230 surface) — must preserve signatures.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `contextvars` (stdlib) | Carry session identity into tool execution | same mechanism as `telegram/context.py` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/tools/toolkit.py:306` — `_pre_execute(tool_name, **kwargs)` hook; `_permission_context` always injected (toolkit.py:174-179).
- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:866` — **reference** per-user resolution in `_pre_execute` (oauth2_3lo).
- `packages/ai-parrot/src/parrot/stores/kb/user.py:43-53` — `UserInfo.search` returns `associate_id as employee_id` AND `manager_id` (for the direct-report check).
- `packages/ai-parrot-integrations/.../telegram/context.py:14-20` — `ContextVar` + `telegram_chat_scope` template for a session-scope ContextVar.

---

### Option C: Explicit `resolve_current_worker` tool the LLM calls first

Add a tool that returns the current user's `worker_id` from the session; the LLM is
prompted to call it first, then pass the id to the other tools.

✅ **Pros:**
- Very visible/debuggable; no change to the other tool signatures.
- No ContextVar contract needed beyond exposing the session to that one tool.

❌ **Cons:**
- **Authorization still not enforced** — the LLM could pass any id to other tools;
  not fail-closed (violates C3).
- Relies on the LLM to chain correctly; brittle and leaks `worker_id` into the dialogue.
- Doesn't replicate the reference UX (identity should be implicit).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| (none new) | — | — |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/stores/kb/user.py:43` — `UserInfo.search`.

---

## Recommendation

**Option B** is recommended.

It is the only option that satisfies **C3 (authorization enforced in code,
fail-closed)** and **C2 (identity never typed/never in the dialogue)** while staying
**channel-agnostic** — matching the reference architecture where the same Workday
tool surface is reached from many chat apps. Crucially, it is **not a novel pattern
here**: `JiraToolkit._pre_execute` already resolves per-user identity/credentials
from `_permission_context` (jiratoolkit.py:866), and `telegram/context.py` already
uses a `ContextVar` to carry chat scope into tool execution. We are composing two
proven patterns, not inventing one.

The tradeoff we accept: Option B touches the FEAT-230 `WorkdayToolkit` (vs. Option
A's zero-toolkit-change). We mitigate by keeping `worker_id` optional and additive
(C6) — explicit callers and the 50 existing tests stay green. We reject Option A
(identity duplicated per channel; weak authorization) and Option C (LLM-trusted
authorization; leaks identity) because both fail the fail-closed security bar the
boss's "self + direct reports" policy requires.

---

## Feature Description

### User-Facing Behavior
An employee opens the Workday bot in Telegram, authenticates once via **Azure/OAuth2
SSO**, then chats naturally:
- *"What's my PTO balance?"* → the agent answers from **live Workday** for the
  authenticated worker — no id typed.
- *"How much vacation does Maria (my report) have left?"* → allowed only if Maria is
  the caller's **direct report**; otherwise the agent declines (fail-closed).
- *"Request 2 days off next week."* → the agent summarizes the request and asks for
  an explicit **yes/no confirmation** before submitting to Workday (self only).
- An unauthenticated user is prompted to log in first; no Workday data is returned.

### Internal Behavior (high level)
- **Phase 3 (verify)**: a live-tenant verification harness exercises the homologated
  read methods (esp. `get_time_off_balance` / `get_current_user_time_off_balance`)
  against the impl tenant whose `WORKDAY_*` creds resolve from `parrot.conf`, and
  records evidence (real PTO balance retrieved). Gated/skipped when creds absent so
  CI stays green.
- **Phase 4 (agent + Telegram)**: **ai-parrot side (this repo)** only ensures the
  framework is ready — `WorkdayToolkit` is loadable and the Telegram integration can
  host an arbitrary agent with SSO required (fail-closed) + allowlist. The
  **Workday agent itself is created in a private repo (location TBD — NOT
  ai-parrot)**: a `@register_agent` Workday agent that loads `WorkdayToolkit`, its
  system prompts, and the `telegram_bots.yaml` binding all live outside parrot (C8).
  The existing `TelegramBotManager` / `TelegramAgentWrapper` host it; SSO
  establishes `nav_user_id`. The seam between the two repos is just the public
  `WorkdayToolkit` import + the integration config contract.
- **Phase 5 (identity + authz)**: an authenticated-session `ContextVar` is set by the
  integration around `agent.ask()`. `WorkdayToolkit._pre_execute` resolves the
  caller's `worker_id` from `UserInfo` (`associate_id`), injects it when the tool
  arg is omitted, and **enforces self-or-direct-report** authorization before any
  Workday call. Writes (`request_my_time_off`) are self-only + confirmation-gated.

### Edge Cases & Error Handling
- **No authenticated session** → tools refuse with a "please log in" message (C4).
- **Authenticated but no `associate_id`** in `auth.vw_users` → graceful "couldn't
  verify your Workday identity" (no Workday call).
- **Requested worker is not self/direct report** → denied, logged, no Workday call (C3).
- **Live tenant unreachable / creds missing (Phase 3)** → verification skipped with a
  clear log, never a false "verified".
- **Write without confirmation** → stays `dry_run`, nothing submitted (C5).
- **DataFrame/JSON boundary** → unchanged from FEAT-230 (tools return JSON-serializable).

---

## Capabilities

### New Capabilities
- `workday-live-verification`: live-tenant end-to-end verification of the homologated
  Workday read methods (Phase 3). *(spec A)*
- `workday-telegram-agent`: framework-readiness in ai-parrot to host a Workday agent
  over Telegram with SSO-gated access (Phase 4). **The agent definition itself is
  created in a private repo, NOT in ai-parrot (C8 — location TBD).** *(spec A — the
  parrot-side enablement; the private-repo agent is tracked separately.)*
- `workday-session-identity`: session-derived `worker_id` resolution + self/direct-report
  authorization in the toolkit (Phase 5). *(spec B)*

### Modified Capabilities
- `workday-tooling-composable-interface` (FEAT-230): `worker_id` becomes optional with
  session resolution; tools gain a fail-closed authorization gate. Additive, non-breaking.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/.../workday/tool.py` (`WorkdayToolkit`) | modifies | add `_pre_execute` (resolve + authorize); `worker_id` → optional; confirmation gate for write |
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | depends on | reuse `_pre_execute` + `_permission_context` plumbing (no change expected) |
| `packages/ai-parrot/src/parrot/stores/kb/user.py` (`UserInfo`) | depends on / extends | `associate_id`→worker_id and `manager_id` for direct-report check |
| `packages/ai-parrot-integrations/.../telegram/` | extends | session-identity ContextVar around `agent.ask()`; `telegram_bots.yaml` Workday bot; SSO required |
| Workday agent (NEW) | creates — **in a private repo, NOT ai-parrot (C8)** | `@register_agent` agent loading `WorkdayToolkit` + prompts + `telegram_bots.yaml`; none exists today; target location TBD (likely `navigator-plugins/docs`) |
| `parrot.conf` `WORKDAY_*` | depends on | impl-tenant creds for Phase 3 verification |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...   # line 306
    # `_permission_context` is ALWAYS injected as a kwarg before _pre_execute (lines 174-179)

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py  — REFERENCE PATTERN for Phase 5
class JiraToolkit(AbstractToolkit):
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:        # line 866
        # if self.auth_type == "oauth2_3lo":
        #     perm_ctx = kwargs.get("_permission_context")  # line 878  → resolves per-user creds

# packages/ai-parrot-tools/src/parrot_tools/workday/tool.py  (FEAT-230 surface)
from ..interfaces.workday.service import WorkdayService as WorkdayComposable  # line 75
class WorkdayToolkit(AbstractToolkit):
    self._composables: Dict[str, WorkdayComposable]                       # line 548
    async def _get_composable(self, operation_type: str) -> WorkdayComposable: ...  # line 656
    async def get_current_user_info(self, worker_id: str) -> Dict[str, Any]: ...    # line 1677
    async def get_time_off_balance(self, worker_id: str,
                                   time_off_plan_id: Optional[str] = None) -> List[Dict]: ...  # ~1787
    async def get_current_user_time_off_balance(self, worker_id: str) -> List[Dict]: ...        # ~1815
    async def get_direct_reports(self, worker_id: str) -> List[Dict]: ...           # ~1754
    async def request_my_time_off(self, worker_id: str, start_date: str, end_date: str,
                                  time_off_type: str, daily_quantity: float = 8.0,
                                  comment: Optional[str] = None, dry_run: bool = True) -> Dict: ... # ~1883
    # NOTE: WorkdayToolkit does NOT currently override _pre_execute (verified — grep empty)

# packages/ai-parrot/src/parrot/stores/kb/user.py
class UserInfo(AbstractKnowledgeBase):                                     # line 11
    async def search(self, query: str, user_id: int, **kwargs) -> List[Dict]: ...   # line 43
    #   SQL selects: associate_id as employee_id, ..., manager_id          # lines 52-53

# packages/ai-parrot-integrations/src/parrot/integrations/telegram/
#   context.py
current_telegram_chat_id: ContextVar[Optional[str]]                        # line 14
def telegram_chat_scope(chat_id) -> Iterator[None]: ...                    # line 20  (ContextVar template)
#   auth.py
class TelegramUserSession:                                                 # line 43
    nav_user_id: Optional[str]      # set after login
    @property
    def user_id(self) -> str: ...   # nav_user_id if authenticated else f"tg:{telegram_id}"
#   wrapper.py
class TelegramAgentWrapper:
    self._user_sessions: Dict[int, TelegramUserSession]                    # line 137
    # await agent.ask(...) with per-user isolation; session.user_agent = await self.agent.clone_for_user(user_context)  # line 1398
```

#### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit              # confirmed
from parrot.stores.kb.user import UserInfo                    # confirmed (stores/kb/user.py:11)
from parrot_tools.workday.tool import WorkdayToolkit          # confirmed
from parrot.integrations.telegram.context import telegram_chat_scope, current_telegram_chat_id  # confirmed
```

#### Key Attributes & Constants
- `UserInfo.search(...)` row → `employee_id` (= `associate_id`) and `manager_id` (parrot/stores/kb/user.py:52-53)
- `AbstractToolkit._pre_execute` receives `_permission_context` kwarg always (toolkit.py:174-179)
- `WorkdayToolkit.METHOD_TO_SERVICE_MAP` routes per-method WSDL (tool.py:110-157)

### Does NOT Exist (Anti-Hallucination)
- ~~a registered Workday `Agent`/bot~~ — **none exists anywhere** (confirmed in both ai-parrot and the private `navigator-plugins` repo). Phase 4 must create one **in the private repo, NOT in ai-parrot** (C8).
- ~~a `telegram_bots.yaml` entry for Workday~~ — does not exist yet; it belongs in the private repo alongside the agent (C8).
- ~~an existing HR/Workday agent in `navigator-plugins/docs`~~ — the `hr_agent` there is a retail/visit-info agent (NetworkNinja/foot-traffic), NOT Workday; `components/Workday/` is the legacy flowtask-style component, not an agent.
- ~~`WorkdayToolkit._pre_execute`~~ — not overridden today (FEAT-230 left identity explicit); Phase 5 adds it.
- ~~session-derived `worker_id` anywhere in `WorkdayToolkit`~~ — every method takes explicit `worker_id` (FEAT-230 Non-Goal).
- ~~live-tenant Workday tests~~ — FEAT-230's 50 tests are all mocked; no live verification exists.
- ~~a session/identity ContextVar reaching the toolkit~~ — only `current_telegram_chat_id` (chat scope) exists; an identity-bearing session ContextVar must be added.

---

## Parallelism Assessment

- **Internal parallelism**: **Spec A** (Phases 3+4) and **Spec B** (Phase 5) are
  largely separable. Spec A can land with explicit/SSO-bound `worker_id`; Spec B then
  makes identity implicit + enforces authorization. Within Spec A, the live-verification
  harness (Phase 3) and the agent+Telegram wiring (Phase 4) touch mostly disjoint files
  and could be parallel tasks; Spec B is concentrated in `WorkdayToolkit._pre_execute`.
- **Cross-feature independence**: depends on FEAT-230 (merged). Spec B shares
  `workday/tool.py` with any future Workday tool work — coordinate to avoid churn. The
  telegram integration files are shared with Jira/MCP telegram work (FEAT-109 lineage).
- **Recommended isolation**: **mixed** — two specs (A then B); within Spec A, Phase 3
  and Phase 4 may use separate worktrees; Spec B is per-spec (single worktree).
- **Rationale**: B depends on A being demonstrably working end-to-end; splitting keeps
  the security-sensitive identity/authorization change reviewable in isolation.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus/Juan*: `feature` on `dev`.
- [x] Phase 3 live-tenant access — *Owner: Jesus*: implementation tenant, `WORKDAY_*` creds already resolve from `parrot.conf`.
- [x] Phase 5 identity-resolution approach — *Owner: Jesus*: resolve in the toolkit via `_pre_execute` + session ContextVar (Option B).
- [x] Data-access policy — *Owner: Jesus*: own data + **first-level** direct reports.
- [x] Authorization enforcement point — *Owner: Jesus*: in the toolkit `_pre_execute`, fail-closed.
- [x] Write operations over Telegram — *Owner: Jesus*: self-only `request_my_time_off`, explicit in-chat confirmation before submit.
- [x] Authentication method — *Owner: Jesus*: Azure/OAuth2 SSO, fail-closed (no Workday tool without an authenticated session).
- [x] Program structure — *Owner: Jesus*: two specs — (A) Phase 3+4, (B) Phase 5.
- [x] Does a Workday agent already exist? — *Owner: Jesus/Juan*: No, none exists. It must be created.
- [ ] **Where exactly to create the Workday agent** (private repo — likely `navigator-plugins/docs`, but the precise repo/path/structure is **TBD, to be decided later**). The agent, its prompts, tenant config, and `telegram_bots.yaml` binding MUST NOT be committed to ai-parrot (C8) — *Owner: Jesus/Juan*.
- [ ] Exact SSO provider/config for the Workday Telegram bot (Azure AD tenant/app registration details) — *Owner: implementer (Spec A)*.
- [ ] Which `UserInfo.search` call shape resolves `worker_id` from `nav_user_id` (the existing signature takes `user_id: int`; confirm the session→`user_id` mapping) — *Owner: implementer (Spec B)*.
- [ ] How a manager references a report in chat (by name → `find_employee_id_by_name` → validate against `get_direct_reports`) and the exact denial UX — *Owner: implementer (Spec B)*.
- [ ] Whether Phase 3 verification runs in CI (gated on creds) or as a manual/recorded evidence run — *Owner: Jesus/implementer (Spec A)*.
