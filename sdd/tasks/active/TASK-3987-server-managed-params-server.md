# TASK-3987: Server handlers read server_managed_params — delete _SERVER_MANAGED/_KNOWN_APP_DEPS; 422 server_managed on PUT, /me, assign, execute (M4, part 3)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3983, TASK-3984, TASK-3985
**Assigned-to**: unassigned
**Wave**: 3 (spec §9) · **Module**: M4 server-managed-params (server)

---

## Context

Spec §2 "Server-managed rules": `_reject_server_managed` refuses a constructor server-managed key on PUT
(`tooling_store.py:167`) **and** on the `/me` override with **422 `server_managed`** (today PUT maps the
`ValueError` to 422 `invalid_params`, `toolkit_config.py:52-53`); assign and execute drop/refuse client values and
fill from the ClassVar (`source="app"` → `app[key]`; `"server"` → bespoke builder like `_assign_wiki`). Both
hard-coded dicts are deleted. Execute body keys that are server-managed → 422 `server_managed`.

---

## Scope

- `tooling_store.py`: delete `_SERVER_MANAGED`; `schema_for` passes no explicit `server_managed` (the ClassVar
  drives it); `_reject_server_managed` raises a dedicated `ServerManagedParamsRejected(ValueError)` with `.params`.
- `toolkit_config.py::_map_exc`: `ServerManagedParamsRejected` → 422 `server_managed` with `details={"params": [...]}`
  (before the generic `ValueError` branch).
- `toolkit_overrides.py` PUT (`/me`): refuse any constructor server-managed key with 422 `server_managed`
  before vaulting.
- `toolkits.py` generic assign: a client value for a server-managed param → 422 `server_managed`; fill
  `source="app"` from `self.request.app`; `_missing_required_params` ignores filled names.
- `testing.py`: delete `_KNOWN_APP_DEPS`; `_instantiate_tool` fills from `cls.server_managed_params` (`app` source);
  execute body keys that are server-managed → 422 `server_managed`.
- Tests `test_put_rejects_server_managed_param` (PUT and `/me`; stored spec never contains it — neither `config` nor
  `secret_refs` on the database backend) and `test_builtin_dicts_deleted_and_schema_for_matches_golden`.

**NOT in scope**: core declaration (TASK-3985); the identity-key switch on these files (FEAT-621 M13 /
TASK-3988); scope/option checks (TASK-3990).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` | MODIFY | delete _SERVER_MANAGED; ServerManagedParamsRejected |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py` | MODIFY | _map_exc → 422 server_managed |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py` | MODIFY | /me PUT refuses server-managed keys (422) |
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | assign: refuse client value, fill app source from ClassVar |
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | delete _KNOWN_APP_DEPS; _instantiate_tool from ClassVar; execute body refusal |
| `packages/ai-parrot-server/tests/studio/test_server_managed_server.py` | CREATE | PUT / /me / assign / execute refusals; dicts deleted; golden |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.server_params import ServerParam, constructor_server_params, method_server_params  # TASK-3985
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py
_SERVER_MANAGED = {  # :40-43 ← anchor (occurrences: 1)
    def _reject_server_managed(schema, params) -> None:  # :166-175 — raises ValueError today
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py
    def _map_exc(self, exc):  # :48 — ValueError → 422 invalid_params :52-53
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py
    async def put(self):  # :127 — offending/not_overridable check :146-153; vault write :170-181
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
def _missing_required_params(cls, provided) -> list[str]  # ends :153; _assign_generic :443-460; _assign_infographic :421-441
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py
_KNOWN_APP_DEPS: dict[str, str] = {  # :42-44 ← anchor (occurrences: 1)
def _instantiate_tool(cls, app) -> AbstractTool:  # :122-161 — app_key = _KNOWN_APP_DEPS.get(pname) :153
result = await instance.execute(**execute_request.args)  # :393
```

