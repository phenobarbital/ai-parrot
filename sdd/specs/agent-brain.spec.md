---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [memory, dream-cycle, brain, multi-tenant, pbac]
docs:
  policy: required
  pages:
    - wiki/memory/agent-brain.md
    - wiki/memory/dream-cycle.md
  api_modules:
    - parrot.memory.dream
---

# Feature Specification: Agent's Brain — an operational, tenant-scoped brain for any agent

**Feature ID**: FEAT-889
**Date**: 2026-11-13
**Author**: Jesus Lara, with Claude
**Status**: draft
**Target version**: next release after `AgentMemoryMixin` lands on `dev`; release number unassigned

> **Decomposition gate.** This spec is the sibling of the memory-unification spec
> (design input: [`sdd/proposals/agent-memory-mixin.design.md`](../proposals/agent-memory-mixin.design.md),
> destination class `AgentMemoryMixin`). **Do not run `/sdd-task` on this spec, and do not launch a
> worker, until `AgentMemoryMixin` is merged into `dev`.** Phase 2 has a second gate, stated in §3.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-390 (`dream-cycle-brain-consolidation`) shipped a brain: a per-agent LLM wiki that a periodic
"dream cycle" fills by distilling episodic memory, and that is fed back into `ask()`. The code is
complete and tested, but it is not operational: no agent uses it and it has never run outside tests.
An inspection of `dev` at `58ec71d179` found six defects that block real use.

1. **Scope.** The brain is keyed by agent only (`~/.parrot/brains/<agent_id>`), and the tenant it
   records is the static attribute of the agent instance, not the tenant of the request. One agent
   instance serving several tenants mixes them in a single brain.
2. **Eligibility.** Every conversation turn is recorded as `QUERY_RESOLUTION` / `PARTIAL`, which gets
   importance 5, exactly the cycle's threshold, plus a generic heuristic lesson. Every turn is
   therefore eligible, and the brain fills with noise.
3. **Personal data.** The cycle distills whatever the episodes contain. With user memory enabled in
   the same agent, personal content flows into a brain that is injected for other users.
4. **Several workers.** The cycle lock is a pair of flags in a JSON file. Two gunicorn workers each
   start a scheduler on the same state file; the design declares that case unsupported.
5. **Exposure.** Brain pages are injected into the prompt of every request, and nothing limits who
   may inspect the brain as a whole. There is also no operator surface: no way to list pages, read
   a cycle report or trigger a cycle.
6. **Forgetting.** When a user asks to be forgotten, pages already distilled from that user's
   episodes stay in the brain.

Separately, FEAT-571 (`memory-dynamics`) defined **M4 — Brain and Dream Cycle** (page state and
versions, verified promotion, recoverable forgetting, re-distillation). M4 is undecomposed and edits
the same files as the six fixes above. The owner decided to move M4 into this spec so that the
`memory/dream/` package has a single owner.

### Goals

- A brain that any agent can turn on and that is safe to leave on: scoped by the tenant of the
  request, fed only by episodes that carry evidence, free of personal data, with one scheduler per
  agent across worker processes.
- The brain is never handed over wholesale to whoever asks. Bulk inspection is an administrator
  operation, gated by PBAC.
- One facade (`BrainService`) is the only thing the integration layer needs to know. The mixin does
  not construct stores, runners or schedulers.
- Phase 2 delivers FEAT-571 M4 here, keeping its gates and contracts.

### Non-Goals (explicitly out of scope)

- **Wiring.** The `enable_brain` flag on `Agent()` / `BasicAgent`, the rule that the brain implies an
  episodic store, the lifecycle calls, the `ask()` / `ask_stream()` hooks and the resolution of the
  request tenant belong to the unification spec. They are listed in §2 as incoming requirements.
- User memory (`enable_user_memory`, `UserKnowledge`), and FEAT-571 M1, M2, M3, M5 and M6.
- Brain storage shared between hosts or containers. The brain stays on the local filesystem; the
  scheduler lease in this spec is single-host by construction.
- Per-user brains. The scope is `(tenant, agent)`; knowledge about one person is user memory.
- Migrating brains written by FEAT-390. They are left in place and never read in scoped mode (§7).
- Promotion to a wiki shared between agents, in Phase 1. It returns in Phase 2 with a verified
  criterion (M9). Phase 1 has no organisation brain and no cross-agent sharing.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:9ebb45c12de6c3b629d29f04ae976cb43c8b82828c6e28dd7ee901ed8da1a946 evaluation_digest=sha256:4c4c47efe623b91af9909adc27e19d6a47d4d4822d7b7c59597cdeb8a00d5aed rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

The cut between this spec and the unification spec is by **file ownership**.

| | Unification spec (`AgentMemoryMixin`) | This spec (FEAT-889) |
|---|---|---|
| Owns | the mixin, the `ask()` / `ask_stream()` hooks, `BasicAgent`, `memory/unified/*`, user memory | `memory/dream/*`, the administrator toolkit, the brain PBAC policy |
| Decides | flags and kwargs, lifecycle, what is injected and when, the tenant of the request | scope and partitioning, eligibility, distillation rules, the scheduler lease, promotion, derived-page forgetting |

The contract between them is one class, `BrainService`:

- The mixin builds one `BrainService` per agent, calls `start()` and `stop()`, and calls
  `search(query, tenant_id)` on the read path with the server-resolved tenant.
- `BrainService` owns everything else: it resolves a `BrainStore` per `(tenant, agent)` scope, runs
  one scheduler per agent guarded by a file lease, and exposes the administrator toolkit.

**Phase 1** makes the existing design correct and operable, with no dependency on FEAT-571 gates.
**Phase 2** replaces cycle-count evidence with FEAT-571 dynamics (M4).

#### Storage layout (Phase 1)

```
<brain_root>/                      # default ~/.parrot/brains/<agent_id>, unchanged
├── dream.lock                     # scheduler lease (flock)
├── tenants/
│   └── <tenant_id>/
│       ├── wiki.db                # the scope's brain
│       └── dream_state.json       # the scope's watermark and schedule
├── wiki.db                        # LEGACY (FEAT-390): left in place, never read or written
└── dream_state.json               # LEGACY
```

A scope directory is created the first time the scope is resolved, on the read path or the write
path. The set of directories under `tenants/` is the set of scopes the scheduler visits, so it
survives a restart without any registry file.

#### Eligibility (Phase 1)

An episode is eligible for consolidation when **all** of these hold:

1. It is not already consolidated (`"consolidated_into"` absent from its metadata).
2. Its category is not in `DreamConfig.excluded_categories` (default: `user_preference`).
3. It is not an unverified conversation turn — category `query_resolution` with outcome `partial` —
   unless `DreamConfig.include_unverified_turns` is true (default false).
4. Its importance is at least `importance_threshold`, or it carries a non-empty `lesson_learned`.

