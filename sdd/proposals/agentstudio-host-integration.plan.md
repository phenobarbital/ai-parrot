# Plan: Agent Studio for multi-tenant hosts (FieldSync first)

**From**: Juan Ruffato · **For**: Jesus Lara (review & decisions) · **Date**: 2026-09-30
**Package** (branch `sdd/agentstudio-host-integration`, specs only, no code):

| # | Spec | What it is | Status |
|---|---|---|---|
| 1 | `sdd/specs/agentstudio-db-storage.spec.md` | Studio state in Postgres (new `navigator.ai_agents` + child tables); cross-pod sync; migrations; BYOK phase 2 | new, FEAT-TBD |
| 2 | `sdd/specs/agentstudio-tenant-visibility.spec.md` | **Your FEAT-605, revised to v0.2** on top of #1 — see its "v0.2 changes" table for the diff | revision |
| 3 | `sdd/specs/agentstudio-host-toolkits.spec.md` | Host toolkits in every Studio path + agent/caller scope for tools | new, FEAT-TBD |

IDs are not reserved: you reserve them if you approve.

## Why

Your `/api/v1/astudio/*` plane (FEAT-467/593) is ready. We want FieldSync
users (reps, managers, admins across flexroc, epson, pokemon…) to build their
own agents, per programme, with sharing private / programme / groups.
Reviewing FEAT-605 against FieldSync's real mount showed it cannot land as
written:

- **Mounted as written, FieldSync returns 500/403 on every call**: Studio views
  are registered directly, so the host's tenant seam never runs.
- **Owners see their own records across tenants** (the FEAT-535 hole again).
- **Per-pod disk state**: `AGENTS_DIR` files and the in-process registry do not
  survive multiple pods or redeploys.
- **Activating a draft imports user-generated Python into the server.**
- Host toolkits (`plugins/tools/`) are invisible to 5 of Studio's 7 toolkit paths.

## What we propose (decisions already taken on the FieldSync side)

1. **All Studio state in Postgres**, in **new** tables — `navigator.ai_bots` is
   not touched; legacy agents keep working; migrating them is a later follow-up.
2. **Tenant-scoped Studio agents are declarative only**: the assistant emits the
   `POST /agents` definition; activate = create; no Python import on the tenant
   path (Python drafts remain for plain hosts, deprecated).
3. **Names unique per tenant** (`UNIQUE(tenant, name)`).
4. **The host keeps its seam**: `setup_studio_routes(prefix, view_wrapper)`,
   `BotManager.setup(studio_routes=False)` / `setup_registry_only(app)`,
   `GET {prefix}/me` for capabilities.
5. **No startup DDL**: versioned SQL the host applies.
6. **One toolkit resolver** honouring the host's `plugins.tools.TOOL_REGISTRY`.

## Order and milestones

```
M1  storage W0–W1 (schema, repositories, identity refs)   ║  FEAT-605 early subset W0.1–W0.3 + W1.1–W1.5  ║  toolkits W1 (resolver, policy code)
M2  storage W2 (services, runtime)  →  FEAT-605 W2 (access service)
M3  storage W3 (handler switch)     →  FEAT-605 W3 (agents, drafts, skills, assistant), per-file after storage
M4  storage W4 + FEAT-605 W4 (route matrix, docs) + toolkits W4 (scope binding)  →  release (1.0.7 or next)
M5  storage P2: BYOK + toolkit secrets off DocumentDB
```

What we build meanwhile, **without waiting on parrot**:

- navigator-svelte: Agent Studio UI foundation (client, store, pickers,
  schema form) against the current contract with a mock — starts now.
- FieldSync: mount + per-programme settings on FEAT-605 W0.1/W0.2 (dev only);
  merge and flag-on only after the release is on PyPI.
- FieldSync: read-only domain toolkits once toolkit discovery + policy land; tenant binding after toolkits W4.

Who implements the parrot specs is open — we can take tasks in parrot under
your review, the same way as FEAT-609.

## Response to the review (R1–R10, 2026-09-30)

Every finding is treated as a **correctness requirement**, fixed in its owning
spec with the regression case you listed added to the test spec and ACs.

