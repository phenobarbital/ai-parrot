# TASK-3546 Research: Full-Profile Performance Measurement

**Feature**: FEAT-581 — Deterministic E2E Gate and Agentic Exploration
**Spec**: `sdd/specs/agentic-e2e-testing.spec.md`
**Module**: M9 (spec §8 "Implementation Spike Gates": "Record full-profile
measurement with authorized real services; if unavailable retain
opt-in/BLOCKED status — owner: M9.")
**Acceptance criteria addressed**: AC16
**Date**: 2026-09-24

---

## 0. Baseline and Provenance

| Item | Value |
|---|---|
| Worktree HEAD at measurement time | `98a217451` |
| Host | Linux 7.0.0-31-generic x86_64, shared workspace interpreter (Python 3.12), sandboxed worktree checkout, invoked read-only against the shared `.venv` |
| Depends-on tasks (must be done first, per this task's contract) | TASK-3545 (done, commit lineage includes `98a217451`), TASK-3544 (done) |

Source anchors re-verified byte-for-byte against this task's Codebase
Contract (all three match exactly):

| File | sha256 |
|---|---|
| `docker/integrations/server.py` | `c580501988bc7a82b8ba884bb8f1ded9542083f7e86cf5c0bb9a71e983ebc302` |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | `4a02c5feb76658ddd89a63649ae28bd13f1cdd39e9feeab51343048851c80844` |
| `.github/workflows/ci.yml` | `4916a147e2886dca6abfa60602197998e099c7477a78d6c05139111b0e502ca6` |

Additional anchors read for this spike (not part of this task's own file
scope; none modified):

| File | sha256 |
|---|---|
| `packages/ai-parrot-server/src/parrot/e2e/targets/botmanager.py` | `163711d0dd24fcb367f5e31d2b29783df613a22ddb5d181ead3d37be661da734` |
| `run.py` (repo-root real application entry point) | `7bac61f5ce5cb819548fe5d1f319a56212f7fa1e8ad583013bf5a7788f054be7` |
| `requirements/docker-compose.yml` (dev Redis/Memcache compose) | `9a513dda3418cbf7a309d875dbd081c10b7434992e8c578ed6231649703a81ae` |

---

## 1. What "full profile" means here

Spec §2 "Target and Authentication Design": *"The full target launches the
real application with an explicit command/readiness profile, never an
assumed `/healthz`. A local opt-in spike with real configured
Postgres/Redis must measure three warm starts and three SIGTERM stops.
Full is eligible for automatic dev-loop use only if every measured
readiness is ≤15s and stop ≤10s; otherwise keep it nightly/opt-in."*

Two independent things had to be checked before any timing could be
recorded:

1. **Is there an executable contract for "full" at all?** — i.e. can the
   E2E harness (`parrot e2e up botmanager --config ...`) even be asked to
   start a full-profile target.
2. **Are the "real configured Postgres/Redis" services this spike requires
   genuinely authorized/available in this sandbox?**

Both are answered below; both are negative, independently of each other.

---

## 2. Method and observations

### 2.1 Harness-level "full" profile does not exist

`packages/ai-parrot-server/src/parrot/e2e/targets/botmanager.py`'s own
`_require_minimal_profile()` (lines 138-159) rejects `profile="full"`
unconditionally:

```python
if config.profile == "full":
    raise E2EConfigError(
        "botmanager 'full' profile requires an explicit command/readiness contract "
        "this adapter does not implement (spec §2); only 'minimal' is supported",
        reason_code="botmanager_full_profile_unsupported",
    )
```

Reproduced directly against this worktree's own code (no shared-venv
drift — imported from this checkout's own `src/`, per
`.claude/rules/worktree-management.md` §4). First, the schema layer alone:

```
$ python -c "
from parrot.e2e.models import TargetConfig
TargetConfig(kind='botmanager', profile='full')
print('constructed OK (schema-level accepted)')
"
constructed OK (schema-level accepted)
```

`TargetConfig` itself accepts the literal (`profile` is a plain
`minimal|full` enum at the schema layer per spec §2's `TargetConfig` model
table) — so the rejection is not a validation-layer accident. Then the
actual adapter call every real `parrot e2e up`/`run` invocation would make:

```
$ python -c "
import asyncio
from pathlib import Path
from parrot.e2e.models import TargetConfig
from parrot.e2e.targets.botmanager import build_botmanager_adapter

async def main():
    adapter = build_botmanager_adapter()
    config = TargetConfig(kind='botmanager', profile='full')
    try:
        await adapter.prepare(config, run_id='spike-full-profile-check', worktree=Path.cwd())
    except Exception as exc:
        print(type(exc).__name__, getattr(exc, 'reason_code', None), exc)

asyncio.run(main())
"
E2EConfigError botmanager_full_profile_unsupported botmanager 'full' profile requires an explicit command/readiness contract this adapter does not implement (spec §2); only 'minimal' is supported
```

`prepare()` raises `E2EConfigError` (`reason_code=
"botmanager_full_profile_unsupported"`) before any process is spawned —
i.e. **no target adapter shipped so far can start a full-profile
application under `parrot e2e`.** `ui`/`browser`/`mcp-*` adapters have no
notion of "full" vs "minimal" applicability to a whole *application*
process at all; only `botmanager` models that axis, and it refuses it.

This alone is enough to make three measured warm start/stop cycles through
the harness impossible on this branch — not merely difficult. It is a
scope observation, not a defect: TASK-3530's own completion note flagged
this as an explicit, disclosed decision ("`profile='full'` support is
explicitly out of scope, not a gap — flagged for a future task if
needed"), consistent with spec §3 M4's own eligibility annotation ("no
initially... Verify real handler session payload and installed Obscura
flags in spike; do not guess them").

### 2.2 Real application entry point and its dependencies

Spec §2 describes the full target as launching "the real application."
The repository's own real application entry point is the workspace-root
`run.py` (sha256 `7bac61f5…f054be7`):

```python
from navigator import Application
from navigator.ext.memcache import Memcache
from app import Main

app = Application(Main, enable_jinja2=True)
```

`from app import Main` requires an `app` package that is **not present in
this checkout**:

```
$ ls app
ls: no se puede acceder a 'app': No existe el archivo o el directorio
# (this sandbox's shell locale is es_ES; message translates to
# "cannot access 'app': No such file or directory")
```

This is a generic `navigator-api` project template entry point, not a
concrete "app" implementation bundled with `ai-parrot` — there is no
"the real application" module to boot here at all, independent of any
missing infrastructure. Building one is explicitly out of this task's
scope ("no new runtime code").

### 2.3 Postgres/Redis authorization check

Spec §2: *"A local opt-in spike with real configured Postgres/Redis..."* —
"configured" is read literally: an operator-provisioned, credentialed
instance this sandbox is authorized to use, not an ad hoc container this
research task would need to stand up and configure itself (which would be
new infrastructure provisioning, out of this documentation task's scope,
and would still not solve §2.2's missing `app` module).

Checked directly in this sandbox:

```
$ command -v redis-server || echo MISSING
MISSING
$ command -v psql || echo MISSING
MISSING
$ command -v pg_ctl || echo MISSING
MISSING
$ env | grep -iE 'DB_HOST|POSTGRES|PG_|REDIS'
# (no output — nothing configured)
$ docker ps
CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
# (daemon reachable, but zero containers running — no standing Postgres/Redis service)
```

- No `redis-server` binary — consistent with TASK-3530's own completion
  note ("absent on this host") and TASK-3548's ("missing `redis-server`/UI
  build toolchain"): this is the same, already-documented gap, not new.
- No Postgres client/server tooling at all (`psql`/`pg_ctl` both absent),
  and no `DB_HOST`/`POSTGRES_*`/`PG_*` environment configured.
- Docker's daemon is reachable, but nothing is currently running — using it
  to improvise a disposable Postgres+Redis pair for this spike would be
  *provisioning new, unauthorized infrastructure* for a research task whose
  own instructions require "genuinely authorized/configured services," not
  ad hoc substitutes. (Contrast TASK-3518's own session-wire-format spike,
  which *did* use a disposable `redis:7-alpine` container — but only to
  validate a *protocol/wire contract*, never to fabricate a performance
  measurement it would then present as representative production timing.)

### 2.4 Conclusion

Both preconditions for AC16's three-cycle measurement are unmet, for two
independent reasons:

1. No target adapter shipped on this branch can start a full-profile
   application through `parrot e2e` at all (`E2EConfigError`,
   `botmanager_full_profile_unsupported`).
2. Even measuring "the real application" (`run.py`) directly, outside the
   harness, is blocked: its own `app` module does not exist in this
   checkout, and neither Postgres nor Redis is an authorized, configured
   service in this sandbox.

No timing numbers are recorded. Inventing plausible-looking start/stop
durations here would violate this task's own instruction ("Missing
infrastructure is an explicit BLOCKED report, never invented timing") and
AC16's explicit permission to record BLOCKED instead.

---

## 3. Disposition

| Required question | Status | Evidence |
|---|---|---|
| Document install/preflight, fixture Redis/session limits, live cost semantics, browser setup, ownership/lease recovery, evidence reuse | **PASS** | `docs/testing/agentic-e2e.md` §1-§6, each section grounded in a read, hashed source file or a live-reproduced CLI command in this sandbox |
| Run three full-profile warm starts/stops with authorized configured services | **BLOCKED** | §2.1 (no harness-level full-profile adapter exists), §2.2 (`run.py`'s own `app` module absent), §2.3 (no `redis-server`, no Postgres, no configured env, no authorized standing infra in this sandbox) |
| All measurements meet 15s/10s for automatic eligibility, else retain opt-in | **N/A — retained opt-in/nightly by default** | No measurement was possible (see above); full profile was already opt-in/nightly-only before this task and remains so. This spike neither promotes nor demotes it. |
| Verify documented file-scoped examples against current CLI and plans | **PASS** | `parrot e2e --help`, `parrot e2e status`, `parrot e2e verify --plan ...` were all executed live against this worktree's own code during authoring of `docs/testing/agentic-e2e.md` (§1, §5, §6 there reproduce the exact observed output) |

**AC16 disposition: BLOCKED, dependent-task-scope gap disclosed, no gate
impact.** This does not block AC15 (documentation, PASS above) and does
not invalidate any other module's evidence — full remains nightly/opt-in
exactly as it already was; nothing regresses. A follow-up task is required
before this measurement can ever be attempted, scoped to at least: (a) a
`botmanager` (or new) target adapter that defines "full"'s explicit
command/readiness contract, and (b) either a genuinely
operator-authorized Postgres/Redis pair in the CI/dev environment, or an
`app` module this repository actually ships and can boot standalone.

---

## 4. Rejected assumptions

- **Not assumed**: that `docker`'s mere presence in this sandbox
  constitutes "authorized/configured" Postgres/Redis for a performance
  spike — a daemon with zero running containers and no operator-declared
  compose file wiring them together is not a configured service.
- **Not assumed**: that the historical ~1.4s MCP / ~3.5s stubbed-BotManager
  timings mentioned in spec §2 could stand in for a full-profile
  measurement — the spec is explicit that those are "context, not
  acceptance evidence."
- **Not assumed**: that building a throwaway `app.Main` module or a
  temporary Postgres/Redis docker-compose file to force a measurement
  would be in scope — this task's own Scope forbids new runtime code and
  new dependencies, and spec §5 "Non-Goals" excludes "building a production
  authentication system" / treats "full-profile auth" as the real
  application's own separate concern.

---

## 5. Selected contract

No new contract is introduced by this research; it confirms the existing
one (`_require_minimal_profile`, §2.1 above) and records the sandbox's
missing-infrastructure disposition for AC16, per spec §8's own accepted
outcome ("if unavailable retain opt-in/BLOCKED status").
