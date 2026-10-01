# TASK-3977: TenantToolingPolicy core — policy model, resolve_mcp, check_tool, enforce_tenant_tooling, registration (M7 core, part 1)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3975
**Assigned-to**: unassigned
**Wave**: 1 (spec §9) · **Module**: M7 tenant-tooling-policy (core)

---

## Context

Spec §1 P4 / review R1: declarative tenant tooling can start processes (stdio MCP via `params` smuggling,
`command`, auto-detected transport) and every built-in (`shell`, `python_execution`, `docker`, …) is open to
Studio authors. Spec §2 "Tenant tooling policy" defines the host-owned, frozen `TenantToolingPolicy`
(default `deny_all()`), applied to the **final normalised** configuration. This task delivers the pure,
synchronous policy module (no I/O): the model, `check_tool`, `resolve_mcp`, `check_tooling`,
`effective_mcp_config`, `set/get_tenant_tooling_policy` and `enforce_tenant_tooling` (THE write/activation
hook storage W2 calls). The build hook in `apply_tooling_specs` and the `hydrate_mcp` hardening are TASK-3978.

---

## Scope

- Create `parrot/tools/tooling_policy.py` with `TenantMCPTransport`, `HostMCPServer`, `ToolingSubject`,
  `ToolingRefusal`, `TenantToolingRefused`, `TenantToolingPolicy` (+ `deny_all()`, `check_tool`,
  `resolve_mcp`, `check_tooling`), `effective_mcp_config`, `set_tenant_tooling_policy`,
  `get_tenant_tooling_policy`, `enforce_tenant_tooling` — exactly the spec §2 "Data Models" / "New Public
  Interfaces" signatures.
- `mcp_endpoints` normalised at construction (scheme, lower-cased host, explicit port, path-segment boundary,
  userinfo refused) — a `field_validator`.
- `check_tool(slug, subject)`: resolver entry must exist (`toolkit_unavailable`); `source="host"` passes iff
  `host_toolkits`; `builtin` / `parrot_tools` / `walk` pass only when the slug is in `builtin_tools`
  (`builtin_not_permitted`). Plain tool names in `NormalizedTooling.tools` use the same check.
- `resolve_mcp(config, subject)`: the four ordered checks of spec §2 (named host server; local execution with
  transport resolved exactly like `MCPClient._detect_transport`; field allow-list; endpoint allow-list).
  Pure; returns the kwargs for `MCPServerConfig(**kwargs)`.
- `check_tooling(tooling, subject)`: `check_tool` per toolkit spec / plain tool; `resolve_mcp(effective_mcp_config(spec))`
  per MCP spec; at `write`/`activate`/`attach` any non-empty `secret_refs` / `vault_owner` supplied by the client
  or bundle → `secret_ref_not_permitted`; at `build` every `secret_refs` vault name must equal
  `toolkit_vault_name(spec.slug, ref)` / `mcp_vault_name(spec.name, ref)` with `ref = f"studio-agent:{subject.agent_id}"`
  (these helpers exist today in `parrot/tools/spec.py:59,64` and accept any string; storage M10 keeps the names, X17).
  NOTE: build-time `vault_owner` must equal the row owner — the subject carries no owner, so the check
  compares against an explicit `owner` keyword (FILL IN, see spec ambiguity below).
- Registration: `set_tenant_tooling_policy(app, policy)` stores under one AppKey-style key at most once
  (second call → `RuntimeError`); `get_tenant_tooling_policy(app)` → stored policy or `deny_all()`.
- `enforce_tenant_tooling(app, tooling, *, subject)`: no-op only when `subject.tenant is None` and not
  `policy.apply_to_global`; otherwise `policy.check_tooling(...)`.
- Unit tests: `test_policy_refuses_stdio_and_params_smuggling`, `test_policy_endpoint_allowlist_normalisation`,
  `test_policy_named_host_server_allows_host_stdio`, `test_policy_builtin_allowlist`,
  `test_policy_refuses_client_secret_refs`, `test_policy_registration_once_and_default_deny`.

