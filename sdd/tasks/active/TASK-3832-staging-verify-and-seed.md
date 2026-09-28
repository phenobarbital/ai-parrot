# TASK-3832: Staging verification and idempotent seed

**Feature**: FEAT-611 — A2UI Linked Surfaces E2E (parallel track)
**Spec**: `sdd/specs/a2ui-linked-e2e-parallel.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3831
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2, §7 (PBAC resource string is inferred), §8 Q1, §9 S5. The Epson slug columns
(`epson_field_activity`: `day, visits, program, store_id`, placeholders `{firstdate}`/`{lastdate}`;
`epson_program_targets`: `program, target`) are *inferred* (F001). Before any scenario is written,
this task:

1. reads the real staging definitions, read-only, and records them as evidence (F020);
2. seeds the multiquery slug `epson_activity_vs_targets_mq` that S3 needs;
3. writes the demo PBAC policy and **proves** it: allow with the policy, deny without it, logging the
   evaluated resource/action strings so "policy absent" can be told apart from "guard missing".

It depends on TASK-3831 because the seed must run on the querysource 5.1.2 lock (spec Worktree Strategy:
M2 → M1). This is the only FEAT-611 task that writes to a shared database, and it writes to **staging only**.

---

## Scope

- Create `examples/agents/a2ui/linked_e2e/seed_staging.py` with `MQ_SLUG`, `assert_staging()`,
  `describe_slugs()`, `seed_multiquery()`, `prove_policy()` and a `main()` CLI.
- Create the example-local policy `examples/agents/a2ui/linked_e2e/policies/source-epson.yaml`.
- Run the script (describe → prove policy → seed, each only after human confirmation for writes) and
  record the results in `sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md`.
- Add a unit test for `assert_staging()` that loads the example module by path.

**NOT in scope**:
- The example server, agent, dashboard TOOL, runner and staging pytest suite (TASK for M8/M9).
- Any policy under the repo-root `policies/` directory — the demo policy lives only under the example.
- Any write to production. Any change to `QuerysourceToolkit`, `setup_dataplane_guard` or the guard.
- Deciding the `DataNotFound → []` question (§8 Q2); only record which date ranges have data.

**Why no `__init__.py`**: `examples/agents/a2ui/` has no `__init__.py` (verified: `ls examples/agents/a2ui/`),
and its sibling scripts run as standalone files. Follow that convention: `linked_e2e/` is a script directory,
not a package. The test therefore loads the module by path with `importlib.util.spec_from_file_location`
(repo pattern: `packages/ai-parrot-integrations/tests/voice/test_voice_demo_assets.py:41`).

**Why the test lives in `packages/ai-parrot/tests/outputs/a2ui/linked/`**: it is the FEAT-598 linked-surface
test directory, it already runs in the `ai-parrot` suite, and `assert_staging()` needs only stdlib + `navconfig`
(a core `ai-parrot` dependency). A test under `ai-parrot-tools` or `ai-parrot-server` would add nothing and
would couple the guard test to packages it does not use. The module keeps every heavy import
(`parrot_tools`, `parrot.auth`, `aiohttp`) inside functions so loading it in that test is cheap.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/a2ui/linked_e2e/seed_staging.py` | CREATE | Staging guard, read-only describe, MQ seed, policy proof, CLI |
| `examples/agents/a2ui/linked_e2e/policies/source-epson.yaml` | CREATE | Demo PBAC allow for `source:read` on `query_slug:public:epson_*` |
| `sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md` | CREATE | Evidence: real slug SQL/columns/placeholders, MQ frames, policy proof log |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_seed_staging_guard.py` | CREATE | `assert_staging()` refuses non-staging targets |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
from parrot_tools.querysource.toolkit import QuerysourceToolkit          # verified: packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py:64
# (MultiQueryResult / ExecutionResult are returned by the toolkit, not imported: models.py:52-74)
from parrot.auth.pbac import setup_dataplane_guard                       # verified: packages/ai-parrot/src/parrot/auth/pbac.py:292
from parrot.auth.permission import build_principal_context               # verified: packages/ai-parrot/src/parrot/auth/permission.py:166 (handler uses it: ui_surfaces.py:31,570)
from parrot.auth.exceptions import AuthorizationRequired                 # verified: packages/ai-parrot/src/parrot/auth/dataplane_guard.py:37 (`from .exceptions import AuthorizationRequired`)
from parrot.tools.dataset_manager.sources.resolver import PhysicalResources  # verified: resolver.py:47 (service.py:92 imports it the same way)
from aiohttp import web                                                  # verified: pbac.py:28
from navconfig import config                                             # verified: .venv navconfig/__init__.py (ns["config"] = Kardex(...))
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                                    # :64
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False, allow_external_sources=True,
                 include_sql=True, max_rows=200, forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)  # :77-88
    async def describe_slug(self, slug: str, dry_run: bool = False, tenant: str | None = None) -> SlugDetail  # :210
    async def validate_pipeline(self, pipeline: dict) -> PipelineValidation                                 # :523 (read-only)
    async def run_multiquery(self, pipeline=None, slug=None, conditions=None, tenant=None) -> MultiQueryResult  # :561 (read-only w/o Output)
    async def save_multiquery(self, slug: str, pipeline: dict, description: str, program: str | None = None,
                              overwrite: bool = False) -> SavedSlug                                         # :605-620
    async def _close(self) -> None                                                                           # :123 (closes the catalog)
# save_multiquery: raises WriteDisabledError unless allow_write; program = guard.resolve_write_program(program)
#   which RAISES "program is required when the toolkit is unrestricted" when programs=None and program=None
#   (catalog.py:134-150) → pass program=<detail.program_slug> or construct with programs=["<epson program>"].
#   Then _assert_pipeline_slugs_allowed + validate_pipeline + _raise_for_issues, then catalog.upsert(...)
#   which refuses overwrite of a slug owned by another program (catalog.py:275-309).

# packages/ai-parrot-tools/src/parrot_tools/querysource/models.py
class SlugSummary(BaseModel): slug; description; program_slug: str; provider; is_multiquery; placeholders   # :13-21
class SlugDetail(SlugSummary): placeholders_detail; filtering; fields; ordering; grouping; is_cached;
    cache_timeout; sql: str | None; pipeline: dict | None; rendered_query                                  # :38-50
class PipelineValidation(BaseModel): valid: bool; issues: list[PipelineIssue]; referenced_slugs; ...        # :85-93
class SavedSlug(BaseModel): slug: str; program_slug: str; action: Literal["inserted", "updated"]            # :119-124
class ExecutionResult(BaseModel): status; slug; rows; returned_rows: int; total_rows; truncated; columns: list[str]; ...  # :52-64
class MultiQueryResult(BaseModel): status: Literal["success","empty"]; results: dict[str, ExecutionResult]; duration_ms  # :69-74

# packages/ai-parrot/src/parrot/auth/pbac.py:292-351
def setup_dataplane_guard(app: web.Application, *, policy_dir: str = "policies", cache_ttl: int = 30) -> Optional[DataPlanePolicyGuard]
#   returns None (sets nothing) when PBAC cannot initialise; idempotent on app["dataplane_guard"].

# packages/ai-parrot/src/parrot/auth/dataplane_guard.py
async def authorize_source(self, ctx: Optional[PermissionContext], resources: "PhysicalResources") -> None  # :193
#   source gate :286-300 → check_access(eval_ctx, "source", f"{source_type}:{source_id}", "source:read", env);
#   deny → raises AuthorizationRequired and logs "DataPlanePolicyGuard DENY source:read user=%s source=%s".

# packages/ai-parrot/src/parrot/auth/permission.py:166-206
def build_principal_context(principal: str, *, channel: str, tenant_id=None, roles=None) -> PermissionContext
#   the UI-surfaces handler builds owner_pctx exactly so: build_principal_context(user_id, channel="ui_surfaces") (ui_surfaces.py:570)

# packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py:47-62
class PhysicalResources(BaseModel): driver=None; tables: set[str]; source_type: str | None; source_id: str | None
# LinkedSurfaceService builds: PhysicalResources(source_type="query_slug", source_id=f"{tenant or 'public'}:{slug}") (service.py:98-102)

# navigator_auth (.venv) — resources.py:97-110: "source:query_slug:public:epson_*" → type "source" (raw-string
#   fallback, no ResourceType.SOURCE), pattern "query_slug:public:epson_*"; resources.py:158-160: groups ["*"] matches
#   any user, even one with no groups (build_principal_context sets none).

# QuerySource MultiQS (.venv querysource/queries/multi) — frame naming facts that bound the pipeline:
#   queries[*] results are keyed by their query name; Join rule {left, right} pops both and stores the join as
#   f"{left}.{right}" (operators/Join.py:84-97); a single remaining frame is unwrapped to one DataFrame unless
#   return_all (multi/__init__.py:802-804). So a Join output can NEVER be named "result".
```

