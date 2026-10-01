# TASK-3978: Build hook — apply_tooling_specs policy kwargs, bind_tooling_policy, hydrate_mcp hardening (M7 core, part 2)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3977
**Assigned-to**: unassigned
**Wave**: 1 (spec §9) · **Module**: M7 tenant-tooling-policy (core build hook)

---

## Context

Spec §2 "Build-hook plumbing" (RC-9): the storage builder must police a Studio agent's tooling at build, but
`configure()` calls `await self.apply_tooling_specs()` with **no arguments** (`bots/abstract.py:1524`) and must
keep doing so for every non-Studio bot. So `AbstractBot.bind_tooling_policy(policy, subject)` stores the policy
and subject on the bot, and `apply_tooling_specs(*, tooling_policy=None, tooling_subject=None)` resolves them
(explicit kwargs win) **before** the `_tooling_applied` short-circuit. `check_tool` runs before each class
construction; `resolve_mcp` runs between `hydrate_mcp` and `MCPServerConfig`. `hydrate_mcp` is hardened so vault
values fill only `MCP_SECRET_FIELDS`.

---

## Scope

- `parrot/tools/spec.py::hydrate_mcp`: any `secret_refs` key outside `MCP_SECRET_FIELDS` raises `ValueError`
  **before** the kwargs are returned (spec §2 "`hydrate_mcp` hardening").
- `parrot/interfaces/tools.py`:
  - add `bind_tooling_policy(self, policy, subject)` next to `apply_tooling_specs`; raises `RuntimeError` when
    `self._tooling_applied` is already True;
  - change `apply_tooling_specs` to `async def apply_tooling_specs(self, *, tooling_policy=None, tooling_subject=None) -> list[str]`;
    resolve policy/subject (explicit kwarg else bound value) **before** the `_tooling_applied` short-circuit;
    a subject with a tenant and no policy → `TenantToolingPolicy.deny_all()`; no subject → today's behaviour;
  - `policy.check_tool(spec.slug, subject=subject)` before resolving/constructing each toolkit class;
  - `kwargs = policy.resolve_mcp(kwargs, subject=subject)` between `hydrate_mcp` and `MCPServerConfig(**kwargs)`;
  - a refused spec is skipped, logged at `error` with its `ToolingRefusal`, never constructed/connected.
- Leave `bots/abstract.py:1524` (`await self.apply_tooling_specs()`) unchanged.
- Tests: `test_bind_tooling_policy_reaches_configure`, `test_hydrate_mcp_vault_fills_only_secret_fields`.

**NOT in scope**: `_resolve_spec_class` → resolver shim (TASK-3979); constructor server-managed fill
(TASK-3986); the storage builder's call to `bind_tooling_policy` (FEAT-621 W2); the build-time "fails
closed" agent refusal (storage §2.7 owns turning a refused spec into a build failure).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/spec.py` | MODIFY | hydrate_mcp: vault values fill only MCP_SECRET_FIELDS |
| `packages/ai-parrot/src/parrot/interfaces/tools.py` | MODIFY | bind_tooling_policy; apply_tooling_specs policy kwargs, check_tool, resolve_mcp |
| `packages/ai-parrot/tests/interfaces/test_tooling_policy_build_hook.py` | CREATE | test_bind_tooling_policy_reaches_configure |
| `packages/ai-parrot/tests/tools/test_hydrate_mcp_hardening.py` | CREATE | test_hydrate_mcp_vault_fills_only_secret_fields |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.mcp import MCPServerConfig  # interfaces/tools.py:11 (lazy export, mcp/__init__.py:38)
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec, hydrate_mcp, hydrate_params, tooling_revision  # interfaces/tools.py:14
from parrot.tools.spec import MCP_SECRET_FIELDS  # spec.py:18
from parrot.tools.tooling_policy import TenantToolingPolicy, TenantToolingRefused, ToolingSubject  # TASK-3977
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/interfaces/tools.py
class ToolInterface:  # :22 (mixin of AbstractBot)
    async def apply_tooling_specs(self) -> list[str]:  # :188  ← anchor (occurrences: 1)
        # _tooling_revision :192; short-circuit `if getattr(self, "_tooling_applied", False): return []` :193-194; set :195
        # toolkit loop :198-247: cls = self._resolve_spec_class(spec.slug) :200; hydrate_params :205;
        #   dataset_manager branch :206-230; cls(**filtered) :242
        # mcp loop :249-256: kwargs = await hydrate_mcp(mspec) :251 ← anchor (occurrences: 1); MCPServerConfig(**kwargs) :252