Rule 3 follows FEAT-571 M0: a conversation turn has no verified outcome, so it is not evidence.
Rule 2 keeps personal preferences out of a shared brain.

#### Distillation without personal data (Phase 1)

- The distill prompt forbids names, identifiers, contact data and anything about a specific person,
  and asks the model to report `personal_data: true` when it could not comply.
- A group whose result reports `personal_data: true` is not archived. Its episodes are not marked
  consolidated and the group is counted in the report.
- With no LLM client, the heuristic path uses `lesson_learned` only. A group with no lessons is
  skipped; the raw `situation` / `action_taken` text is never copied into a page.
- The title and body of every page pass through `redact_text` before they are archived, whether or
  not the agent sets `enable_redaction`. Tool episodes can carry keys and tokens in their arguments.

#### One scheduler per agent (Phase 1)

`SchedulerLease` takes a non-blocking exclusive `flock` on `<brain_root>/dream.lock`. The process
that holds it runs the loop. The others stay on standby and retry every
`DreamConfig.lease_retry_seconds`; the kernel releases the lock when its holder exits, so a standby
takes over without stale-lock heuristics. The `running` / `running_since` flags remain as crash
evidence in the state file but no longer decide who runs.

Each wake-up, the holder visits every known scope whose `next_due` has passed, in sequence.

#### Exposure (Phase 1)

- The read path returns only the pages of the request's scope, packed under the existing token
  budget. With eligibility and distillation fixed, what a user can coax out of the agent is
  operational knowledge of their own tenant.
- `BrainAdminToolkit` is the only way to inspect a brain as a whole, and it is **mounted only when
  allowed**. It is never registered on the agent's own `ToolManager`. On each request the agent HTTP
  handler asks PBAC whether the user may execute `tool:brain_admin_*`; if so it registers the
  toolkit on the session-scoped `ToolManager`, and in every other case — denied, PBAC not
  configured, an error, no session-scoped manager — it makes sure those tools are absent. Channels
  that do not go through that handler never receive it.
- `policies/tools.yaml` denies `tool:brain_admin_*` to everyone outside the `superuser` group, at a
  priority above `devops_all_tools` (which allows `tool:*` at priority 30).

#### Forgetting derived pages (Phase 1)

`BrainService.forget_derived(tenant_id, episodes)` deletes every page named by the
`"consolidated_into"` metadata of the given episodes. The page is deleted whole, even when other
episodes contributed to it; the remaining source episodes are not re-distilled in Phase 1 (they sit
behind the watermark). Phase 2 replaces deletion with re-distillation from the remaining sources.

### Component Diagram

```
AgentMemoryMixin  (unification spec)
      │  start() / stop() / search(query, tenant_id) / forget_derived(...)
      ▼
BrainService ──→ BrainRegistry ──→ BrainStore  (one per tenant scope)
      ├──→ SchedulerLease  (flock on dream.lock)
      ├──→ DreamScheduler ──→ DreamCycleRunner (one per scope per cycle)
      │                              │
      │                              ├──→ is_eligible()        (eligibility.py)
      │                              └──→ EpisodicMemoryStore  (existing)
      └──→ BrainAdminToolkit  ◀── mounted per request by the agent HTTP handler, only when PBAC allows
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BrainStore` | modifies | adds page listing, reading and deletion |
| `DreamCycleRunner` | modifies | scoped collection, eligibility, privacy rules |
| `DreamScheduler` | modifies | lease, per-scope state, runner factory |
| `EpisodicMemoryStore` | uses | unchanged; collection still reaches `_backend.get_recent` |
| `parrot.skills.tenancy.validate_tenant_id` | uses | tenant ids become path segments |
| `parrot.utils.paths.secure_path` | uses | scope directories cannot escape the brain root |
| `AbstractToolkit`, `requires_permission` | uses | administrator toolkit |
| `parrot.security.redaction.redact_text` | uses | scrubs distilled text before archiving |
| `AgentTalk` handler (`handlers/agent.py`) | modifies | mounts or removes the administrator tools per request |
| `policies/tools.yaml` | modifies | deny rule for `tool:brain_admin_*` |

#### Incoming requirements (owned by the unification spec)

These are not implemented here. This spec is correct only if the unification spec delivers them.

| # | Requirement | Evidence of the gap today |
|---|---|---|
| R1 | `enable_brain` is a constructor flag any `Agent` can set | activation needs inheriting `LongTermMemoryMixin` and calling two methods by hand |
| R2 | `enable_brain` implies an episodic store; no second flag is required | `mixin.py:124`, `mixin.py:198` |
| R3 | `BrainService.start()` runs in `configure()` and `stop()` in `shutdown()`, idempotently | nothing in `bots/` calls `_configure_long_term_memory` |
| R4 | The tenant passed to `search()` and recorded on episodes is the server-resolved request tenant | `manager.py:381` records `self.namespace.tenant_id` |
| R5 | `ask_stream()` reads and records memory like `ask()` | only `base.py:1406` and `base.py:1819` do |
| R6 | The unified manager calls `BrainService.search()` and holds no `BrainStore` | `manager.py:91`, `manager.py:327` |
| R7 | The user-memory `forget` operation calls `BrainService.forget_derived()` | no caller exists |
| R8 | Tool and outcome episodes are recorded on the unified path | without them nothing is eligible under rule 3 |
| R9 | Nothing registers `BrainAdminToolkit` on the agent's own `ToolManager`; mounting is done only by the handler (M6) | — |
| R10 | The mixin exposes the service as `self.brain_service` (`BrainService \| None`) so the handler can reach it | no such attribute exists |

### Data Models

```python
class BrainScope(BaseModel):
    """Identity of one brain: the tenant of the request and the agent."""
    model_config = ConfigDict(frozen=True)
    tenant_id: str
    agent_id: str

class DreamConfig(BaseModel):          # existing — new fields only
    excluded_categories: list[str] = ["user_preference"]
    include_unverified_turns: bool = False
    lease_retry_seconds: int = 300

class DistilledKnowledge(BaseModel):   # existing — new field only
    personal_data: bool = False

class DreamCycleReport(BaseModel):     # existing — new fields only
    tenant_id: str | None = None
    groups_rejected_privacy: int = 0
```

### New Public Interfaces

```python
class BrainService:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def search(self, query: str, tenant_id: str, max_tokens: int = 600) -> str: ...
    async def run_now(self, tenant_id: str | None = None) -> list[DreamCycleReport]: ...
    async def forget_derived(self, tenant_id: str, episodes: Sequence[EpisodicMemory]) -> list[str]: ...
    def admin_toolkit(self) -> BrainAdminToolkit: ...
```

---

## 3. Module Breakdown

Phase 1 is modules M1–M7. Phase 2 is modules M8–M9.

