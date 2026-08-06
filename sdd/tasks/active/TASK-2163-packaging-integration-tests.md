# TASK-2163: Packaging extra, route wiring, integration tests and acceptance sweep

**Feature**: FEAT-417 — CommCenter — Bulk Notification Sender over NotifyWorker
**Spec**: `sdd/specs/commcenter-notify.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2153, TASK-2154, TASK-2155, TASK-2156, TASK-2157, TASK-2158, TASK-2159, TASK-2160, TASK-2161, TASK-2162
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10. Final task: declare the optional dependency, wire the
handler into the app, write the cross-cutting integration tests, and verify
**every** acceptance criterion in spec §5.

This is also where the **release-gating strategy** (spec §7) is realized: the
string-`template=` path cannot be exercised against a live worker until the new
`async-notify` ships, so the suite proves the contract via captured payloads
plus one real smoke test on the `TEMPLATE_DIR` **file** path that works today.

---

## Scope

- Add the `comm-center` extra to `ai-parrot-server` and the `all` aggregator.
- Wire `CommCenterHandler` into app route setup.
- Write the integration tests from spec §4.
- Write the `TEMPLATE_DIR`-file smoke test.
- Add Excel/CSV fixtures shared across the suite.
- Update `docs/` per spec §5.
- Run the full acceptance sweep against spec §5 and record the result.

**NOT in scope**:
- Implementing feature behavior (TASK-2153…2162).
- Executing the DDL against a live database (operator step).
- Bumping `async-notify` to the unreleased string-template version.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/pyproject.toml` | MODIFY | `comm-center` extra + `all` aggregator |
| App route wiring (`app.py` / `BotManager`) | MODIFY | Instantiate handler, call `.setup(app)` |
| `packages/ai-parrot-server/tests/handlers/test_comm_center_integration.py` | CREATE | Integration tests |
| `packages/ai-parrot-server/tests/handlers/conftest.py` | MODIFY | Shared fixtures |
| `packages/ai-parrot-server/tests/fixtures/recipients.csv` / `.xlsx` | CREATE | Test data |
| `docs/comm_center.md` | CREATE | API docs incl. per-provider mapping + ceilings |

---

## Codebase Contract (Anti-Hallucination)

> Verified fresh 2026-08-06.

### Verified Imports

```python
from parrot.handlers.comm_center import CommCenterHandler     # TASK-2159
from notify.server.wrapper import NotifyWrapper               # verified importable
from notify.models import Actor, Account, Chat, Channel, TeamsChannel
from notify.conf import NOTIFY_WORKER_STREAM, TEMPLATE_DIR    # verified live
```

### Existing Signatures to Use

```toml
# packages/ai-parrot-server/pyproject.toml:28-34 — VERIFIED current base deps
dependencies = [
    "ai-parrot",
    "pyarrow>=25.0",
]

# :36+ — extras pattern to follow
[project.optional-dependencies]
scheduler = ["apscheduler==3.11.2"]
mcp = ["aioquic==1.3.0", "pylsqpack==0.3.23", "click>=8.1.7", "PyYAML>=6.0.2"]
a2a = ["PyJWT>=2.8.0"]
autonomous = ["aiofiles>=23.0"]
all = ["ai-parrot-server[scheduler,mcp,a2a,autonomous]"]
#      ↑ ADD comm-center HERE TOO
```

```python
# packages/ai-parrot-server/src/parrot/handlers/scraping/info.py:123 — wiring pattern
def setup(self, app: web.Application) -> None: ...
# Call site convention: instantiate the handler, then handler.setup(app)
```

```python
# notify/conf.py — VERIFIED live
TEMPLATE_DIR = PosixPath('/home/jesuslara/proyectos/ai-parrot/templates')
NOTIFY_WORKER_STREAM = "NotifyWorkerStream"
```

### Does NOT Exist

- ~~`async-notify` in `ai-parrot-server` base dependencies~~ — base deps are
  exactly `["ai-parrot", "pyarrow>=25.0"]`. Add it as an **extra**, not a base dep.
- ~~A released `async-notify` accepting a template **string**~~ — 1.5.5 does not
  (`TemplateParser` has no `from_string`; verified again 2026-08-06). Do **not**
  pin a version that does not exist. Keep the floor at `>=1.5.5` and note the
  future bump in the docs.
- ~~`packages/ai-parrot-server/tests/` not existing~~ — it exists, with a
  `handlers/` subdirectory (verified). Put tests there.
- ~~A live NotifyWorker in CI~~ — none. Every send assertion uses captured
  payloads from a mocked `NotifyClient`.

---

## Implementation Notes

### The extra
```toml
comm-center = [
    "async-notify>=1.5.5",
    "pandas>=2.2",
    "openpyxl>=3.1.2,<=3.1.5",   # matches root pyproject.toml:133 override
]
all = ["ai-parrot-server[scheduler,mcp,a2a,autonomous,comm-center]"]
```

