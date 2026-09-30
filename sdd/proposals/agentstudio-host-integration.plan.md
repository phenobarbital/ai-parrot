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
M1  storage W0–W1 (schema, repositories, partition hook)   ║  FEAT-605 W0–W1 (scope seam, host mount hooks, /me)  ║  toolkits W1–W2
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
- FieldSync: read-only domain toolkits on toolkits W1–W2.

Who implements the parrot specs is open — we can take tasks in parrot under
your review, the same way as FEAT-609.

## Decisions we need from you

| # | Decision | Our recommendation |
|---|---|---|
| 1 | Package shape and order (storage → FEAT-605 v0.2; toolkits in parallel); two specs or merge 1+2? | Keep separate; storage first |
| 2 | Declarative-only on the tenant path; the assistant stops emitting Python there | Yes |
| 3 | Host seam API (`view_wrapper`, `studio_routes=False`, `setup_registry_only`, `/me`) | As in FEAT-605 v0.2 |
| 4 | Cross-pod sync by row `version` re-read (no LISTEN/NOTIFY; works through PgBouncer) | Yes; LISTEN later as an optimisation |
| 5 | Host toolkit registration: declarative registry + mandatory prefix; never shadow built-ins | Yes |
| 6 | Release train: ship FEAT-605 W0–W1 early, the rest in lockstep with storage W3 | Yes |
| 7 | BYOK and toolkit secrets move from DocumentDB to Postgres (phase 2) | Yes |
| 8 | Shared handler files merge storage W3 first, per file. Exempt the small gates (FEAT-605 W1.3 `/tools/{slug}/execute`; toolkits W2–W3 in `tooling_store.py` / `testing.py` / `toolkits.py`) so they can land earlier? | Exempt W1.3; keep toolkits behind storage W3 |
| 9 | New `PATCH /agents/{name}` (storage §2.9a): name immutable (`name_immutable`), `bot_class` not updatable, `not_studio_agent` for legacy agents | Yes |

All three specs share an identical "Cross-spec contract (package)" section
(X1–X16): the one place to check names, tables, routes and error codes.

Each spec ends with its own smaller Open Questions, each with a
recommendation.

## Out of scope for this package

Scheduler; runtime use of authored agents outside Studio (chat, A2UI
surfaces); KB binaries (S3); migrating legacy `ai_bots` / Python agents;
Agent Studio in navigator-frontend-next or parrot-admin-ui.