# packages/ai-parrot/src/parrot/bots/abstract.py:1524 (REFERENCE, unchanged)
                await self.apply_tooling_specs()

# packages/ai-parrot/src/parrot/tools/spec.py
async def hydrate_mcp(spec: AgentMCPServerSpec) -> dict[str, Any]:  # :185
    base.update(spec.params)  # :188 ← anchor (occurrences: 1) — spec §6 says :189 (drifted by one)
    # vault loop :189-195: grouped_fields by vault_name; base[field] = secrets[field]
```

### Does NOT Exist
- ~~`AbstractBot.bind_tooling_policy`~~, ~~`self._tooling_policy`~~, ~~`self._tooling_subject`~~ — created here (`grep -rn _tooling_policy packages` → 0).
- ~~a no-argument-incompatible change to `configure()`~~ — `bots/abstract.py:1524` must stay byte-identical.
- ~~`StudioAgentBuilder`~~ — FEAT-621 W2; it is the only caller of `bind_tooling_policy` (spec §2 step 4).
- ~~a policy check inside `hydrate_mcp`~~ — `hydrate_mcp` only refuses non-secret vault fields; policy runs in `apply_tooling_specs`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/spec.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/interfaces/tools.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/interfaces/test_tooling_policy_build_hook.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_hydrate_mcp_hardening.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface.apply_tooling_specs",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#hydrate_mcp",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#AgentMCPServerSpec"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Keep `apply_tooling_specs` "never raises" (docstring at :189): a `TenantToolingRefused` is caught per spec,
  logged with `self.logger.error("... refused: %s (%s)", exc.reason, exc.item)` and skipped.
- `apply_tooling_specs` is already long; extract `_resolve_tooling_binding(tooling_policy, tooling_subject)`
  returning `(policy | None, subject | None)` to stay within R4 budgets.
- Use the real bot pattern of `tests/interfaces/test_apply_tooling_specs.py` for the build-hook test; patch
  `asyncio.create_subprocess_exec` to fail if called (the `no_subprocess` fixture shape of spec §4).

### Cross-feature ordering
- Core `interfaces/tools.py`: **this task merges before FEAT-621 W2** (the storage `StudioAgentBuilder` calls
  `bot.bind_tooling_policy(...)`), then TASK-3979 / TASK-3986 serialise on the same file (package X16).

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Harden `hydrate_mcp` (raise on a non-secret vault field) — *why*: a vault value must never smuggle `command`/`transport`.
2. Add `bind_tooling_policy` next to `apply_tooling_specs` — *why*: RC-9, `configure()` is unchanged.
3. Change the `apply_tooling_specs` signature and resolve the binding before the short-circuit — *why*: spec step 2.
4. Insert `check_tool` before class resolution and `resolve_mcp` before `MCPServerConfig` — *why*: refuse before construction/connection.
5. Tests with mutation checks: ignore the bound values ⇒ `test_bind_tooling_policy_reaches_configure` RED.

### `packages/ai-parrot/src/parrot/tools/spec.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'base.update(spec.params)' spec.py)
# AFTER — insert below `    base.update(spec.params)` (verified: spec.py:188)
    foreign = sorted(field for field in spec.secret_refs if field not in MCP_SECRET_FIELDS)
    if foreign:
        # FEAT-622: vault values may fill only headers/auth_config/env; never transport/command/etc.
        raise ValueError(f"MCP secret_refs may only reference {MCP_SECRET_FIELDS}: {foreign}")
```
**Why**: raising before the vault read keeps it pure on refusal; `resolve_mcp` still refuses a vaulted `env` later.

### `packages/ai-parrot/src/parrot/interfaces/tools.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'async def apply_tooling_specs(self) -> list\[str\]:' interfaces/tools.py)
# REPLACE the signature line at interfaces/tools.py:188 and INSERT bind_tooling_policy above it:
    def bind_tooling_policy(self, policy: "TenantToolingPolicy | None", subject: "ToolingSubject") -> None:
        """Bind the build-time tenant tooling policy for the next ``configure()`` (FEAT-622, RC-9).

        Raises:
            RuntimeError: tooling was already applied; a late binding would police nothing.
        """
        if getattr(self, "_tooling_applied", False):
            raise RuntimeError("bind_tooling_policy() called after tooling specs were applied")
        self._tooling_policy = policy
        self._tooling_subject = subject

    async def apply_tooling_specs(
        self,
        *,
        tooling_policy: "TenantToolingPolicy | None" = None,
        tooling_subject: "ToolingSubject | None" = None,
    ) -> list[str]:
        """Hydrate and register pending toolkit / MCP specs once (FEAT-593). Never raises."""
        # FILL IN: policy, subject = self._resolve_tooling_binding(tooling_policy, tooling_subject)
        #   BEFORE the existing `_tooling_applied` short-circuit (:193) — bounded by spec "Build-hook plumbing" step 2