### Does NOT Exist
- ~~`ServerManagedParamsRejected`~~ — created here (server-local; not a core name).
- ~~a 400 status for `server_managed`~~ — it is 422 everywhere (spec v0.2.1 fix, X14).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_config.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_server_managed_server.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore._reject_server_managed",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py#AgentToolingStore.schema_for",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#_instantiate_tool",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#_missing_required_params",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkit_overrides.py#StudioUserToolkitOverrideHandler.put"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- `testing.py` already returns 422 `server_managed` with `details.missing` (`:373-379`): reuse that shape.
- Golden comparison reuses `packages/ai-parrot/tests/tools/data/feat622_builtin_schemas_golden.json` (TASK-3985):
  read it by path from the server test.
- Tests storing a secret **value** (PUT with a secret, `/me`) need the DocumentDB vault or FEAT-621 M12; skip with
  that reason otherwise (spec §4).

### Cross-feature ordering
- `tooling_store.py` and `toolkit_overrides.py` are identity files: FEAT-621 M13 (its W1) merges first, then
  FEAT-621 W3 for those files; this task merges after both and rebases (X16).
- `toolkit_config.py`, `toolkits.py`, `testing.py`: after the FEAT-621 W2/W3 task for each file (X16 per-file rule).

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
1. Introduce `ServerManagedParamsRejected` and map it to 422 `server_managed` — *why*: one code across PUT/`/me`/assign/execute (X14).
2. Delete both dicts; read the ClassVar — *why*: G4.
3. `/me`, assign and execute refusals/fills — *why*: AC "cannot be set via PUT, `/me`, the assign JSON, the execute body".
4. Tests; mutation: re-add `_SERVER_MANAGED` usage ⇒ dict-deleted assertion RED.

### `packages/ai-parrot-server/src/parrot/handlers/studio/tooling_store.py` (MODIFY)
```python
# DELETE tooling_store.py:40-43 (`_SERVER_MANAGED = { … }`); in schema_for drop the server_managed kwarg:
        envelope = build_schema_envelope(slug, cls)


class ServerManagedParamsRejected(ValueError):
    """A client supplied a server-managed parameter (HTTP 422 ``server_managed``)."""

    def __init__(self, params: list[str]) -> None:
        self.params = params
        super().__init__(f"Server-managed parameters cannot be set: {', '.join(params)}")
# FILL IN: _reject_server_managed raises ServerManagedParamsRejected(sorted(forbidden))
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# DELETE testing.py:42-44 (`_KNOWN_APP_DEPS`); in _instantiate_tool replace `app_key = _KNOWN_APP_DEPS.get(pname)` (:153):
        declared = (getattr(cls, "server_managed_params", None) or {}).get(pname)
        app_key = declared.key if declared is not None and declared.source == "app" else None
# FILL IN: execute — refuse body keys in method/constructor server-managed names with 422 server_managed (before validate_args :389)
```

### FILL IN checklist
- [ ] `toolkit_config.py::_map_exc` branch order; `toolkit_overrides.py` refusal placement (before vault); `toolkits.py` fill/refusal.

---

## Acceptance Criteria

- [ ] PUT and `/me` with the probe's constructor param → 422 `server_managed`; the stored spec never contains it.
- [ ] `grep -n "_SERVER_MANAGED\|_KNOWN_APP_DEPS" packages/ai-parrot-server/src` → 0 matches.
- [ ] `schema_for("wiki")` / `schema_for("infographic")` equal the golden copy.
- [ ] Execute body with a server-managed key → 422 `server_managed`; assign JSON with one → 422 `server_managed`.
- [ ] Existing FEAT-593 suites pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_server_managed_server.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_tooling_store.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_config.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkit_overrides.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_server_managed_server.py
async def test_put_rejects_server_managed_param(host_plugins): ...
def test_builtin_dicts_deleted_and_schema_for_matches_golden(): ...
async def test_execute_and_assign_refuse_server_managed_body_key(host_plugins): ...
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