**NOT in scope**: `apply_tooling_specs` / `bind_tooling_policy` / `hydrate_mcp` (TASK-3978); any server
handler wiring (TASK-3983/TK-10); storage services (FEAT-621 W2); the M9 re-verification of the vault-name
check against storage M10's final helpers (TASK-3988).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/tooling_policy.py` | CREATE | policy model, checks, registration, enforce_tenant_tooling |
| `packages/ai-parrot/tests/tools/test_tooling_policy.py` | CREATE | M7 policy unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.spec import (  # spec.py
    AgentMCPServerSpec,   # :32
    MCP_SECRET_FIELDS,    # :18  ("headers", "auth_config", "env")
    NormalizedTooling,    # :50
    SECRET_MASK,          # :17
    ToolkitSpec,          # :21
    mcp_vault_name,       # :64  f"mcp_agent_{server}_{agent_name}"
    toolkit_vault_name,   # :59  f"toolkit_{slug}_{agent_name}"
)
from parrot.tools.resolver import get_toolkit_resolver  # created by TASK-3975
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/spec.py
class AgentMCPServerSpec(BaseModel):  # :32 — extra="forbid"
    name: str; transport: str = "http"; url: str | None = None; command: str | None = None
    args: list[str] = []; allowed_tools: list[str] | None = None; blocked_tools: list[str] | None = None
    description: str | None = None; auth_type: str | None = None
    params: dict[str, Any] = {}; secret_refs: dict[str, str] = {}; vault_owner: str | None = None
class NormalizedTooling(BaseModel):  # :50 — tools: list[Any]; toolkits: list[ToolkitSpec]; mcp_servers: list[AgentMCPServerSpec]
async def hydrate_mcp(spec) -> dict  # :185 — dump(exclude params/secret_refs/vault_owner, exclude_none) → update(params) :188 → vault fields :190-195

# packages/ai-parrot/src/parrot/mcp/integration.py — transport detection to mirror exactly
def _detect_transport(self) -> str:  # :374-390
    # transport != "auto" → transport; socket_path → "unix"; url → "sse" if "events"/"sse" in url else "http";
    # command → "stdio"; else ValueError
# packages/ai-parrot/src/parrot/mcp/client.py:133 class MCPClientConfig — transport default "auto" (:177), env (:163), socket_path (:181)