### Environment facts (verified, key names only — never print values)
- navconfig picks the env dir from `os.environ["ENV"]` (`navconfig/project.py:10-12` `get_environment()`), then
  **overwrites** `navconfig.ENV` with the `ENV` key inside the loaded `.env` (`navconfig/__init__.py:93`).
  `env/staging/.env` contains `ENV=production`, so `navconfig.ENV` reads `"production"` even on staging.
  **`assert_staging()` must therefore test `os.environ.get("ENV") == "staging"`, not `navconfig.ENV`.**
- `DBNAME` is defined in both `env/.env` and `env/staging/.env`; only the staging value contains `staging`
  (verified by a boolean grep). querysource reads it as `config.get('DBNAME', fallback='navigator')` (querysource/conf.py:27).
- `ENV_TYPE` defaults to `"vault"` (`navconfig/project.py:15-17`); set `ENV_TYPE=file` if the vault is not reachable.

### Does NOT Exist
- ~~`examples/agents/a2ui/linked_e2e/`~~ — nothing there yet (this task creates it); ~~`examples/agents/a2ui/__init__.py`~~.
- ~~A `query_slug` / `source:read` policy in repo-root `policies/`~~ — only `slug:*` / `slug:execute` (policies/slugs.yaml).
- ~~`ResourceType.SOURCE` in navigator_auth~~ — `source` is a raw-string fallback type.
- ~~`QuerysourceToolkit.open()` / `.close()` public methods~~ — only `_open()` / `_close()`; `open`/`close` are excluded tools.
- ~~`save_multiquery(slug=..., pipeline=..., overwrite=True)` without `description`~~ — `description` is a required positional.
- ~~`navconfig.ENV == "staging"` on staging~~ — it is `"production"` (see above).
- ~~A dry-run mode on `save_multiquery`~~ — use `validate_pipeline` + `run_multiquery(pipeline=...)` (no Output step) to preview.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "examples/agents/a2ui/linked_e2e/seed_staging.py", "action": "CREATE"},
    {"path": "examples/agents/a2ui/linked_e2e/policies/source-epson.yaml", "action": "CREATE"},
    {"path": "sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_seed_staging_guard.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.describe_slug",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.validate_pipeline",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.run_multiquery",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit.save_multiquery",
    "sym:packages/ai-parrot/src/parrot/auth/pbac.py#setup_dataplane_guard",
    "sym:packages/ai-parrot/src/parrot/auth/dataplane_guard.py#DataPlanePolicyGuard.authorize_source",
    "sym:packages/ai-parrot/src/parrot/auth/permission.py#build_principal_context",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/resolver.py#PhysicalResources"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Staging only.** Every entry point calls `assert_staging()` first, including read-only describe.
- **Human confirmation before any staging write.** `seed_multiquery` is a write; the CLI prompts
  (`input()`), and an agent must not pass `--yes` without the human's explicit go-ahead in chat.
- Idempotent: `overwrite=True`, same `program`, same pipeline → second run reports `action="updated"`.
- Never print secrets (DSNs, passwords, tokens). Log slug names, column names, placeholder names only.
- Async throughout; `logging.getLogger("FEAT611.seed")`; always `await tk._close()` in `finally`.

### References in Codebase
- `packages/ai-parrot-tools/tests/querysource/conftest.py:6-10` — a `queries` + `Join` pipeline shape.
- `packages/ai-parrot/src/parrot/outputs/a2ui/linked/contract/fixtures/envelopes/linked_multiquery_public.json` —
  the linked MQ descriptor (`is_multiquery: true`, `multi_output: "result"`).
- `policies/slugs.yaml` — YAML policy layout (`version`, `policies[]`, `subjects.groups: ["*"]`).
- `sdd/state/FEAT-611/findings/F001-candidate-query-slugs.md` — findings frontmatter format.

---

## Implementation Blueprint

### Steps (in order)
1. Create `policies/source-epson.yaml` and `seed_staging.py` from the blocks below — *why*: the script and the
   policy are the reviewable artefacts; nothing runs yet.
2. Create the guard test and make it pass locally (no staging needed) — *why*: proves the refusal path before any
   real run.
3. Run `ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py describe` — *why*: read-only; it confirms
   (or corrects) the inferred columns/placeholders the rest of FEAT-611 depends on. Stop and report if a slug is
   missing or its columns differ from spec §2 "Dataset".
4. Run `... preview` — *why*: `validate_pipeline` + `run_multiquery(pipeline=...)` are read-only and show the real
   frame keys before anything is saved.
5. Run `... prove-policy` — *why*: §7/§9 S5, the resource string is inferred and must be proven allow/deny.
6. **Ask the human in chat for confirmation**, then run `... seed` (it prompts again) — *why*: the only write.
   Run it twice to prove idempotency (`updated` the second time).
7. Write F020 from the logged output — *why*: TASK for M8/M9 read the real definitions and date ranges from it.

### `examples/agents/a2ui/linked_e2e/policies/source-epson.yaml` (CREATE)
```yaml
# FEAT-611 M2 demo policy — EXAMPLE-LOCAL, loaded only via setup_dataplane_guard(policy_dir=<this dir>).
# Never copy into the repo-root policies/. Resource type "source" is a raw-string fallback in navigator_auth
# (no ResourceType.SOURCE); the guard evaluates ("source", "query_slug:<tenant>:<slug>", "source:read").
version: "1.0"
policies:
  - name: demo_allow_epson_linked_sources
    effect: allow
    description: >
      FEAT-611 demo — any authenticated user may read the public epson_* query slugs through
      the linked-surface data-plane guard. Staging example only.
    resources: ["source:query_slug:public:epson_*"]
    actions: ["source:read"]
    subjects: { groups: ["*"] }
    priority: 10
```

### `examples/agents/a2ui/linked_e2e/seed_staging.py` (CREATE) — part 1: guard + describe
```python
"""FEAT-611 M2 — staging-only verification and idempotent seed for the linked-surface E2E.

Usage (from the repo root, staging only):
    ENV=staging python examples/agents/a2ui/linked_e2e/seed_staging.py describe|preview|prove-policy|seed [--yes]

Refuses to run unless ENV=staging (the navconfig selector) AND the configured DBNAME contains 'staging'.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("FEAT611.seed")

HERE = Path(__file__).resolve().parent
POLICY_DIR = HERE / "policies"
MQ_SLUG = "epson_activity_vs_targets_mq"
ACTIVITY_SLUG = "epson_field_activity"
TARGETS_SLUG = "epson_program_targets"
MQ_DESCRIPTION = "FEAT-611 E2E: Epson field activity vs program targets (frames: result, targets)"


def _current_dbname() -> str:
    """Return the DBNAME navconfig resolved (value is never logged). Tests monkeypatch this."""
    from navconfig import config  # imported lazily: bootstraps navconfig from os.environ["ENV"]

    return str(config.get("DBNAME", fallback="") or "")


def assert_staging() -> None:
    """Raise SystemExit unless ENV=staging and the configured DBNAME contains 'staging'."""
    # Check the SELECTOR, not navconfig.ENV: env/staging/.env sets ENV=production internally, so
    # navconfig.ENV reads "production" on staging (navconfig/__init__.py:93).
    selected = os.environ.get("ENV", "")
    if selected != "staging":
        raise SystemExit(f"refusing to run: ENV={selected!r}, expected 'staging'")
    if "staging" not in _current_dbname().lower():
        raise SystemExit("refusing to run: configured DBNAME does not contain 'staging'")
    logger.info("staging target confirmed (ENV=staging, DBNAME contains 'staging')")


async def describe_slugs(slugs: list[str]) -> dict[str, dict]:
    """Read-only qs_describe_slug for each slug; returns {slug: SlugDetail.model_dump()}."""
    assert_staging()
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    tk = QuerysourceToolkit(include_sql=True)  # allow_write=False: describe is a catalog read
    out: dict[str, dict] = {}
    try:
        for slug in slugs:
            detail = await tk.describe_slug(slug)
            out[slug] = detail.model_dump()
            logger.info(
                "describe %s: program=%s multiquery=%s placeholders=%s fields=%s",
                slug, detail.program_slug, detail.is_multiquery, detail.placeholders, detail.fields,
            )
    finally:
        await tk._close()
    return out
```

### `seed_staging.py` — part 2: pipeline, preview, seed
```python
def build_pipeline() -> dict[str, Any]:
    """The MQ_SLUG pipeline: activity and targets joined on program, with output frames 'result' and 'targets'."""
    # FILL IN: the exact pipeline — bounded by (a) validate_pipeline(...).valid is True, (b) the preview's
    # frame keys are exactly {"result", "targets"} (spec §3 M2 / S3 needs multi_output="targets", the 'result'
    # fallback, and an ambiguous case), and (c) the MultiQS naming facts in the Codebase Contract: a Join
    # stores its output as "<left>.<right>" (Join.py:97), so a Join output cannot be called "result".
    # Starting candidate (no Join; frames keyed by query name; the activity⋈targets join then lives in the
    # linked descriptor's transform.ops — M8):
    #     {"queries": {"result": {"slug": ACTIVITY_SLUG}, "targets": {"slug": TARGETS_SLUG}}}
    # If a server-side Join is required, keep it and record the real frame names in F020 as a spec deviation.
    raise NotImplementedError


async def preview_multiquery(conditions: dict[str, Any]) -> dict[str, Any]:
    """Read-only: validate the pipeline and run it inline (no Output step); log frame keys and row counts."""
    assert_staging()
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    tk = QuerysourceToolkit(include_sql=True)
    try:
        pipeline = build_pipeline()
        validation = await tk.validate_pipeline(pipeline)
        logger.info("validate_pipeline valid=%s issues=%s", validation.valid, validation.issues)
        result = await tk.run_multiquery(pipeline=pipeline, conditions=conditions)
        # MultiQueryResult.results: dict[frame_name, ExecutionResult] (models.py:69-74); never return `rows`.
        frames = {
            name: {"columns": r.columns, "total_rows": r.total_rows, "returned_rows": r.returned_rows}
            for name, r in result.results.items()
        }
        logger.info("preview %s: status=%s frames=%s", MQ_SLUG, result.status, sorted(frames))
        # FILL IN: fail loudly (SystemExit) when sorted(frames) != ["result", "targets"] — bounded by spec §3 M2
        # (two output frames `result` and `targets`); if the chosen pipeline deliberately differs, record why in F020.
        return {"valid": validation.valid, "status": result.status, "frames": frames}
    finally:
        await tk._close()


async def seed_multiquery(*, overwrite: bool = True) -> dict:
    """Upsert MQ_SLUG via QuerysourceToolkit.save_multiquery (verified: toolkit.py:605); idempotent."""
    assert_staging()
    from parrot_tools.querysource.toolkit import QuerysourceToolkit

    details = await describe_slugs([ACTIVITY_SLUG])
    program = details[ACTIVITY_SLUG]["program_slug"]  # save needs an explicit program (catalog.py:148-150)
    tk = QuerysourceToolkit(programs=[program], allow_write=True)
    try:
        saved = await tk.save_multiquery(MQ_SLUG, build_pipeline(), MQ_DESCRIPTION, program=program, overwrite=overwrite)
        logger.info("seed %s: action=%s program=%s", saved.slug, saved.action, saved.program_slug)
        return saved.model_dump()
    finally:
        await tk._close()
```

### `seed_staging.py` — part 3: policy proof + CLI
```python
async def prove_policy(user: str = "feat611-e2e") -> dict[str, str]:
    """Prove demo_allow_epson_linked_sources: allow with POLICY_DIR, deny without it; logs evaluated strings."""
    assert_staging()
    from aiohttp import web
    from parrot.auth.exceptions import AuthorizationRequired
    from parrot.auth.pbac import setup_dataplane_guard
    from parrot.auth.permission import build_principal_context
    from parrot.tools.dataset_manager.sources.resolver import PhysicalResources

    resources = PhysicalResources(source_type="query_slug", source_id=f"public:{ACTIVITY_SLUG}")
    resource_name, action = f"{resources.source_type}:{resources.source_id}", "source:read"
    pctx = build_principal_context(user, channel="ui_surfaces")  # same shape as the handler's owner_pctx
    outcome: dict[str, str] = {}
    for label, policy_dir in (("with_policy", POLICY_DIR), ("without_policy", None)):
        # FILL IN: for "without_policy" pick a policy dir that PBAC loads but that has no source rule (e.g. a
        # tempfile.TemporaryDirectory holding one unrelated allow policy) — bounded by: setup_dataplane_guard must
        # return a guard (not None), otherwise the run proves "guard missing", not "policy absent" (§9 S5).
        guard = setup_dataplane_guard(web.Application(), policy_dir=str(policy_dir))
        if guard is None:
            outcome[label] = "guard-missing"
            logger.error("%s: guard missing (PBAC did not initialise) resource=source/%s action=%s", label, resource_name, action)
            continue
        try:
            await guard.authorize_source(pctx, resources)
            outcome[label] = "allow"
        except AuthorizationRequired:
            outcome[label] = "deny"
        logger.info("%s: %s resource_type=source resource=%s action=%s", label, outcome[label], resource_name, action)
    if outcome != {"with_policy": "allow", "without_policy": "deny"}:
        raise SystemExit(f"policy proof failed: {outcome}")
    return outcome


def _confirm(prompt: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    if input(f"{prompt} [type 'yes' to continue]: ").strip().lower() != "yes":
        raise SystemExit("aborted by operator")


def main(argv: list[str] | None = None) -> int:
    """CLI: describe | preview | prove-policy | seed. Only `seed` writes (after confirmation)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["describe", "preview", "prove-policy", "seed"])
    parser.add_argument("--yes", action="store_true", help="skip the interactive write confirmation")
    parser.add_argument("--firstdate", default="FDOM")
    parser.add_argument("--lastdate", default="TODAY")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    assert_staging()
    if args.command == "describe":
        result: Any = asyncio.run(describe_slugs([ACTIVITY_SLUG, TARGETS_SLUG]))
    elif args.command == "preview":
        result = asyncio.run(preview_multiquery({"firstdate": args.firstdate, "lastdate": args.lastdate}))
    elif args.command == "prove-policy":
        result = asyncio.run(prove_policy())
    else:
        _confirm(f"WRITE {MQ_SLUG} to the STAGING query catalog?", args.yes)
        result = asyncio.run(seed_multiquery(overwrite=True))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
**Why this shape**: the spec skeleton fixes `MQ_SLUG`, `assert_staging() -> None`, `describe_slugs(slugs) -> dict`
and `seed_multiquery(*, overwrite=True) -> dict`; `preview_multiquery` and `prove_policy` are additions the spec's
Responsibility items 2–3 need. Every heavy import is local so the guard test loads the file cheaply. The loop
over two guards (not one guard with a toggled policy) keeps "allow" and "deny" as independent observations.

### `packages/ai-parrot/tests/outputs/a2ui/linked/test_seed_staging_guard.py` (CREATE)
```python
"""FEAT-611 M2: seed_staging.assert_staging refuses anything that is not the staging DB (spec AC7)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SEED_PATH = Path(__file__).resolve().parents[6] / "examples/agents/a2ui/linked_e2e/seed_staging.py"


@pytest.fixture
def seed(monkeypatch):
    spec = importlib.util.spec_from_file_location("feat611_seed_staging_under_test", SEED_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_refuses_when_env_is_not_staging(seed, monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(seed, "_current_dbname", lambda: "navigator_staging")
    with pytest.raises(SystemExit):
        seed.assert_staging()


def test_refuses_when_dbname_is_not_staging(seed, monkeypatch):
    # FILL IN: ENV=staging + DBNAME "navigator" → SystemExit; bounded by AC7 (no production writes).
    ...


def test_accepts_staging(seed, monkeypatch):
    # FILL IN: ENV=staging + DBNAME containing "staging" → returns None, no exception.
    ...


def test_seed_refuses_before_any_toolkit_import(seed, monkeypatch):
    # FILL IN: ENV=production → asyncio.run(seed.seed_multiquery()) raises SystemExit and never constructs a
    # QuerysourceToolkit (monkeypatch sys.modules["parrot_tools.querysource.toolkit"] with a sentinel that
    # fails the test if touched) — bounded by AC7.
    ...
```
**Why**: `_current_dbname` is the single seam that touches navconfig, so the tests never load a real `.env`.

### `sdd/state/FEAT-611/findings/F020-staging-slug-definitions.md` (CREATE — from the real run)
```markdown
---
id: F020
query_id: M2
type: live-read
intent: real staging definitions of the Epson slugs, MQ seed and PBAC proof
executed_at: <ISO-8601 of the run>
parent_id: F001
depth: 1
---
# F020 — Staging slug definitions (querysource <installed_version()>)

## Summary
<!-- FILL IN from the describe/preview/prove-policy/seed output — bounded by: no secrets, no row values. -->
## epson_field_activity — program, placeholders (name/type/default/required), fields, SQL (redact literals)
## epson_program_targets — same
## Date ranges known to have data (for S2; §7 DataNotFound gotcha)
## epson_activity_vs_targets_mq — final pipeline, frame keys, action (inserted/updated ×2)
## PBAC proof — evaluated resource type/name/action, with_policy / without_policy outcome
## Deviations from spec §2 Dataset (columns, frame names)
```

### FILL IN checklist
- [ ] `seed_staging.py::build_pipeline` — exact pipeline; bounded by `validate_pipeline().valid`, frame keys `{result, targets}`, Join naming (Join.py:97).
- [ ] `seed_staging.py::preview_multiquery` — exit when frame keys ≠ `{result, targets}`; bounded by spec §3 M2.
- [ ] `seed_staging.py::prove_policy` — the "without" policy dir; bounded by guard ≠ None (§9 S5).
- [ ] `test_seed_staging_guard.py` — three remaining tests; bounded by AC7.
- [ ] `F020-…md` — every section from the real run; bounded by "no secrets".

---

## Acceptance Criteria

- [ ] `assert_staging()` raises `SystemExit` unless `os.environ["ENV"] == "staging"` and DBNAME contains `staging`; the guard tests pass.
- [ ] `describe` recorded the real SQL/columns/placeholders of both Epson slugs in F020 (or reported a mismatch).
- [ ] `epson_activity_vs_targets_mq` exists in **staging**, seeded through `save_multiquery(..., overwrite=True)`;
      a second run reports `action="updated"`; its frame keys are recorded in F020.
- [ ] `prove-policy` shows `with_policy=allow`, `without_policy=deny`, both with a real guard, and logs the
      evaluated `source` / `query_slug:public:epson_field_activity` / `source:read` strings.
- [ ] The demo policy exists only under `examples/agents/a2ui/linked_e2e/policies/`. Nothing was written to production.
- [ ] `ruff check examples/agents/a2ui/linked_e2e/seed_staging.py packages/ai-parrot/tests/outputs/a2ui/linked/test_seed_staging_guard.py` is clean.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_seed_staging_guard.py -q`

---

## Test Specification

See the `test_seed_staging_guard.py` CREATE block. The live steps (describe / preview / prove-policy / seed)
are verified by F020, not by pytest — they need staging credentials (spec §4: staging is never a merge gate).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug a2ui-linked-e2e-parallel --feature-id FEAT-611`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — TASK-3831 must be `"done"` in `sdd/tasks/index/a2ui-linked-e2e-parallel.json`
   and `installed_version()` must report ≥ 5.1.2
4. **Verify the Codebase Contract** — before writing ANY code, re-read the signatures above
5. **Update status** in the index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker
7. **SAFETY — non-negotiable**:
   - **Never run any command of this script against production.** Always export `ENV=staging` explicitly;
     never rely on a default env.
   - `describe`, `preview` and `prove-policy` are read-only and may run once `assert_staging()` passes.
   - **`seed` writes to the staging query catalog. STOP and ask the human for explicit confirmation in chat
     before running it**, and never pass `--yes` without that confirmation. If staging credentials are not
     available, do not seed: finish the code and tests, mark the live steps as blocked in the Completion Note,
     and leave F020 with the sections still to be filled (§8 Q1 is owned by Javier).
   - Never print or commit DSNs, passwords, tokens, or row values.
8. **Verify** all acceptance criteria are met — run the Validation Commands
9. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
10. **Close the task** with `scripts/sdd/close_task.sh TASK-3832 a2ui-linked-e2e-parallel verified`
11. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