> **Phase 2 gate.** M8 and M9 are not eligible for decomposition until (a) the FEAT-571 gates G1,
> G2 and G4 are accepted by the owner, and (b) the dynamics model (FEAT-571 M1) and the review
> storage protocol (FEAT-571 M2), delivered by the unification spec, have frozen interfaces on
> `dev`. `/sdd-task` decomposes Phase 1 first and Phase 2 in a later run.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: scope and registry | yes | layout, signatures and validation fixed in §2 and below | — |
| M2: eligibility | yes | four rules fixed in §2 | — |
| M3: runner | yes | prompt clause, skip rules and report fields fixed | — |
| M4: lease and scheduler | yes | `flock` protocol and standby retry fixed | — |
| M5: service | yes | facade signatures fixed | — |
| M6: admin toolkit, mount and policy | yes | tool names, mount/unmount rule and policy rule fixed below | — |
| M7: documentation | yes | pages named in §10 | — |
| M8: page state and versions | no | — | blocked by G4 and G2 |
| M9: dynamics in the cycle | no | — | blocked by G1 and the M1/M2 interfaces |

### Module 1: Scope and registry
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/scope.py` (new),
  `packages/ai-parrot/src/parrot/memory/dream/brain.py` (modify)
- **Responsibility**: Map a `(tenant, agent)` scope to a contained directory and a cached
  `BrainStore`; list known scopes; add the page operations the service and toolkit need.
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/dream/scope.py  (new)
  TENANTS_DIRNAME: Final[str] = "tenants"

  class BrainScope(BaseModel):
      """Identity of one brain: the request tenant and the agent."""

  def scope_dir(brain_root: Path, tenant_id: str) -> Path:
      """Return brain_root/tenants/<tenant_id>, contained in brain_root.

      Raises:
          ValueError: if tenant_id is unsafe or reserved, or the path escapes brain_root.
      """
      # validate_tenant_id verified: packages/ai-parrot/src/parrot/skills/tenancy.py:45
      # secure_path verified: packages/ai-parrot/src/parrot/utils/paths.py:52

  def has_legacy_brain(brain_root: Path) -> bool:
      """True when a FEAT-390 un-scoped wiki.db sits directly under brain_root."""

  class BrainRegistry:
      """Resolves and caches one BrainStore per tenant for a single agent."""
      def __init__(self, brain_root: Path, agent_id: str) -> None: ...
      def get(self, tenant_id: str) -> BrainStore:
          """Return the scope's store, creating its directory on first use."""
      def known_tenants(self) -> list[str]:
          """Tenant ids with a directory under brain_root/tenants, sorted."""

  # packages/ai-parrot/src/parrot/memory/dream/brain.py  (modifies brain.py:21)
  class BrainStore:  # verified: packages/ai-parrot/src/parrot/memory/dream/brain.py:21
      async def list_pages(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
          """Page stubs without bodies. Never raises; [] on error."""
          # BaseWikiStore.list_pages verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:941
      async def get_page(self, page_id: str) -> dict[str, Any] | None:
          """One page with its body, or None."""
          # BaseWikiStore.get_page verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:938
      async def delete_pages(self, page_ids: Sequence[str]) -> list[str]:
          """Delete the given pages; return the ids actually deleted."""
          # BaseWikiStore.delete_page verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:931
  ```

### Module 2: Eligibility
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/eligibility.py` (new),
  `packages/ai-parrot/src/parrot/memory/dream/models.py` (modify)
- **Responsibility**: The pure eligibility predicate and its configuration.
- **Depends on**: nothing in this spec
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/dream/eligibility.py  (new)
  def is_eligible(episode: EpisodicMemory, config: DreamConfig) -> bool:
      """Apply the four rules of §2 "Eligibility". Pure; never raises."""
      # EpisodicMemory.outcome verified: packages/ai-parrot/src/parrot/memory/episodic/models.py:109
      # EpisodicMemory.category verified: packages/ai-parrot/src/parrot/memory/episodic/models.py:134
      # EpisodicMemory.metadata verified: packages/ai-parrot/src/parrot/memory/episodic/models.py:164

  # packages/ai-parrot/src/parrot/memory/dream/models.py  (modifies models.py:58, :87, :103)
  class DreamConfig(BaseModel):  # verified: packages/ai-parrot/src/parrot/memory/dream/models.py:58
      excluded_categories: list[str]
      include_unverified_turns: bool
      lease_retry_seconds: int
  class DistilledKnowledge(BaseModel):  # verified: models.py:87
      personal_data: bool
  class DreamCycleReport(BaseModel):  # verified: models.py:103
      tenant_id: str | None
      groups_rejected_privacy: int
  ```

### Module 3: Runner — scoped collection and privacy
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/runner.py` (modify)
- **Responsibility**: Collect with `is_eligible`; apply the privacy rules; stamp the report with the
  tenant. The runner's constructor is unchanged: it already receives the namespace and the store of
  one scope.
- **Depends on**: M2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/dream/runner.py
  DISTILL_PROMPT = ...  # modifies runner.py:22 — adds the personal-data clause and the
                        # "personal_data" response field

  class DreamCycleRunner:  # verified: packages/ai-parrot/src/parrot/memory/dream/runner.py:71
      async def _collect(self, state: DreamState) -> list[EpisodicMemory]:  # modifies runner.py:235
          """Eligible episodes of this runner's namespace since the watermark, oldest first."""
      @staticmethod
      def _heuristic_distill(group: list[EpisodicMemory]) -> DistilledKnowledge | None:  # modifies runner.py:474
          """Lessons only. Returns None when the group carries no lesson."""
  ```
  `run_cycle` (runner.py:105) treats a `None` result and a `personal_data=True` result the same way
  as a failed distill for watermark purposes: the group stays pending. Before `self._brain.remember`
  (runner.py:166) the title and body pass through `redact_text`. The promotion block (runner.py:196)
  is left in place but unreachable in Phase 1, because `BrainService` never passes an `org_brain`.

### Module 4: Lease and scheduler
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/lease.py` (new),
  `packages/ai-parrot/src/parrot/memory/dream/scheduler.py` (modify)
- **Responsibility**: One running loop per agent across processes; one state file per scope.
- **Depends on**: M1, M3
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/dream/lease.py  (new)
  class SchedulerLease:
      """Non-blocking exclusive flock on a lock file. Single-host only."""
      def __init__(self, lock_path: Path) -> None: ...
      def try_acquire(self) -> bool:
          """Take the lock if free. Idempotent for the holder. Never blocks."""
      def release(self) -> None: ...
      @property
      def held(self) -> bool: ...

  # packages/ai-parrot/src/parrot/memory/dream/scheduler.py  (modifies scheduler.py:24)
  RunnerFactory = Callable[[str], DreamCycleRunner]   # tenant_id -> runner for that scope

  class DreamScheduler:  # verified: packages/ai-parrot/src/parrot/memory/dream/scheduler.py:24
      def __init__(
          self,
          runner_factory: RunnerFactory,
          registry: BrainRegistry,
          lease: SchedulerLease,
          interval_hours: float = 24.0,
          config: DreamConfig | None = None,
      ) -> None: ...
      async def start(self) -> None:
          """Start the loop. Without the lease, stay on standby and retry."""
      async def stop(self) -> None:
          """Cancel the loop, persist state, release the lease."""
      async def run_now(self, tenant_id: str | None = None) -> list[DreamCycleReport]:
          """Run one cycle per requested scope (all known scopes when None).

          Returns an aborted report per scope when this process does not hold the lease.
          """
  ```
  The constructor change is breaking. Its only caller outside tests is `LongTermMemoryMixin`
  (`mixin.py:255`), which the unification spec removes.