### Integration tests (spec §4)
| Test | Description |
|---|---|
| `test_end_to_end_json_recipients_mocked_worker` | JSON list → 202 → assert exact captured payloads |
| `test_end_to_end_multipart_xlsx_mocked_worker` | `.xlsx` upload → per-recipient personalization |
| `test_end_to_end_stored_template_partial_render` | Template row → `{{today}}` resolved, `{{ name }}` literal |
| `test_smoke_template_file_path_real_notify` | **Real `TEMPLATE_DIR` filename** through `NotifyWrapper` — the path that works on 1.5.5 today |
| `test_mixed_valid_invalid_rows_partial_send` | Some skipped, rest published; both reported |
| `test_end_to_end_single_message_mocked_worker` | `/message` payload builds a valid `Actor` |
| `test_dry_run_then_real_send_produce_same_payload` | Preview fidelity |

### Docs (spec §5)
`docs/comm_center.md` must cover the API, the **per-provider recipient mapping
table**, and the two ceilings stated plainly:
1. **No delivery confirmation** — the worker publishes no results; status tops
   out at `queued`. The UI must not render "delivered".
2. **Bare-placeholder limitation** — record placeholders must be written
   `{{ field }}`; filters/conditionals over them are unsupported.

Also document the `{{username}}` fallback and the reserved names.

### Acceptance sweep
Walk every checkbox in spec §5, run the commands, and record pass/fail in the
completion note. **Do not tick a box you did not execute.**

### Key Constraints
- Suite must pass **without** a live Redis, Postgres or NotifyWorker.
- Importing the handler without `async-notify` installed must not raise.
- `ruff check` clean across all feature files.

### References in Codebase
- `packages/ai-parrot-server/pyproject.toml:28-64` — deps + extras
- `packages/ai-parrot-server/tests/handlers/` — test location convention
- Spec §4 Integration Tests, §5 Acceptance Criteria, §7 gating

---

## Acceptance Criteria

- [ ] `comm-center` extra exists and is included in `all`
- [ ] `async-notify` is **not** a base dependency
- [ ] `CommCenterHandler` wired into app routes and reachable
- [ ] All 7 integration tests from the table pass
- [ ] Smoke test exercises the real `TEMPLATE_DIR` **file** path
- [ ] Suite passes with no live Redis / Postgres / worker
- [ ] Importing the handler without `async-notify` does not raise
- [ ] `docs/comm_center.md` covers API, per-provider mapping, both ceilings,
      the `username` fallback and reserved names
- [ ] Full spec §5 acceptance sweep executed and recorded
- [ ] `pytest packages/ai-parrot-server/tests/handlers/ -v` green
- [ ] `ruff check` clean on every file this feature touched

---

## Test Specification

```python
import pytest
from notify.server.wrapper import NotifyWrapper
from notify.models import Actor


class TestIntegration:
    async def test_end_to_end_json_recipients(self, client, auth, fake_notify):
        r = await client.post("/api/v1/comm_center/sender", json={
            "provider": "email",
            "recipients": [{"name": "Ana", "email": "ana@example.com"},
                           {"name": "Luis", "email": "luis@example.com"}],
            "template": "Hola {{ name }}, hoy es {{ today }}"})
        assert r.status == 202
        assert len(fake_notify) == 2
        for msg, stream, use_wrapper in fake_notify:
            assert use_wrapper is False
            assert "recipient" in msg and "recipients" not in msg
            assert isinstance(NotifyWrapper(**msg).recipients[0], Actor)
            assert msg["username"]                    # never absent

    async def test_end_to_end_multipart_xlsx(self, client, auth, fake_notify,
                                             recipients_xlsx):
        ...

    async def test_smoke_template_file_path(self):
        """The TEMPLATE_DIR filename path — works on async-notify 1.5.5 today."""
        from notify.conf import TEMPLATE_DIR
        assert TEMPLATE_DIR.exists()
        ...

    async def test_mixed_valid_invalid_rows(self, client, auth, fake_notify):
        ...


class TestPackaging:
    def test_comm_center_extra_declared(self):
        import tomllib, pathlib
        p = tomllib.loads(pathlib.Path(
            "packages/ai-parrot-server/pyproject.toml").read_text())
        extras = p["project"]["optional-dependencies"]
        assert "comm-center" in extras
        assert any("comm-center" in a for a in extras["all"])
        assert not any("async-notify" in d for d in p["project"]["dependencies"])

    def test_handler_imports_without_async_notify(self, monkeypatch):
        ...
```

---

## Agent Instructions

1. **Read the spec** — §4, §5 and §7 gating in full
2. **Check dependencies** — ALL of TASK-2153…2162 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read `pyproject.toml` before editing;
   confirm `TemplateParser` still lacks `from_string` before pinning a version
4. **Update status** in `sdd/tasks/index/commcenter-notify.json` → `"in-progress"`
5. **Implement** per scope
6. **Verify** every spec §5 criterion — execute, do not assume
7. **Move** to `sdd/tasks/completed/TASK-2163-packaging-integration-tests.md`
8. **Update index** → `"done"`, set `completed_at` on the index header
9. **Fill in the Completion Note** with the acceptance-sweep result

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Acceptance sweep result**: <criteria passed / total, and any that failed>

**Deviations from spec**: none | describe if any