```
```python
# occurrences: 1 (verified: grep -c 'cls = self._resolve_spec_class(spec.slug)' interfaces/tools.py)
# BEFORE — insert above `                cls = self._resolve_spec_class(spec.slug)` (verified: interfaces/tools.py:200)
                if policy is not None:
                    policy.check_tool(spec.slug, subject=subject)
```
```python
# occurrences: 1 (verified: grep -c 'kwargs = await hydrate_mcp(mspec)' interfaces/tools.py)
# AFTER — insert below `                kwargs = await hydrate_mcp(mspec)` (verified: interfaces/tools.py:251)
                if policy is not None:
                    kwargs = policy.resolve_mcp(kwargs, subject=subject)
```
```python
# Both `except Exception` handlers (:246, :255): add a preceding
            except TenantToolingRefused as exc:
                self.logger.error("Tooling spec '%s' refused by tenant policy: %s", exc.item, exc.reason)
# FILL IN: _resolve_tooling_binding helper (explicit > bound; tenant subject + None policy → deny_all())
```
**Why**: explicit kwargs win, else the binding; a legacy bot has neither, so its build is exactly today's
(spec step 4). Import `TenantToolingPolicy`, `TenantToolingRefused`, `ToolingSubject` at module top
(`interfaces/tools.py` already imports `parrot.tools.discovery`; no cycle).

### FILL IN checklist
- [ ] `interfaces/tools.py::_resolve_tooling_binding` — precedence and `deny_all()` default; bounded by spec "Build-hook plumbing" step 2, X15.
- [ ] `interfaces/tools.py::apply_tooling_specs` — call the helper before the short-circuit; bounded by `test_bind_tooling_policy_reaches_configure`.

---

## Acceptance Criteria

- [ ] `bind_tooling_policy` exists on every `AbstractBot` (via `ToolInterface`) and raises `RuntimeError` after `_tooling_applied`.
- [ ] A bot bound with a tenant subject and `deny_all()` built through the unchanged `configure()` skips a stdio MCP spec: `asyncio.create_subprocess_exec` call count 0.
- [ ] An unbound bot builds exactly as today: `pytest packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py -q` pass unchanged.
- [ ] `hydrate_mcp` raises on a `secret_refs` key outside `MCP_SECRET_FIELDS`.
- [ ] `bots/abstract.py:1524` unchanged (`git diff` shows no change to `bots/abstract.py`).

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/interfaces/test_tooling_policy_build_hook.py -q`
- `pytest packages/ai-parrot/tests/tools/test_hydrate_mcp_hardening.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_apply_tooling_specs.py -q`
- `pytest packages/ai-parrot/tests/interfaces/test_configure_applies_tooling.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/interfaces/test_tooling_policy_build_hook.py
import pytest
from uuid import uuid4
from parrot.tools.spec import AgentMCPServerSpec
from parrot.tools.tooling_policy import TenantToolingPolicy, ToolingSubject


@pytest.mark.asyncio
async def test_bind_tooling_policy_reaches_configure(monkeypatch):
    """Tenant subject + deny_all(): stdio MCP spec skipped via the unchanged configure() path; no process;
    binding after _tooling_applied raises RuntimeError; unbound bot builds as today.
    Mutation: ignore the bound values in apply_tooling_specs ⇒ RED."""
    # FILL IN: no_subprocess patch on asyncio.create_subprocess_exec; real bot; _pending_mcp_specs=[stdio spec];
    #   bot.bind_tooling_policy(TenantToolingPolicy.deny_all(), ToolingSubject(tenant="acme", agent_id=uuid4(), actor=None, phase="build"))


# packages/ai-parrot/tests/tools/test_hydrate_mcp_hardening.py
@pytest.mark.asyncio
async def test_hydrate_mcp_vault_fills_only_secret_fields():
    """A secret_refs key outside MCP_SECRET_FIELDS raises before any vault read."""
    # FILL IN: spec with secret_refs={"command": "v"}; patch retrieve_vault_credential to fail if called
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Mutation evidence**: <for each new assertion: the code reverted, the test that went RED>

**Deviations from spec**: none | describe if any