### Module 5: Service facade
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/service.py` (new),
  `packages/ai-parrot/src/parrot/memory/dream/__init__.py` (modify)
- **Responsibility**: The single object the integration layer builds.
- **Depends on**: M1, M3, M4
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/dream/service.py  (new)
  class BrainService:
      def __init__(
          self,
          agent_id: str,
          episodic_store: EpisodicMemoryStore,
          brain_root: Path | None = None,          # default ~/.parrot/brains/<agent_id>
          llm_client: Any = None,
          interval_hours: float = 24.0,
          config: DreamConfig | None = None,
      ) -> None: ...
      async def start(self) -> None:
          """Idempotent. Logs one WARNING when a legacy un-scoped brain is present."""
      async def stop(self) -> None:
          """Idempotent."""
      async def search(self, query: str, tenant_id: str, max_tokens: int = 600) -> str:
          """Packed pages of the scope. "" on error or invalid tenant."""
      async def run_now(self, tenant_id: str | None = None) -> list[DreamCycleReport]: ...
      async def forget_derived(self, tenant_id: str, episodes: Sequence[EpisodicMemory]) -> list[str]:
          """Delete pages named by the episodes' "consolidated_into"; return deleted ids."""
      def admin_toolkit(self) -> "BrainAdminToolkit": ...
  ```
  `__init__.py` adds `BrainScope`, `BrainRegistry`, `SchedulerLease`, `BrainService`, `is_eligible`
  and `BrainAdminToolkit` to `_EXPORT_MODULES` (`__init__.py:16`), keeping resolution lazy.

### Module 6: Administrator toolkit and policy
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/toolkit.py` (new),
  `packages/ai-parrot-server/src/parrot/handlers/agent.py` (modify), `policies/tools.yaml` (modify)
- **Responsibility**: Bulk inspection and operation of a brain, for superusers only, mounted per
  request and fail-closed.
- **Depends on**: M5
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/memory/dream/toolkit.py  (new)
  class BrainAdminToolkit(AbstractToolkit):  # verified: packages/ai-parrot/src/parrot/tools/toolkit.py:225
      """Administrator-only inspection of an agent's brain."""
      tool_prefix = "brain_admin"            # tool_prefix verified: toolkit.py:276

      @requires_permission("brain.admin")    # verified: packages/ai-parrot/src/parrot/tools/decorators.py:9
      async def search(self, query: str, tenant_id: str | None = None) -> str:
          """Search the brain of a tenant. Defaults to the tenant of the request."""
      @requires_permission("brain.admin")
      async def list_pages(self, tenant_id: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
          """List the pages of a tenant's brain."""
      @requires_permission("brain.admin")
      async def read_page(self, page_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
          """Read one brain page in full."""
      @requires_permission("brain.admin")
      async def cycle_status(self) -> dict[str, Any]:
          """Lease holder flag, known tenants and each tenant's cycle state."""
      @requires_permission("brain.admin")
      async def run_cycle(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
          """Trigger a dream cycle now and return its reports."""
  ```
  `tenant_id=None` resolves to `current_tenant.get()`
  (verified: `packages/ai-parrot/src/parrot/observability/context.py:85`).

  ```python
  # packages/ai-parrot-server/src/parrot/handlers/agent.py  (modifies agent.py:237, :1614)
  async def _sync_brain_admin_tools(self, agent: Any, tool_manager: "ToolManager") -> None:
      """Mount the agent's BrainAdminToolkit on the session ToolManager only when PBAC allows it.

      Allowed  -> every brain_admin_* tool is registered (idempotent).
      Anything else (denied, no Guardian/PDP, no brain_service, any exception) -> every
      brain_admin_* tool is removed. Never raises.
      """
      # ToolManager.register_toolkit verified: packages/ai-parrot/src/parrot/tools/manager.py:1193
      # ToolManager.remove_tool verified: packages/ai-parrot/src/parrot/tools/manager.py:1450
      # Guardian.filter_resources call shape verified: handlers/agent.py:260
  ```
  It is called immediately before `_filter_tools_for_user` (agent.py:1614), so the existing filter
  remains a second check. The policy rule follows `deny_tool_configure_non_admin`
  (`policies/tools.yaml:121`): `effect: deny`, resource `tool:brain_admin_*`, actions `tool:execute`,
  `tool:list`, `tool:configure`, `groups: ["*"]`, `exclude_groups: [superuser]`, priority 90.
  `@requires_permission("brain.admin")` stays on the tools for deployments that use the RBAC
  resolver; under PBAC the declared permission is ignored (`auth/resolver.py:305`).

### Module 7: Documentation
- **Path**: `wiki/memory/agent-brain.md` (new), `wiki/memory/dream-cycle.md` (modify)
- **Responsibility**: Operator and author documentation for the scoped brain.
- **Depends on**: M1–M6

