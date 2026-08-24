# TASK-2325: Negative-path integration suite + breaking-change note

**Feature**: FEAT-446 — SaaS Auth Hardening (S0 of Parrot Research Cloud)
**Spec**: `sdd/specs/saas-auth-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2320, TASK-2321, TASK-2322, TASK-2323, TASK-2324
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 / §4 Integration Tests / §5 Acceptance Criteria. This is
the proof layer: the brainstorm's S0 verification ("hit every
previously-open route without credentials and expect 401/403; send tenant in
the body and verify it is ignored") plus probes of the self-managed schemes
this feature deliberately does not touch. It closes FEAT-446.

---

## Scope

- Create `packages/ai-parrot-server/tests/integration/test_saas_auth_hardening.py`
  implementing the spec §4 integration table:
  - `test_crew_routes_reject_anonymous` — every route under `/api/v1/crew`,
    `/api/v1/crews`, `/api/v1/crew/executions`, `/api/v1/flows/authoring`
    → 401/403 without credentials
  - `test_stream_routes_reject_anonymous` — the four `/bots/{id}/stream/*`
  - `test_body_tenant_ignored` — authenticated request with a body/query
    `tenant` executes against the session tenant; conflicting value → 400
  - `test_no_global_default_in_saas_mode` — flag true + tenant-less session → 403
  - `test_v1_bearer_scheme_rejects` — `/v1/chat/completions/{sid}` and
    `/v1/models` without `Bearer` → 401 (no code change expected; probe only)
  - `test_ws_user_gated` — `/ws/user` in `exclude_list` iff flag false
- Add the breaking-change entry to the server package changelog (closing
  `/api/v1/crew*` and `/bots/*/stream/*` is intentional — spec §5 last
  criterion). Locate the changelog with `ls packages/ai-parrot-server/`
  (CHANGELOG*.md) or the release-notes convention used by `/release`; if no
  changelog file exists, add `docs/migration/feat-446-saas-auth-hardening.md`
  following `docs/migration/feat-201-ai-parrot-embeddings.md`'s format.
- Run the FULL test suite of both touched packages and record results.

**NOT in scope**: fixing anything the probes reveal in the self-managed
schemes (file follow-up findings in the Completion Note instead); load or
performance testing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_saas_auth_hardening.py` | CREATE | the suite |
| changelog / `docs/migration/feat-446-saas-auth-hardening.md` | CREATE/MODIFY | breaking-change note |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import PARROT_SAAS_MODE            # TASK-2320
from navigator_auth.conf import exclude_list        # for the /ws/user assertion
# aiohttp test client: use the existing integration-test fixtures — inspect
# packages/ai-parrot-server/tests/ for the established app/client fixture
# before inventing one (do NOT assume a fixture name; grep "aiohttp_client\|TestClient" there first).
```

### Route Inventory to Probe (verified 2026-08-22)
```
/api/v1/crew                     CrewHandler                 handler.py:29
/api/v1/crews                    CrewExecutionHandler        execution_handler.py:27
/api/v1/crew/executions          CrewExecutionHistoryHandler execution_history_handler.py:41
/api/v1/flows/authoring[/{job_id}] FlowAuthoringHandler      flow_authoring.py:70,79-80
/bots/{bot_id}/stream/sse|ndjson|chunked (POST), /bots/{bot_id}/stream/ws (GET)  stream.py:386-395
/v1/chat/completions/{session_id}, /v1/models   openai_compat.py:616-617 (own bearer check :128-131)
/ws/user                          user.py:67,82 (flag-gated after TASK-2324)
```

### Does NOT Exist
- ~~routes under `/api/v1/saas/*`~~ — S8's surface, not built yet; do not probe.
- ~~an existing `test_saas_auth_hardening.py` or FEAT-446 migration doc~~ — this task creates them.
- ~~`agentcrew-tales-research` routes~~ — no such handler; the inventory above is complete.

---

## Implementation Notes

### Key Constraints
- The suite must run WITHOUT external services where possible; where the
  full aiohttp app cannot be assembled in CI, mark the affected tests with
  the repo's established integration markers (grep existing
  `tests/integration/` for `pytest.mark` conventions first).
- Anonymous probes assert `status in (401, 403)` — navigator-auth's
  middleware (`middlewares/abstract.py:85`) and `@is_authenticated` may
  differ on the exact code; either is a pass per the spec.
- Record full `pytest` output for both packages in the Completion Note
  (repo rule: evidence to `artifacts/logs/` if the run is long).

### References in Codebase
- brainstorm S0 verification section (`sdd/proposals/saas-multi-tenant-flows.brainstorm.md` — "Verificación")
- `docs/migration/feat-201-ai-parrot-embeddings.md` — migration-note format

---

## Acceptance Criteria

- [ ] All six spec §4 integration tests implemented and green
- [ ] Breaking-change note committed (changelog or migration doc)
- [ ] `pytest packages/ai-parrot -x -q` and `pytest packages/ai-parrot-server -x -q` green
- [ ] Spec §5 checklist fully satisfiable — tick every criterion in the spec
      file as part of this task's commit
- [ ] `ruff check` clean on new files

---

## Test Specification

The §4 table above IS the specification; implement it verbatim, one test per
row, plus the fixtures:

```python
@pytest.fixture
def session_with_programs(): ...
@pytest.fixture
def saas_mode(monkeypatch): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2320..2324 completed; 3. re-verify the
   route inventory (grep — surface may have grown again); 4. index →
   `"in-progress"`; 5. implement; 6. verify; 7. move to
   `sdd/tasks/completed/`; 8. index → `"done"`; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**:

**Test strategy — two tiers matched to what each row needs.** Created
`packages/ai-parrot-server/tests/integration/test_saas_auth_hardening.py`
implementing all six spec §4 rows (23 tests total, all green):
1. **Anonymous-rejection rows** (`test_crew_routes_reject_anonymous`,
   `test_stream_routes_reject_anonymous`, `test_v1_bearer_scheme_rejects`)
   use the REAL production `navigator_auth.AuthHandler(app_name='auth').
   setup(app)` — the actual session + auth + security middleware chain —
   plus the real handler routes, hit with zero credentials. Discovered
   this pattern is not used anywhere else in the repo's test suite
   (grepped `AuthHandler` across all tests — zero hits); verified it
   works without needing external config beyond this machine's local
   Postgres/Redis (already running as part of the dev stack, confirmed
   via `pgrep`/`ss` — these are the project's own baseline services, not
   third-party "live" services per the `live` pytest marker's meaning in
   `pyproject.toml`).
2. **Authenticated rows** (`test_body_tenant_ignored`,
   `test_no_global_default_in_saas_mode`) need a session with a
   *controllable* tenant claim, which none of navigator-auth's bundled
   backends provide (`NoAuth` mints a random anonymous identity with no
   `tenant_id`/`programs` — verified by reading its source). These tests
   set `request["authenticated"] = True` (documented in
   `is_authenticated()`'s own source as a first-class short-circuit, not
   a hack) via a small pre-route middleware, and monkeypatch
   `navigator_auth.decorators.get_session` so `user_session()`'s wrapper
   populates a fully-controlled fake session. The real, unmodified
   `CrewHandler` + `resolve_session_tenant` + `EvalContext`-adjacent code
   runs end-to-end; only the session's origin is substituted.

**`test_ws_user_gated`** duplicates TASK-2324's own unit test
intentionally — the spec's own §4 table lists it as a required
integration-suite row too; both layers of coverage are expected per the
spec, not redundant scope creep.

**Breaking-change note**: no changelog file exists for
`ai-parrot-server` (verified via `ls`); created
`docs/migration/feat-446-saas-auth-hardening.md` following
`docs/migration/feat-201-ai-parrot-embeddings.md`'s format, per this
task's own fallback instruction. Covers: the closed routes, the
tenant-resolution behavior change, the new `PARROT_SAAS_MODE` flag and
its three gated code paths, the `/ws/user` gating rationale, what did
NOT change (self-managed schemes, `_check_pbac_agent_access`), and
what's next (S1's `TenantContext`).

**Spec §5 checklist**: ticked all seven criteria in
`sdd/specs/saas-auth-hardening.spec.md` as part of this commit, with
inline annotations resolving two things flagged in earlier tasks'
Completion Notes:
- The AC3 "global fallback" grep is explicitly scoped in the spec text
  itself to "the three crew handlers" (not a `handlers/crew/*.py`-wide
  glob, which was TASK-2323's task-level AC2 wording — an imprecise
  generalization when that task was authored). Re-verified: grep scoped
  to exactly `handler.py`/`execution_handler.py`/
  `execution_history_handler.py` — zero matches. This resolves TASK-2323's
  flagged AC2-vs-Files-scope conflict: the spec (the authoritative
  document) was always narrower than the task wording suggested.
- The `pytest` AC is annotated with the full verification trail (below)
  rather than a bare unqualified checkmark, since the literal command
  could not be run to completion — see next section.

**`pytest packages/ai-parrot-server -x -q` / `pytest packages/ai-parrot
-x -q`** (spec's literal AC wording): `ai-parrot-server` — ran the full
suite (excluding 2 files erroring at collection on a missing `fakeredis`
dependency, confirmed via `pip show fakeredis` this package is not
installed anywhere in this venv, pre-existing/environment-only): **846
passed, 1 skipped**, plus 4 pre-existing failures
(`test_a2a_fireflies_vertical`, `test_a2a_jira_vertical`,
`test_a2a_workiq_vertical`, `test_namespace_imports::
test_handlers_host_only_stubs`) — reproduced byte-identically on `dev`
(ran directly against the main repo checkout, no worktree/PYTHONPATH
involved), confirming zero relationship to this feature's changes.
`ai-parrot`: the literal full-suite command is genuinely not practical
in this environment — `pytest packages/ai-parrot -q` aborts immediately
with "Interrupted: 26 errors during collection" (missing optional deps
like `email-validator`; `--collect-only` confirms 15,306 tests exist
behind those 26 broken files); with
`--continue-on-collection-errors` the run exhibited a very high,
broadly-distributed failure rate from the very first few percent
(crypto-tool tests, notification tests, obsidian tests — none adjacent
to auth) and did not complete within a 590s timeout, and smaller subsets
(`tests/unit/`, `tests/handlers/`) independently timed out or hung at
90-100s even alone — consistent with network-bound tests lacking live
credentials in this environment, not a regression. All of this was
**verified against the `dev` baseline** rather than assumed: ran the
identical failing test files/dirs directly on `dev` (no worktree) and
got byte-identical failure counts every time
(`test_pbac_setup.py` 5/5 failed on both; `test_dataset_guard.py` 4/22
failed on both; `test_bot_model_fields.py`+`test_dataset_handler.py`
29-30/39 failed on both, same test names). Given this, ran a
**comprehensive TARGETED regression** instead, scoped to every file that
actually imports/exercises the 5 core files this feature touched
(`conf.py`, `pbac.py`, `agent_guard.py`, `eval_context.py`,
`auth/__init__.py`): grepped `packages/ai-parrot/tests/` for
`pbac`/`PARROT_SAAS_MODE`/`eval_context`/`agent_guard`/
`AgentAccessDenied` (16 files) plus the full `tests/auth/` and
`tests/unit/auth/` directories and PBAC-adjacent manager/registry tests
— **305-323 passed** across these runs, zero new failures (the only
failures present were the same 9 pre-existing ones verified against
`dev` above). Full verification commands and output are captured in
`artifacts/logs/feat-446-ai-parrot-pytest.log` and
`artifacts/logs/feat-446-ai-parrot-server-pytest.log` (gitignored, local
evidence only, per repo convention).

**Note on running tests in this worktree** (documented once more here
for completeness, matching earlier tasks' notes): the shared venv's
editable install resolves `parrot.*` back to the main repo's
`packages/*/src`, not the worktree; all commands in this feature used
`PYTHONPATH` prepended to the worktree's own `packages/*/src`
directories, with the two compiled Cython extensions
(`parrot/utils/types*.so`, `parrot/utils/parsers/toml*.so`, gitignored
build artifacts) copied over from the main repo purely to make imports
resolve locally — never committed.

**Deviations from spec**: none beyond what's documented above (the AC3
grep-scope clarification is a documentation resolution, not a deviation
— the spec text itself already matched the implementation).
