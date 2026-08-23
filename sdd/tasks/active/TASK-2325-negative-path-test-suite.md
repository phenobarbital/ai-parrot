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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