### Module 8 (Phase 2): Page state, versions and lineage — from FEAT-571 M4 / G4
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/{brain,models}.py`
- **Responsibility**: Per-version page state; `content_version` derived from the body and the
  sorted source episode ids; superseded versions archived; `BrainStore.search_memories` returning
  structured candidates, with `search(...) -> str` kept as an adapter.
- **Depends on**: M1; FEAT-571 gates G4 and G2; the authoritative-state decision in §8 Q4
- **Interface Skeleton**: not fixed. FEAT-571 §3 M4 and the G4 amendment are the inputs; the
  skeleton is written when the gate is accepted.

### Module 9 (Phase 2): Dynamics in the cycle — from FEAT-571 M4 / G1
- **Path**: `packages/ai-parrot/src/parrot/memory/dream/runner.py`
- **Responsibility**: Reintroduce promotion to a per-tenant wiki shared between agents, by
  retrievability plus at least one verified, attributed, non-`AGAIN` review of that version; recoverable forgetting; re-distillation, including re-distilling a page
  from its remaining sources when `forget_derived` removes some; cycle counters kept readable but no
  longer evidence.
- **Depends on**: M8; FEAT-571 gate G1; FEAT-571 M1 and M2 interfaces
- **Interface Skeleton**: not fixed, same reason as M8.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_scope_dir_contained` | M1 | unsafe, reserved and traversal tenant ids raise; valid ids resolve under `tenants/` |
| `test_registry_isolates_tenants` | M1 | a page remembered for tenant A is not returned by a search for tenant B |
| `test_registry_known_tenants_survive_restart` | M1 | a new registry on the same root lists the same tenants |
| `test_legacy_brain_ignored` | M1 | a root-level `wiki.db` is detected, never read or written |
| `test_brain_delete_pages` | M1 | deletes existing ids, ignores unknown ids, returns what it deleted |
| `test_unverified_turn_not_eligible` | M2 | `query_resolution` / `partial` is rejected even with a lesson and importance 5 |
| `test_user_preference_not_eligible` | M2 | excluded category rejected regardless of importance |
| `test_verified_episode_eligible` | M2 | a tool failure with importance 7, and a decision with a lesson, are accepted |
| `test_include_unverified_turns_flag` | M2 | the flag restores the FEAT-390 behaviour |
| `test_collect_uses_scope_namespace` | M3 | the backend filter carries the scope's tenant |
| `test_privacy_flag_skips_group` | M3 | `personal_data=True` writes no page, marks no episode, increments the counter |
| `test_heuristic_never_copies_situation` | M3 | a group without lessons produces no page |
| `test_watermark_holds_for_rejected_groups` | M3 | rejected groups stay collectable next cycle |
| `test_lease_exclusive_across_processes` | M4 | a second process cannot acquire; it acquires after the first exits |
| `test_scheduler_standby_takes_over` | M4 | a standby scheduler starts its loop once the lease is free |
| `test_scheduler_visits_due_scopes` | M4 | only scopes whose `next_due` passed run; each keeps its own state file |
| `test_service_search_scoped` | M5 | returns only the tenant's pages; `""` for an invalid tenant |
| `test_service_start_stop_idempotent` | M5 | repeated calls start one loop and release once |
| `test_forget_derived_deletes_pages` | M5 | pages named by the episodes are gone from search; ids returned |
| `test_distilled_text_is_redacted` | M3 | a token in a lesson is replaced by the redaction marker in the stored page |
| `test_admin_tools_require_permission` | M6 | every generated tool carries `brain.admin` and the `brain_admin_` prefix |
| `test_mount_only_when_allowed` | M6 | allowed user: tools registered; denied user: absent |
| `test_mount_fails_closed` | M6 | no Guardian, no `brain_service`, or a raising Guardian: tools absent, no exception |
| `test_mount_revokes_cached_session` | M6 | tools mounted on a cached session manager are removed once the user is no longer allowed |

### Integration Tests
| Test | Description |
|---|---|
| `test_two_tenants_one_agent_end_to_end` | episodes of two tenants, one cycle each, searches never cross |
| `test_brain_admin_policy_superuser_only` | with the shipped policies loaded, `tool:brain_admin_search` is denied to a `devops` user and allowed to a `superuser` |

### Validation Contract

tests:
- tests/memory/dream/test_brain.py
- tests/memory/dream/test_models.py
- tests/memory/dream/test_runner.py
- tests/memory/dream/test_scheduler.py
- tests/memory/dream/test_update_metadata.py
- packages/ai-parrot/tests/memory/dream/test_scope.py
- packages/ai-parrot/tests/memory/dream/test_eligibility.py
- packages/ai-parrot/tests/memory/dream/test_runner_privacy.py
- packages/ai-parrot/tests/memory/dream/test_lease.py
- packages/ai-parrot/tests/memory/dream/test_service.py
- packages/ai-parrot/tests/memory/dream/test_admin_toolkit.py
- packages/ai-parrot-server/tests/handlers/test_brain_admin_mount.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def brain_root(tmp_path: Path) -> Path:
    """An empty per-agent brain root."""

@pytest.fixture
def fake_episodic_store() -> Any:
    """In-memory store whose backend implements get_recent and update_metadata."""
```

The five files under `tests/memory/dream/` exist today and are updated by the modules that change
the behaviour they cover. The six files under `packages/ai-parrot/tests/memory/dream/` and
`packages/ai-parrot-server/tests/handlers/test_brain_admin_mount.py` are created by this feature. `tests/memory/dream/test_integration.py` and `test_unified_brain.py` exercise
`LongTermMemoryMixin` and belong to the unification spec.

---

## 5. Acceptance Criteria

Phase 1:

- [ ] A page written for one tenant is never returned by `BrainService.search` for another tenant
      of the same agent.
- [ ] A tenant id that is unsafe, reserved or escapes the brain root raises on write and yields `""`
      on read; no directory is created for it.
- [ ] A conversation turn recorded as `query_resolution` / `partial` is not consolidated with the
      default configuration.
- [ ] An episode of category `user_preference` is never consolidated with the default configuration.
- [ ] A group whose distillation reports personal data produces no page and its episodes remain
      collectable.
- [ ] With no LLM client, no page contains `situation` or `action_taken` text.
- [ ] With two processes on one brain root, exactly one runs cycles; when it exits, the other takes
      over within `lease_retry_seconds`.
- [ ] `BrainService.start()` and `stop()` are idempotent.
- [ ] `forget_derived` removes every page named by the given episodes' `consolidated_into`.
- [ ] No page contains a value that `redact_text` would replace.
- [ ] `BrainAdminToolkit` tools are present on a session `ToolManager` only for a user PBAC allows;
      they are absent when PBAC is not configured, when the check raises, and after the user stops
      being allowed.
- [ ] Under the shipped policies, `tool:brain_admin_*` is denied to every group except `superuser`,
      including groups that are allowed `tool:*`.
- [ ] Phase 1 writes no page outside `tenants/<tenant_id>/`; there is no organisation brain.
- [ ] A FEAT-390 brain at the root of the brain directory is neither read nor modified, and one
      WARNING names it.
- [ ] Importing `parrot.memory` still does not import the wiki plane unless a brain symbol is used.
- [ ] The Validation Contract passes.
- [ ] Documentation pages declared in §10 exist under `wiki/` (`parrot sdd techwiki check`).

Phase 2 criteria are inherited from FEAT-571 §5 for M4 and are restated when the Phase 2 gate opens.

---

## 6. Codebase Contract

> Verified against `dev` at `58ec71d179`. All paths below are under
> `packages/ai-parrot/src/parrot/` unless they start with `policies/` or `tests/`.

### Verified Imports
```python
from parrot.memory.dream.brain import BrainStore                    # memory/dream/brain.py:21
from parrot.memory.dream.models import (                            # memory/dream/models.py
    DreamState, DreamConfig, DistilledKnowledge, DreamCycleReport,  # :29, :58, :87, :103
    save_state, load_state,                                         # :132, :150
)
from parrot.memory.dream.runner import DreamCycleRunner             # memory/dream/runner.py:71
from parrot.memory.dream.scheduler import DreamScheduler            # memory/dream/scheduler.py:24
from parrot.memory.episodic.models import (                         # memory/episodic/models.py
    EpisodicMemory, MemoryNamespace, EpisodeOutcome, EpisodeCategory,  # namespace :214, outcome :20, category :29
)
from parrot.memory.episodic.store import EpisodicMemoryStore        # imported at memory/dream/runner.py:15
from parrot.knowledge.wiki import create_wiki_store, pack_results   # knowledge/wiki/__init__.py:70, :74
from parrot.knowledge.wiki.store import WikiPageRecord, estimate_tokens  # knowledge/wiki/store.py:606, :479
from parrot.skills.tenancy import validate_tenant_id                # skills/tenancy.py:45
from parrot.utils.paths import secure_path, validate_path_segment   # utils/paths.py:52, :33
from parrot.observability.context import current_tenant             # observability/context.py:85
from parrot.tools.toolkit import AbstractToolkit                    # tools/toolkit.py:225
from parrot.tools.decorators import requires_permission             # tools/decorators.py:9
from parrot.security.redaction import redact_text                   # security/redaction.py:49
```

### Existing Class Signatures
```python
# memory/dream/brain.py
class BrainStore:                                                   # :21
    def __init__(self, storage_dir: Path, wiki_name: str, asserted_by: str = "agent") -> None  # :31
    self._store                                                     # :49  (create_wiki_store(..., backend="sqlite"))
    async def remember(self, text, title=None, category="note", related_pages=None) -> dict[str, Any]  # :53
    async def search(self, query: str, top_k: int = 5, max_tokens: int = 600) -> str                    # :113
    async def copy_page_to(self, page_id: str, other: BrainStore) -> str                                # :146