# TASK-3975 (resolver.py)
class ToolkitEntry(BaseModel, frozen=True): slug; dotted_path: str | None; source: Literal["builtin","parrot_tools","host","walk"]
def get_toolkit_resolver() -> ToolkitResolver   # .entry(slug) -> ToolkitEntry | None
```

### Does NOT Exist
- ~~any transport or command restriction on agent MCP specs~~ — none today (`spec.py:32`, `tooling_store.py:204`).
- ~~`TenantToolingPolicy`, `enforce_tenant_tooling`, `ToolingSubject`, `TenantToolingRefused`~~ — created here.
- ~~`parrot.mcp.integration.detect_transport` as a module function~~ — `_detect_transport` is a private **method** of `MCPClient`; re-implement the same 5-line rule as a pure function, do not instantiate a client.
- ~~`toolkit_override_vault_name`, `agent_tooling_ref`, `ToolingState.tooling_ref`~~ — storage M10/M13 (FEAT-621), not needed here.
- ~~`web.AppKey` usage requirement~~ — `app` is a plain `Mapping` (spec §7: core takes `app` as a Mapping); use a module-level string key constant.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/tooling_policy.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_tooling_policy.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#AgentMCPServerSpec",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#NormalizedTooling",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#ToolkitSpec",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#toolkit_vault_name",
    "sym:packages/ai-parrot/src/parrot/tools/spec.py#mcp_vault_name",
    "sym:packages/ai-parrot/src/parrot/mcp/integration.py#MCPClient._detect_transport"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Frozen Pydantic model; every check is a pure function (spec §7) so storage can call it inside a DB
  transaction with no I/O.
- Field allow-list (check 3): `name, url, transport, description, allowed_tools, blocked_tools, auth_type,
  headers, auth_config, timeout`; callables (`header_provider`, `token_supplier`) never come from a spec.
- Named host server (check 1): keys other than `name`, the server's `tenant_fields`, and fields **equal to the
  `AgentMCPServerSpec` defaults** must be absent; returns `{**host.config, **tenant_fields_supplied, "name": name}`.
  `effective_mcp_config` dumps the spec with `exclude_none=True`, so `transport="http"` and `args=[]` (defaults)
  are present and must be ignored — compare against `AgentMCPServerSpec.model_fields[...]` defaults.
- `effective_mcp_config(spec)` = exactly what `hydrate_mcp` returns minus the vault read: top-level dump, then
  `params`, then each `secret_refs` key present with value `SECRET_MASK`. Keep it in sync with `hydrate_mcp`
  (`spec.py:185-196`); TASK-3978 hardens `hydrate_mcp` in the same spirit.
- Keep each function ≤ 60 lines / complexity ≤ 10: split `resolve_mcp` into `_check_named_host`,
  `_check_local_execution`, `_check_fields`, `_check_endpoint`.

### Spec ambiguity (record in Completion Note)
- §3 places "the build-time vault-name check" in M9's path, while §4 lists it in the M7 test
  `test_policy_refuses_client_secret_refs`. This task implements it now with today's `spec.py` helpers
  (already ref-agnostic, so no sibling dependency); TASK-3988 (M9) re-verifies it against storage M10.
- "vault_owner must equal the row owner" at build: `ToolingSubject` has no owner field. Add a keyword-only
  `owner: str | None = None` to `check_tooling` (not to the frozen subject) and FILL IN; do not change
  `ToolingSubject`'s fields (package X18 freezes them).

### Cross-feature ordering
- Wave 1, no sibling dependency. This module merges **before FEAT-621 W2**: storage's `StudioToolingGate`,
  `StudioToolingService`, `StudioAgentService` and `StudioDraftService` call `enforce_tenant_tooling` (X15, X18).

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
1. Create the module from the block; keep the public names verbatim — *why*: FEAT-621 W2 and FEAT-605 C35/C36 import them.
2. Fill `_check_*` helpers in the spec order — *why*: the order decides the refusal reason the tests assert.
3. Fill `check_tooling` phase handling — *why*: client-supplied `secret_refs` must never be accepted on write/activate/attach (X18).
4. Write the six unit tests; mutation-check (e.g. drop the `params` overlay in `effective_mcp_config` → smuggling test RED).

### `packages/ai-parrot/src/parrot/tools/tooling_policy.py` (CREATE)
```python
"""Host-owned tenant tooling policy (FEAT-622 M7, review R1). Pure and synchronous: no I/O."""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, field_validator

from parrot.tools.resolver import get_toolkit_resolver
from parrot.tools.spec import (
    SECRET_MASK, AgentMCPServerSpec, NormalizedTooling, mcp_vault_name, toolkit_vault_name,
)

TenantMCPTransport = Literal["http", "sse", "streamable-http"]
ToolingRefusal = Literal[
    "local_execution", "transport_not_permitted", "endpoint_not_allowed", "mcp_server_unknown",
    "field_not_permitted", "secret_ref_not_permitted", "builtin_not_permitted", "toolkit_unavailable",
]
_POLICY_KEY = "parrot.tenant_tooling_policy"
_TENANT_MCP_FIELDS = frozenset({
    "name", "url", "transport", "description", "allowed_tools", "blocked_tools",
    "auth_type", "headers", "auth_config", "timeout",
})
_LOCAL_FIELDS = ("command", "args", "env", "socket_path")


class TenantToolingRefused(Exception):
    """Raised when tenant tooling is not permitted (HTTP 422 on writes/assign, 403 on execute)."""

    code: ClassVar[str] = "tooling_not_permitted"

    def __init__(self, reason: ToolingRefusal, *, item: str) -> None:
        self.reason: ToolingRefusal = reason
        self.item = item
        super().__init__(f"{self.code}: {reason} ({item})")