| # | Finding | Fixed in | How |
|---|---|---|---|
| R1 | MCP stdio / `command` in `params` still executes | TOOLKITS (policy) + STORAGE (gate) | Host-owned `TenantToolingPolicy`, deny-by-default, applied to the final normalised config (after `hydrate_mcp`) on every write, activation and build via `StudioToolingGate` → `enforce_tenant_tooling`; built-ins behind an allow-list |
| R2 | Studio instances in `_bots` reachable by `get_bot` | STORAGE | Separate `StudioRuntimeCache`; `get_bot` refuses `studio:`/`studio-agent:`; `add_bot` refuses Studio instances; warm-cache test |
| R3 | Overrides / vault names keyed by bare name | STORAGE (scheme) + TOOLKITS (consumer) | Immutable `studio-agent:<agent_id>` ref in override keys, vault names and caches **now**; legacy keeps bare names |
| R4 | Assistant session not partitioned | FEAT-605 + STORAGE | Session, instance cache and `chatbot_id` keyed by (tenant, user); explicit `user_id`/`session_id` on `ask`; runtime `chatbot_id = str(agent_id)` |
| R5 | Builder drops stored config | STORAGE | Explicit definition → constructor map; no `config`/`startup_config` path; model precedence settled; test on real constructor/LLM settings |
| R6 | Standalone tools and options bypass scope | TOOLKITS | Gate at top of `AbstractTool.execute` before resources; options wrapped; `ensure_tool_scope` |
| R7 | `confirming_tools` not enforced | TOOLKITS | Fail-closed approval token; direct execute → 403 `confirmation_required` |
| R8 | Minimal mount lacks lifecycle | STORAGE (hooks) + FEAT-605 (mount) | `add_studio_runtime_hooks` (storage first), expiry sweep, per-instance cleanup, leases for in-flight calls, shutdown |
| R9 | Migration integrity / DDL | STORAGE | Final DDL, checksum excludes trailer + `MANIFEST.json`, advisory lock, PG ≥ 14, constraints on catalogue/drafts; `search_path` claim removed |
| R10 | Service signatures / concurrency | STORAGE | Signatures match handlers; `StudioWriteGuard` under `FOR UPDATE`; `expected_version` only on listed routes; atomic activation; build snapshot; real asyncdb transaction API |
| — | Found while fixing R4 | FEAT-605 | Assistant called `ask` without `user_id`/`session_id` → `anonymous` + random session |

**Sequencing, corrected:** the truly independent early subset is FEAT-605
W0.1–W0.3 + W1.1–W1.5 (incl. the plain-host D1 draft-overwrite and D3 takeover
fixes, now independent of the storage conversion). Toolkit discovery proceeds
alone; scope binding/enforcement waits for FEAT-605 W2.1 + storage runtime
identity. **No tenant-ready release until every spec's release gate is met.**
Phase 2 (BYOK + vault credentials/user overrides off DocumentDB) is now a
committed module/task set in STORAGE (M11–M12), not an open question.

## Product decisions (approved 2026-09-30)

| # | Decision | Outcome |
|---|---|---|
| 1 | Package shape: three specs, storage first, coordinated tenant release | Keep (as you suggested) |
| 2 | Host seam API (`view_wrapper`, `studio_routes=False`, `setup_registry_only` + runtime hooks, `/me`) | As in FEAT-605 |
| 3 | Cross-pod sync by row `version` re-read, with the snapshot/in-flight guarantees stated in STORAGE | Yes; LISTEN later only as an optimisation |
| 4 | Host toolkit registration: declarative registry + mandatory prefix; never shadow built-ins | Yes |
| 5 | Test chat has no HITL channel yet → host writes unavailable there until one exists | Accept for v1 |
| 6 | Does `TenantToolingPolicy` also apply to the GLOBAL (plain-host) partition? | Opt-in (`apply_to_global=False` default) |
| 7 | `PATCH /agents/{name}`: name immutable, `bot_class` not updatable | Yes |
| 8 | Release train for the early subset: a preview release (not tenant-ready) vs. holding everything for one lockstep release; still 1.0.7? | **Not a spec decision — non-blocking.** The maintainer picks version numbers and release grouping once the specs are built; only the release gate (no tenant-ready release before every gate) is binding |

All recommendations above were adopted. Every spec's remaining questions are
resolved or deferred as explicit non-blocking follow-ups; the three specs are
marked **approved** and ready for `/sdd-task` (feature IDs reserved by the
maintainer).

## Out of scope for this package

Scheduler; runtime use of authored agents outside Studio (chat, A2UI
surfaces); KB binaries (S3); migrating legacy `ai_bots` / Python agents;
Agent Studio in navigator-frontend-next or parrot-admin-ui.