# memory/dream/models.py
class DreamState(BaseModel):                                        # :29
    agent_id: str; last_run; next_due; interval_hours; running; running_since
    cycles_completed; episodes_consolidated; reinforcement_counts: dict[str, int]; promoted_pages: list[str]
class DreamConfig(BaseModel):                                       # :58
    importance_threshold: int = 5; similarity_threshold: float = 0.75; max_groups_per_cycle: int = 20
    org_promotion_cycles: int = 3; distill_model: str; startup_jitter_seconds: int = 60; failure_backoff_divisor: int = 4
class DistilledKnowledge(BaseModel):                                # :87   title, body, category="lesson", confidence=0.5
class DreamCycleReport(BaseModel):                                  # :103
def save_state(state: DreamState, path: Path | str) -> None         # :132
def load_state(path: Path | str, agent_id: str) -> DreamState       # :150

# memory/dream/runner.py
DISTILL_PROMPT                                                      # :22
_COLLECT_LIMIT = 5000                                               # :50
class DreamCycleRunner:                                             # :71
    def __init__(self, episodic_store, brain, namespace, llm_client=None, org_brain=None, config=None)  # :88
    async def run_cycle(self, state: DreamState) -> DreamCycleReport                                    # :105
    async def _collect(self, state: DreamState) -> list[EpisodicMemory]                                 # :235
    async def _distill(self, group) -> DistilledKnowledge                                               # :360
    @staticmethod def _format_episodes(group) -> str                                                    # :429
    @staticmethod def _heuristic_distill(group) -> DistilledKnowledge                                   # :474

# memory/dream/scheduler.py
class DreamScheduler:                                               # :24
    def __init__(self, runner, state_path: Path, interval_hours: float = 24.0, config=None)  # :38
    async def start(self) -> None                                   # :57
    async def stop(self) -> None                                    # :109
    async def run_now(self) -> DreamCycleReport                     # :122
    async def _run_locked_cycle(self) -> DreamCycleReport           # :154

# memory/episodic/models.py
class MemoryNamespace(BaseModel):                                   # :214  tenant_id="default", agent_id, user_id, session_id, room_id, crew_id
    def build_filter(self) -> dict[str, Any]                        # :246

# memory/episodic/store.py
class EpisodicMemoryStore:
    async def mark_consolidated(self, episode_ids: list[str], page_id: str) -> int   # :577

# memory/episodic/backends/abstract.py
    async def get_recent(self, namespace_filter: dict[str, Any], limit: int = 10, since: datetime | None = None) -> list[EpisodicMemory]  # :51
    async def update_metadata(self, episode_ids: list[str], patch: dict[str, Any]) -> int  # :106

# knowledge/wiki/store.py
class BaseWikiStore(ABC):                                           # :870
    supports_attrs: bool = False                                    # :889
    async def delete_page(self, concept_id: str) -> bool            # :931
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]  # :938
    async def list_pages(self, category=None, limit: int = 100, origin=None) -> list[dict[str, Any]]  # :941
    async def search_fts(self, query: str, category=None, limit: int = 10) -> list[dict[str, Any]]    # :949

# tools/toolkit.py
class AbstractToolkit(ServerManagedToolkit, ABC):                   # :225
    tool_prefix: str | None = None                                  # :276
    async def get_tools_filtered(self, permission_context, resolver) -> list[AbstractTool]  # :620

# auth/resolver.py
    async def can_execute(self, context, tool_name: str, required_permissions: set[str]) -> bool  # :44 (abstract)
    async def filter_tools(self, context, tools: list[Any]) -> list[Any]                          # :65, PBAC override :341

# security/redaction.py
def redact_text(text: str) -> str                                   # :49

# packages/ai-parrot-server/src/parrot/handlers/agent.py
    async def _filter_tools_for_user(self, tool_manager: "ToolManager") -> None   # :237  removes denied tools; fail-open
    # guardian = self.request.app.get("security")                                # :249
    # await guardian.filter_resources(resources=tool_names, request=self.request,
    #     resource_type=ResourceType.TOOL, action="tool:execute")                 # :260  -> .denied
    # call site: await self._filter_tools_for_user(user_tool_manager)             # :1614

# tools/manager.py
    def register_toolkit(self, toolkit, **kwargs) -> List[AbstractTool]   # :1193
    def list_tools(self) -> List[str]                               # :1415
    def remove_tool(self, tool_name: str) -> None                   # :1450
    def set_resolver(self, resolver) -> None                        # :446
    # Layer 2 check at execution: self._resolver.can_execute(permission_context, tool.name, required)  # :2027
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `scope_dir` | `validate_tenant_id`, `secure_path` | function call | `skills/tenancy.py:45`, `utils/paths.py:52` |
| `BrainRegistry.get` | `BrainStore.__init__` | construction | `memory/dream/brain.py:31` |
| `BrainStore.delete_pages` | `BaseWikiStore.delete_page` | method call | `knowledge/wiki/store.py:931` |
| `DreamCycleRunner._collect` | `is_eligible` | function call | `memory/dream/runner.py:262` (current inline predicate) |
| `DreamScheduler` | `SchedulerLease`, `BrainRegistry` | constructor injection | `memory/dream/scheduler.py:38` |
| `BrainAdminToolkit` tools | `ToolManager` Layer 2 check | `can_execute` | `tools/manager.py:2027` |
| `_sync_brain_admin_tools` | `Guardian.filter_resources`, `ToolManager.register_toolkit` / `remove_tool` | method calls | `handlers/agent.py:260`, `tools/manager.py:1193`, `:1450` |
| distilled title/body | `redact_text` | function call before `remember` | `security/redaction.py:49`, `memory/dream/runner.py:166` |
| `forget_derived` | episode `metadata["consolidated_into"]` | read | written at `memory/dream/runner.py:189` |