class HostMCPServer(BaseModel, frozen=True):
    name: str
    config: dict[str, Any]
    tenant_fields: frozenset[str] = frozenset({"allowed_tools", "blocked_tools", "description"})


class ToolingSubject(BaseModel, frozen=True):
    tenant: str | None
    agent_id: UUID | None
    actor: str | None
    phase: Literal["write", "activate", "build", "attach", "execute"]


class TenantToolingPolicy(BaseModel, frozen=True):
    mcp_servers: Mapping[str, HostMCPServer] = {}
    mcp_endpoints: tuple[str, ...] = ()
    mcp_transports: frozenset[TenantMCPTransport] = frozenset({"http", "sse", "streamable-http"})
    builtin_tools: frozenset[str] = frozenset()
    host_toolkits: bool = True
    apply_to_global: bool = False

    @field_validator("mcp_endpoints")
    @classmethod
    def _normalise_endpoints(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        # FILL IN: absolute https prefixes only; lower-case host, explicit port, trailing "/" segment
        #   boundary, reject userinfo — bounded by test_policy_endpoint_allowlist_normalisation
        raise NotImplementedError

    @classmethod
    def deny_all(cls) -> "TenantToolingPolicy":
        """Host toolkits only, no MCP, no built-ins."""
        return cls()

    def check_tool(self, slug: str, *, subject: ToolingSubject) -> None:
        entry = get_toolkit_resolver().entry(slug)
        if entry is None:
            raise TenantToolingRefused("toolkit_unavailable", item=slug)
        if entry.source == "host":
            if not self.host_toolkits:
                raise TenantToolingRefused("builtin_not_permitted", item=slug)  # FILL IN: confirm reason with spec §2
            return
        if slug.lower() not in {name.lower() for name in self.builtin_tools}:
            raise TenantToolingRefused("builtin_not_permitted", item=slug)

    def resolve_mcp(self, config: Mapping[str, Any], *, subject: ToolingSubject) -> dict[str, Any]:
        """Spec §2 checks 1–4 on the FINAL kwargs; returns MCPServerConfig kwargs."""
        name = str(config.get("name", ""))
        if name in self.mcp_servers:
            return self._check_named_host(self.mcp_servers[name], config)
        self._check_local_execution(config)
        self._check_fields(config)
        self._check_endpoint(config)
        return dict(config)

    def check_tooling(
        self, tooling: NormalizedTooling, *, subject: ToolingSubject, owner: str | None = None
    ) -> None:
        # FILL IN: check_tool per toolkit spec slug and per str in tooling.tools; resolve_mcp(effective_mcp_config(s))
        #   per MCP spec; phase write/activate/attach → any secret_refs/vault_owner → secret_ref_not_permitted;
        #   phase build → every vault name == toolkit_vault_name(slug, ref) / mcp_vault_name(name, ref),
        #   ref = f"studio-agent:{subject.agent_id}", and vault_owner == owner — bounded by test_policy_refuses_client_secret_refs
        raise NotImplementedError

    # FILL IN: _check_named_host, _check_local_execution (transport resolved like MCPClient._detect_transport;
    #   stdio/unix → local_execution; outside mcp_transports → transport_not_permitted), _check_fields,
    #   _check_endpoint — one helper per spec check, each ≤ 60 lines


def effective_mcp_config(spec: AgentMCPServerSpec) -> dict[str, Any]:
    """Exactly what hydrate_mcp returns, minus the vault read (secret fields → SECRET_MASK)."""
    base = spec.model_dump(exclude={"params", "secret_refs", "vault_owner"}, exclude_none=True)
    base.update(spec.params)
    for field in spec.secret_refs:
        base[field] = SECRET_MASK
    return base


def set_tenant_tooling_policy(app: MutableMapping[str, Any], policy: TenantToolingPolicy) -> None:
    """Register the host policy once, before startup completes."""
    if _POLICY_KEY in app:
        raise RuntimeError("tenant tooling policy already registered")
    app[_POLICY_KEY] = policy


def get_tenant_tooling_policy(app: Mapping[str, Any]) -> TenantToolingPolicy:
    """Registered policy, or ``deny_all()`` when the host registered nothing."""
    policy = app.get(_POLICY_KEY)
    return policy if isinstance(policy, TenantToolingPolicy) else TenantToolingPolicy.deny_all()


def enforce_tenant_tooling(app: Mapping[str, Any], tooling: NormalizedTooling, *, subject: ToolingSubject) -> None:
    """THE write/activation hook: raises TenantToolingRefused; pure, no I/O."""
    policy = get_tenant_tooling_policy(app)
    if subject.tenant is None and not policy.apply_to_global:
        return
    policy.check_tooling(tooling, subject=subject)
```
**Why this shape**: public names and `ToolingRefusal` values are frozen by package X15/X18 and consumed by
FEAT-621 and FEAT-605 — do not rename. Note `host_toolkits=False` refusal reason is not named by the spec;
use `builtin_not_permitted` only if no better listed value applies and record it.

### FILL IN checklist
- [ ] `_normalise_endpoints` — normalisation rules; bounded by `test_policy_endpoint_allowlist_normalisation`.
- [ ] `check_tool` — reason when `host_toolkits=False`; bounded by the spec's `ToolingRefusal` list (no new values).
- [ ] `check_tooling` — phase handling, build-time namespace + owner; bounded by `test_policy_refuses_client_secret_refs`, X17.
- [ ] `_check_named_host` / `_check_local_execution` / `_check_fields` / `_check_endpoint` — spec §2 checks 1–4 in order.

---

## Acceptance Criteria

- [ ] All public names of spec §2 exist with the exact signatures; `TenantToolingRefused.code == "tooling_not_permitted"`.
- [ ] stdio (explicit, auto-detected via `params.command`, inside `params`), `socket_path`, non-empty `args`/`env`, `secret_refs={"command": ...}` → `local_execution` / `field_not_permitted` as the spec orders them.
- [ ] Endpoint normalisation: `https://mcp.host/api/` allows `https://MCP.host:443/api/x`; refuses `/apix`, userinfo, `http://`, missing url.
- [ ] Named `HostMCPServer` with stdio config passes with tenant fields only; adding `url`/`command` → `field_not_permitted`.
- [ ] Under `deny_all()`: `shell`, `python_execution`, `docker` refused; `wiki` passes when listed; host toolkit passes; walked slug treated as built-in.
- [ ] Second `set_tenant_tooling_policy` raises `RuntimeError`; unset → `deny_all()`.
- [ ] `enforce_tenant_tooling` is a no-op for `tenant=None` unless `apply_to_global`.
- [ ] No I/O anywhere in the module (no vault, no network, no subprocess). `flake8` clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_tooling_policy.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_tooling_policy.py
import pytest
from uuid import uuid4
from parrot.tools.spec import AgentMCPServerSpec, NormalizedTooling, ToolkitSpec
from parrot.tools.tooling_policy import (
    HostMCPServer, TenantToolingPolicy, TenantToolingRefused, ToolingSubject,
    effective_mcp_config, enforce_tenant_tooling, get_tenant_tooling_policy, set_tenant_tooling_policy,
)
from ._host_probe import host_plugins  # noqa: F401

SUBJECT = ToolingSubject(tenant="acme", agent_id=uuid4(), actor="u1", phase="write")


@pytest.mark.parametrize("raw, reason", [
    # FILL IN: transport="stdio"; transport="http"+params={"transport":"stdio","command":"sh"};
    #   params={"command":"sh"} with default auto; params={"socket_path":...}; args/env non-empty;
    #   secret_refs={"command": ...}
])
def test_policy_refuses_stdio_and_params_smuggling(raw, reason): ...

def test_policy_endpoint_allowlist_normalisation(): ...
def test_policy_named_host_server_allows_host_stdio(): ...
def test_policy_builtin_allowlist(host_plugins): ...
def test_policy_refuses_client_secret_refs(): ...   # activate: client secret_refs/vault_owner; build: foreign/bare vault names
def test_policy_registration_once_and_default_deny(): ...
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