### Does NOT Exist (Anti-Hallucination)
- ~~`BrainStore.delete_page` / `list_pages` / `get_page`~~ — `BrainStore` has only `remember`,
  `search`, `copy_page_to`. The wiki store underneath (`self._store`) has them.
- ~~`BrainStore.close()`~~ — no close or cleanup method exists on `BrainStore`.
- ~~`BrainStore.search_memories`~~ — named by FEAT-571 M4; not implemented (Phase 2, M8).
- ~~`EpisodicMemoryStore.get_recent`~~ — the store has no passthrough; the runner reaches
  `self._episodic_store._backend.get_recent` (`runner.py:253`).
- ~~a get-episode-by-id method on `AbstractEpisodeBackend`~~ — not found; `forget_derived` therefore
  takes episode objects, not ids.
- ~~`WikiPageRecord.metadata`~~ — the record has no metadata member. Page attributes are a separate
  store capability; `SQLiteWikiStore` enables it (`supports_attrs = True`, `knowledge/wiki/store.py:1306`).
- ~~a caller of `AbstractToolkit.get_tools_filtered` on the bot request path~~ — nothing calls it.
  Layer 1 is wired elsewhere: the agent HTTP handler removes denied tools from the session
  `ToolManager` (`handlers/agent.py:237`). That filter is fail-open and HTTP-only.
- ~~`bot.brain_service`~~ — does not exist yet; it is requirement R10 on the unification spec.
- ~~a per-request tenant on `MemoryNamespace`~~ — `tenant_id` is whatever the caller sets; today
  the mixin sets it from the instance attribute (`memory/unified/mixin.py:356`).
- ~~`fakeredis`, a `parrot/vectorstores/` package, `DreamScheduler` leader election~~ — none exist.
- `tool.required_permissions` (read at `tools/manager.py:2026`) versus `tool._required_permissions`
  (set by the decorator, `tools/decorators.py:32`, copied at `tools/toolkit.py:714`): which one the
  Layer 2 check actually sees for a toolkit tool is **(unverified — check before use)**; M6's
  integration test settles it.

### Edit Sites (Blueprint Anchors)

Verified against: `58ec71d179`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/memory/dream/scope.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/dream/eligibility.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/dream/lease.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/dream/service.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/dream/toolkit.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/memory/dream/brain.py` | MODIFY | `class BrainStore:` | `brain.py:21` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/models.py` | MODIFY | `class DreamConfig(BaseModel):` | `models.py:58` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/models.py` | MODIFY | `class DreamCycleReport(BaseModel):` | `models.py:103` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/runner.py` | MODIFY | `DISTILL_PROMPT = """Analyze these related agent episodes and distill ONE piece of durable knowledge.` | `runner.py:22` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/runner.py` | MODIFY | `    async def _collect(self, state: DreamState) -> list[EpisodicMemory]:` | `runner.py:235` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/runner.py` | MODIFY | `    def _heuristic_distill(group: list[EpisodicMemory]) -> DistilledKnowledge:` | `runner.py:474` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/scheduler.py` | MODIFY | `class DreamScheduler:` | `scheduler.py:24` | 1 |
| `packages/ai-parrot/src/parrot/memory/dream/__init__.py` | MODIFY | `_EXPORT_MODULES: dict[str, str] = {` | `__init__.py:16` | 1 |
| `policies/tools.yaml` | MODIFY | `  - name: deny_tool_configure_non_admin` | `tools.yaml:121` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `    async def _filter_tools_for_user(self, tool_manager: "ToolManager") -> None:` | `agent.py:237` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `            await self._filter_tools_for_user(user_tool_manager)` | `agent.py:1614` | 1 |
| `wiki/memory/agent-brain.md` | CREATE | — | — | — |
| `wiki/memory/dream-cycle.md` | MODIFY | `# Dream Cycle — episodic → wiki brain consolidation` | `dream-cycle.md:1` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Memory never breaks `ask()`: every read-path failure degrades to an empty string with a WARNING,
  as `BrainStore.search` does today (`brain.py:132`).
- Tenant ids are path segments: validate with `validate_tenant_id` and build paths with
  `secure_path`, the same primitives per-tenant skills use (FEAT-707).
- Keep `parrot.memory.dream` exports lazy (PEP 562, `__init__.py:31`).
- `flock` is a synchronous call; with `LOCK_NB` it returns at once and is safe on the event loop.
- Pydantic v2 models; `self.logger`; no new dependencies.

### Known Risks / Gotchas
- **Nothing is eligible without R8.** Under rule 3, an agent that records only conversation turns
  consolidates nothing. That is intended, and it makes R8 a hard dependency on the unification spec.
- **`personal_data` is self-reported by the model.** It is one of three layers, with the excluded
  categories and the unverified-turn rule. It is not a guarantee by itself.
- **Deleting a whole page on `forget_derived` loses knowledge** that other episodes supported.
  Accepted for Phase 1; M9 re-distills instead.
- **The collection limit is unchanged.** `_COLLECT_LIMIT = 5000` and the absence of pagination in
  `get_recent` still apply, now per scope.
- **`flock` is single-host and Linux-only.** Network filesystems are out of scope with shared
  storage. Two hosts sharing a brain root is unsupported.
- **Legacy brains are orphaned, not migrated.** No production agent enables the brain today, so no
  migration is written. The WARNING names the path so an operator can move it under
  `tenants/<tenant>/` by hand.
- **The administrator tools exist only on the HTTP path.** Telegram, Slack and other channels never
  mount them. That is intended.
- **`redact_text` covers secrets, not personal data.** It complements the prompt clause and the
  eligibility rules; it does not replace them.
- **Breaking constructor on `DreamScheduler`.** Safe only because this spec is built after the
  hard-cut removes `LongTermMemoryMixin`.

### External Dependencies
None. `fcntl` is in the standard library.

---

## Decisions

```yaml
schema_version: 1
document_id: agent-brain
entries:
  - id: brain-scope-request-tenant
    statement: A brain is scoped by the server-resolved tenant of the request and the agent, never by the agent alone or by the instance's static tenant.
    relation: requires
    about: [memory]
    targets: ["file:packages/ai-parrot/src/parrot/memory/dream/brain.py"]
    contradicts: []
    supersedes: []
    rationale: One agent instance can serve several tenants; an agent-keyed brain mixes them.
    rejected_alternatives: ["per-user brains (that knowledge is user memory)", "treating a user as a tenant"]
  - id: brain-unverified-turns-not-evidence
    statement: A conversation turn without a verified outcome is never consolidated into the brain by default.
    relation: forbids
    about: [memory]
    targets: ["file:packages/ai-parrot/src/parrot/memory/dream/runner.py"]
    contradicts: []
    supersedes: []
    rationale: FEAT-571 M0 records such turns as PARTIAL precisely because they prove nothing; consolidating them fills the brain with noise.
    rejected_alternatives: ["raising the importance threshold only"]
  - id: brain-single-scheduler-by-lease
    statement: Exactly one process per agent runs dream cycles, selected by an exclusive file lease on the brain root.
    relation: requires
    about: [memory]
    targets: ["file:packages/ai-parrot/src/parrot/memory/dream/scheduler.py"]
    contradicts: []
    supersedes: []
    rationale: gunicorn runs several workers; the FEAT-390 JSON flags are not an inter-process lock.
    rejected_alternatives: ["an external cron job", "a scheduler flag set by hand on one worker"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:9ebb45c12de6c3b629d29f04ae976cb43c8b82828c6e28dd7ee901ed8da1a946 evaluation_digest=sha256:4c4c47efe623b91af9909adc27e19d6a47d4d4822d7b7c59597cdeb8a00d5aed rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: brain, dream-cycle, multi-tenant, pbac
- Targets resolved: 3/3
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 3,
    "targets_total": 3,
    "unmapped_tags": [
      "brain",
      "dream-cycle",
      "multi-tenant",
      "pbac"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:4c4c47efe623b91af9909adc27e19d6a47d4d4822d7b7c59597cdeb8a00d5aed",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:9ebb45c12de6c3b629d29f04ae976cb43c8b82828c6e28dd7ee901ed8da1a946",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:c0bb514c8818b7437b79f6afed09d85800ef0625e747bddf2af62a7cb687532b",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] One spec or two for unification and brain — *Resolved by the owner, 2026-11-13*: two. This
      spec owns `memory/dream/*`; the unification spec owns the mixin and the wiring.
- [x] Where FEAT-571 M4 lives — *Resolved by the owner, 2026-11-13*: here (M8–M9). It is removed
      from the unification design document with an amendment pointing to this spec.
- [x] When this spec is built — *Resolved by the owner, 2026-11-13*: only after `AgentMemoryMixin`
      lands on `dev`.
- [x] Does enabling the brain require enabling episodic memory separately — *Resolved by the owner,
      2026-11-13*: no; one cannot exist without the other, so the brain turns it on by default (R2).
- [x] May an agent disclose its brain to whoever asks — *Resolved by the owner, 2026-11-13*: no.
      Bulk inspection is administrator tooling gated by PBAC to superusers.
- [x] Is a user a tenant — *Resolved by the owner, 2026-11-13*: no. Knowledge about a person is
      user memory, a separate capability in the unification spec.
- [x] **Q1** — How the administrator tools are restricted by policy — *Resolved by inspection,
      2026-11-13*: under PBAC the declared permission is ignored and the resource `tool:<name>` is
      evaluated (`auth/resolver.py:322`). `policies/tools.yaml` denies by default, but
      `devops_all_tools` allows `tool:*` at priority 30, so M6 adds an explicit deny for
      `tool:brain_admin_*` with `exclude_groups: [superuser]` at priority 90, after the existing
      `deny_tool_configure_non_admin` pattern.
- [x] **Q2** — How the administrator toolkit is mounted — *Resolved by the owner, 2026-11-13*: mount
      only when allowed. It is never registered on the agent; the HTTP handler adds it to the session
      `ToolManager` when PBAC allows the user and removes it in every other case, including PBAC not
      configured and errors. (An earlier draft said Layer 1 was not wired; that was wrong — see
      `handlers/agent.py:237`.)
- [x] **Q3** — Redaction of distilled text — *Resolved by the owner, 2026-11-13*: always. Title and
      body pass through `redact_text` before archiving, regardless of `enable_redaction`.
- [ ] **Q4** — Authoritative brain page state and G2–G4 atomicity (inherited from the unification
      design document, §8 "Contrato transversal pendiente"). Blocks M8; cannot be closed before the
      G2 and G4 gates are reviewed. — *Owner: Jesus + G2/G4 review*
- [x] **Q5** — Promotion in Phase 1 — *Resolved by the owner, 2026-11-13*: deferred to Phase 2.
      Phase 1 has no organisation brain; M9 reintroduces promotion with the G1 criterion.
- [x] **Q6** — Page attributes on the SQLite wiki backend — *Resolved by inspection, 2026-11-13*:
      supported (`knowledge/wiki/store.py:1306`). M8 may record lineage on the page.

---

## 9. Design Research Cross-Check

Status: skipped (no accepted exploration document — the design was settled in conversation with the
owner and `/sdd-spec` ran from notes).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/memory/agent-brain.md` — create: what the brain is, its scope and storage layout, what is
    and is not consolidated, the scheduler lease, the administrator toolkit and its policy, legacy
    brains.
  - `wiki/memory/dream-cycle.md` — update: point to the scoped model, replace the single-process and
    turning-it-on sections.
- **API modules**:
  - `parrot.memory.dream`

---

## Worktree Strategy

- **Isolation**: one feature worktree for this spec; the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M3 → M2 (the runner imports `is_eligible` and the new `DreamConfig` fields).
  - M4 → M1 (the scheduler takes a `BrainRegistry`), M4 → M3 (it builds runners).
  - M5 → M1, M3, M4 (the service composes them).
  - M6 → M5 (the toolkit wraps the service). M6 also edits `ai-parrot-server`; run its tests with
    `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src`.
  - M7 → M1–M6.
  - M1 and M2 have no edge between them and run concurrently.
  - M9 → M8.
- **Shared files**: `memory/dream/models.py` (M2, later M8); `memory/dream/runner.py` (M3, later
  M9); `memory/dream/brain.py` (M1, later M8); `memory/dream/__init__.py` (M5 only).
- **Exclusive resources**: none.
- **Cross-feature dependencies**: the unification spec (`AgentMemoryMixin`) must be merged first.
  Phase 2 additionally needs the FEAT-571 gates G1, G2 and G4 accepted and the FEAT-571 M1/M2
  interfaces frozen on `dev`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-13 | Jesus Lara, with Claude | Initial draft. Absorbs FEAT-571 M4 as Phase 2. |
| 0.2 | 2026-11-13 | Jesus Lara, with Claude | Open questions resolved: mount-only-when-allowed for the admin toolkit, deny rule in `policies/tools.yaml`, always-on redaction, promotion deferred to Phase 2. Only Q4 stays open. |
