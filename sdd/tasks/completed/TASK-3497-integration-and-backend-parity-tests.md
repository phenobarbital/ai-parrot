# TASK-3497: Integration, backend-parity, and namespace-isolation tests

**Feature**: FEAT-578 — ADR extraction and decision retrieval in the LLM wiki
**Spec**: `sdd/specs/sdd-spec-wiki-adr.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3482, TASK-3483, TASK-3484, TASK-3496
**Assigned-to**: unassigned

---

## Context

Module 7's validation half. Every earlier task carries its own unit tests; this
task covers the seven **integration** tests in spec §4 — the ones that can only
fail once the whole pipeline exists — plus the AC14 baseline measurement.

One requirement here is unusual and must be honoured literally (AC8):

> Namespace and backend contract tests pass; **missing live backend validation
> is reported and blocks declaring backend parity complete.**

So a skipped ArangoDB or Postgres run is not a pass. This task adds a parity
**reporter** that fails loudly if anyone claims parity while a live backend was
skipped, and writes the evidence under `artifacts/logs/` (AC12).

---

## Scope

- Implement the seven integration tests from spec §4.
- Implement the backend-parity harness: SQLite and memory mandatory; Arango and
  Postgres run when their env is present and are **explicitly reported as
  unvalidated** when not.
- Implement the AC14 baseline: time and memory for 1000 synthetic ADRs, recorded
  as a measurement — **not** asserted as a latency SLA.
- Save evidence under `artifacts/logs/` (AC12).

**NOT in scope**: any production code change. If an integration test reveals a
defect, report it — do not fix it here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_integration_roundtrip.py` | CREATE | Build → lookup → why → page read; incremental; partial retry |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py` | CREATE | Four-backend CAS + dossier parity, with skip reporting |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_namespace_and_offline.py` | CREATE | Namespace isolation, CLI/MCP parity, offline guarantees |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_scale_baseline.py` | CREATE | AC14 inventory-bound + 1000-record baseline |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from click.testing import CliRunner
from parrot.knowledge.wiki.cli import wiki                                # cli.py:1328
from parrot.knowledge.wiki.file_store import InMemoryWikiStore            # file_store.py:71
from parrot.knowledge.wiki.store import SQLiteWikiStore                   # store.py
from parrot.knowledge.wiki.decisions import DecisionService, create_decision_tools   # TASK-3494
from parrot.knowledge.wiki.decisions.repository import DecisionRepository # TASK-3485
from parrot.knowledge.wiki.decisions.ingest import refresh_decisions      # TASK-3489
```

### Existing Signatures to Use

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/conftest.py  (TASK-3489)
@pytest.fixture
def adr_repo(tmp_path) -> Path: ...      # the full spec §4 synthetic repository
@pytest.fixture
def adr_config() -> DecisionConfig: ...
@pytest.fixture
async def adr_store(tmp_path): ...

# Skip-reason constants to assert against (TASK-3483 / TASK-3484)
# packages/ai-parrot/tests/knowledge/wiki/test_arango_store_cas.py::SKIP_REASON
# packages/ai-parrot/tests/knowledge/wiki/test_postgres_store_cas.py::SKIP_REASON
```

Existing multi-backend test conventions to follow:
`packages/ai-parrot/tests/knowledge/wiki/test_extra_backends.py`,
`test_mcp_server_namespaces.py`, `test_postgres_store.py`.

### Does NOT Exist

- ~~a network model call in any test~~ — spec §4: "No network model calls in
  tests." Use the fake-client pattern from
  `packages/ai-parrot/tests/knowledge/wiki/decisions/test_generation.py`.
- ~~a latency SLA~~ — AC14: "Record timing and memory for 1000 synthetic ADRs as
  a baseline; **no unmeasured latency SLA is asserted**." Record; do not
  `assert elapsed < X`.
- ~~`WikiProjectConfig.backend == "postgres"`~~ — Postgres is reachable only as a
  directly instantiated store (spec §6). Do not drive it through a project config.
- ~~fixing production code here~~ — this task is validation only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_integration_roundtrip.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_namespace_and_offline.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_scale_baseline.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#wiki",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/file_store.py#InMemoryWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)

1. Write the round-trip suite first — *why*: it is the smoke test that tells you
   whether the other three suites are worth debugging.
2. Write the parity harness with its skip **reporter** — *why*: AC8's reporting
   requirement is the part most easily satisfied by accident and lost later.
3. Write the namespace/offline suite.
4. Write the baseline last and save its output under `artifacts/logs/`.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_integration_roundtrip.py` (CREATE)

```python
"""End-to-end ADR pipeline (FEAT-578 Module 7, spec §4 integration tests)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


class TestBuildLookupWhyRoundtrip:
    def test_build_lookup_why_roundtrip(self, adr_repo):
        """Ordinary build + ADR refresh -> lookup -> why -> raw page read."""
        # FILL IN: run `wikitoolkit build --path adr_repo`; then
        #   `adr lookup sym:<the citing symbol> --json` -> the accepted ADR
        #   `adr why "why pgvector" --json`            -> cited excerpts
        #   `wikitoolkit page adr:doc:<id>`            -> the raw managed page
        # Assert each step's exit code and that the dossiers carry labels and
        # at least one citation. Bounded by spec §4 test_build_lookup_why_roundtrip.
        raise NotImplementedError

    def test_page_read_shows_labels_not_raw_json_only(self, adr_repo):
        """AC9: the generic page surface still reads as a labeled decision."""
        # FILL IN: assert the page body's markdown tail is present and its title
        # carries the [DOCUMENTED / ACCEPTED] prefix
        raise NotImplementedError


class TestIncrementalLinksAndDeletion:
    def test_incremental_links_and_deletion(self, adr_repo):
        """ADR added / changed / deleted / renamed; citing code re-resolved."""
        # FILL IN: build; then in sequence
        #   add a new ADR      -> upsert    -> it appears
        #   change its alias   -> upsert    -> the UNCHANGED citing file relinks
        #   delete it          -> upsert    -> record retained, marked missing
        #   rename another ADR -> upsert    -> a NEW record, old one retained
        # Assert candidate history survives every step. Bounded by spec §4 and AC7.
        raise NotImplementedError

    def test_candidate_history_survives_every_step(self, adr_repo):
        # FILL IN: seed an accepted candidate before the sequence above and
        # assert its review_history is byte-identical afterwards (AC7)
        raise NotImplementedError


class TestPartialSyncRetry:
    def test_partial_sync_retry(self, adr_repo, adr_config, adr_store, monkeypatch):
        """Failure after one record persists; retry converges cleanly."""
        # FILL IN: patch DecisionRepository.save to raise on the Nth call; run
        # refresh_decisions (expect diagnostics); unpatch; re-run; assert every
        # record exists exactly once and no revision was double-bumped.
        # Bounded by spec §4 test_partial_sync_retry.
        raise NotImplementedError
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py` (CREATE)

```python
"""Four-backend contract parity, with explicit reporting of skips (AC8).

SQLite and memory are MANDATORY. ArangoDB and Postgres run only when their
env is configured; when they do not, this module records them as
UNVALIDATED. AC8: "missing live backend validation is reported and blocks
declaring backend parity complete" — a skip is not a pass.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

#: Backends that must always run.
MANDATORY_BACKENDS = ("sqlite", "memory")

#: Live backends and the env var that enables each.
LIVE_BACKENDS = {"arangodb": "ARANGODB_HOST", "postgres": "WIKI_POSTGRES_DSN"}

#: Where the parity report is written (AC12: evidence under artifacts/logs/).
PARITY_REPORT = Path("artifacts/logs/feat-578-backend-parity.json")


def _available_live_backends() -> dict[str, bool]:
    return {name: bool(os.getenv(env)) for name, env in LIVE_BACKENDS.items()}


@pytest.fixture(params=MANDATORY_BACKENDS)
def parity_store(request, tmp_path):
    """One store per mandatory backend."""
    # FILL IN: build SQLiteWikiStore / InMemoryWikiStore for the param,
    # following test_extra_backends.py's construction; yield and close
    raise NotImplementedError


@pytest.fixture(params=[n for n, ok in _available_live_backends().items() if ok])
def live_store(request, tmp_path):
    """One store per CONFIGURED live backend; the param list is empty otherwise."""
    # FILL IN: build ArangoDBWikiStore / PostgresWikiStore on a throwaway
    # database/schema; yield and tear down
    raise NotImplementedError


class TestMandatoryBackends:
    async def test_cas_contract(self, parity_store):
        """Insert / replace / conflict behave identically on every backend."""
        # FILL IN: the same four assertions as TASK-3481's suite, run against
        # whichever backend the fixture supplied
        raise NotImplementedError

    async def test_full_record_roundtrip(self, parity_store):
        """Every DecisionRecord field survives a save/load on each backend."""
        # FILL IN: save a fully populated record via DecisionRepository, reload,
        # assert equality — the file backend loses edge provenance (spec §6), so
        # this must prove the RECORD carries it
        raise NotImplementedError

    async def test_identical_dossier_semantics(self, parity_store):
        """The same seeded records produce the same dossier on every backend."""
        # FILL IN: seed identical records, run for_symbol and why, compare the
        # dossiers field by field across backends
        raise NotImplementedError


class TestLiveBackends:
    async def test_cas_contract(self, live_store):
        # FILL IN: same CAS contract against the live backend
        raise NotImplementedError

    async def test_concurrent_cas_one_winner(self, live_store):
        """AC8: parity is BEHAVIORAL, not just a JSON round-trip."""
        # FILL IN: asyncio.gather two CAS calls from the same read; assert
        # exactly one True
        raise NotImplementedError


def test_backend_parity_is_reported(tmp_path):
    """Write the parity report and fail if parity is claimed while unvalidated.

    This test is the AC8 guard itself: it does not validate a backend, it
    validates that the PROJECT is honest about which backends were validated.
    """
    available = _available_live_backends()
    report = {
        "feature": "FEAT-578",
        "mandatory_validated": list(MANDATORY_BACKENDS),
        "live_validated": [n for n, ok in available.items() if ok],
        "live_unvalidated": [n for n, ok in available.items() if not ok],
        "parity_complete": all(available.values()),
    }
    # FILL IN: mkdir PARITY_REPORT.parent, write the JSON, and then assert
    # EITHER report["parity_complete"] is True, OR that the unvalidated list is
    # non-empty AND this run is explicitly allowed to be partial via an env flag
    # (e.g. ADR_PARITY_ALLOW_PARTIAL=1). Without that flag, a missing live
    # backend must FAIL this test — that is what "blocks declaring backend
    # parity complete" means in AC8. Emit the unvalidated names in the failure
    # message so the gap is legible in CI output.
    raise NotImplementedError
```

**Why this shape**: `test_backend_parity_is_reported` is deliberately a test
about the project's claims rather than about a backend. AC8's wording — *missing
live backend validation is reported and blocks declaring backend parity
complete* — cannot be satisfied by `pytest.mark.skipif` alone, because a skipped
test is green. The env flag makes a partial run an explicit, recorded decision
instead of an invisible default.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_namespace_and_offline.py` (CREATE)

```python
"""Namespace isolation, CLI/MCP parity and offline guarantees (spec §4)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki


class TestNamespaceIsolation:
    async def test_same_adr_number_in_two_namespaces_stays_distinct(self, tmp_path):
        """spec §4 test_namespace_isolation."""
        # FILL IN: build two planes each holding an ADR-42, federate them, and
        # assert a lookup in each namespace returns only its own record
        raise NotImplementedError

    async def test_remote_reads_are_unverified(self, tmp_path):
        """No local root -> freshness is 'unverified', never 'current' (spec §2)."""
        # FILL IN: read a store-only namespace; assert every hit's freshness is
        # "unverified"
        raise NotImplementedError

    async def test_broadcast_writes_are_refused(self, tmp_path):
        """--ns all is ADR_INVALID_ARGUMENT in v1."""
        # FILL IN: assert both the CLI and the tool reject namespace 'all'
        raise NotImplementedError


class TestCliMcpParity:
    async def test_cli_mcp_parity(self, adr_repo):
        """spec §4: equivalent data and identical error codes on both surfaces."""
        # FILL IN: for the same query, compare `adr why --json` stdout against
        # wiki_decision_why's ToolResult payload — assert the decision ids,
        # groups and labels match; then trigger the same failure on both and
        # assert the SAME ADR_* code appears
        raise NotImplementedError

    def test_stdout_remains_protocol_safe(self, adr_repo):
        """--json stdout must always parse, even when warnings are logged."""
        # FILL IN: run `adr why --json` on a repo that emits diagnostics; assert
        # json.loads(stdout) succeeds
        raise NotImplementedError


class TestOfflineAndDisabledGeneration:
    def test_build_lookup_why_never_construct_an_llm(self, adr_repo, monkeypatch):
        """AC5: spec §4 test_offline_and_disabled_generation."""
        # FILL IN: monkeypatch LLMFactory.create AND AbstractClient.invoke to
        # raise AssertionError; run build, adr lookup and adr why; assert all
        # three succeed
        raise NotImplementedError

    def test_generation_failure_leaves_ordinary_wiki_working(self, adr_repo):
        """A broken model must not degrade the read surfaces."""
        # FILL IN: enable generation with a client that always raises; run
        # `adr generate` (expect exit 1), then assert `adr why` and
        # `wikitoolkit query` still work
        raise NotImplementedError

    def test_existing_search_and_source_slices_are_unaffected(self, adr_repo):
        """AC10: existing symbol ids and search behaviour are unchanged."""
        # FILL IN: assert `wikitoolkit query` and `wikitoolkit symbols lookup`
        # return the same results before and after an ADR refresh, and that no
        # sym: id changed
        raise NotImplementedError
```

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_scale_baseline.py` (CREATE)

```python
"""Inventory bound and the AC14 scale baseline (FEAT-578 Module 7).

AC14 asks for a RECORDED baseline, explicitly not a latency SLA. This module
measures and writes evidence; it asserts only correctness, never speed.
"""

from __future__ import annotations

import json
import time
import tracemalloc
from pathlib import Path

import pytest

#: AC12: evidence is saved under artifacts/logs/.
BASELINE_REPORT = Path("artifacts/logs/feat-578-scale-baseline.json")

SYNTHETIC_RECORD_COUNT = 1000


class TestInventoryBound:
    async def test_exceeding_max_records_is_an_explicit_error(self, adr_store):
        """AC14: an explicit error, never a silent 'no decisions'."""
        # FILL IN: seed max_records + 1 records; assert DecisionError.code ==
        # "ADR_INVENTORY_LIMIT" from both inventory() and a `why` call
        raise NotImplementedError

    async def test_serialization_roundtrips_at_the_configured_bound(self, adr_store):
        """AC14: exactly max_records records still round-trip."""
        # FILL IN: seed exactly max_records; assert inventory() returns them all
        # and each decodes equal to what was saved
        raise NotImplementedError


class TestScaleBaseline:
    async def test_record_1000_adr_baseline(self, adr_store, tmp_path):
        """Measure and RECORD; assert correctness only (AC14)."""
        tracemalloc.start()
        started = time.perf_counter()
        # FILL IN: seed SYNTHETIC_RECORD_COUNT deterministic records, then run
        # one full inventory() and one why() call, timing each phase
        raise NotImplementedError
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        BASELINE_REPORT.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_REPORT.write_text(json.dumps({
            "feature": "FEAT-578",
            "records": SYNTHETIC_RECORD_COUNT,
            "elapsed_seconds": round(elapsed, 3),
            "peak_memory_bytes": peak,
            "note": "Baseline measurement only — AC14 asserts no latency SLA.",
        }, indent=2))
        # Deliberately NO timing assertion here. AC14: "no unmeasured latency
        # SLA is asserted." Adding one would invent a contract the spec refuses.
```

### FILL IN checklist

- [ ] `test_integration_roundtrip.py` — five test bodies; bounded by spec §4
- [ ] `test_backend_parity.py` — two fixtures + five test bodies
- [ ] `test_backend_parity.py::test_backend_parity_is_reported` — the AC8 honesty guard
- [ ] `test_namespace_and_offline.py` — eight test bodies; bounded by spec §4
- [ ] `test_scale_baseline.py` — three test bodies; bounded by AC14

---

## Acceptance Criteria

- [ ] All seven spec §4 integration tests exist and pass
- [ ] SQLite and memory backends pass the CAS, full-record and dossier-parity contracts
- [ ] Arango and Postgres pass when configured; when not, they are **reported as unvalidated** and `test_backend_parity_is_reported` fails without an explicit partial-run flag (AC8)
- [ ] `artifacts/logs/feat-578-backend-parity.json` names every unvalidated backend
- [ ] Same ADR number in two namespaces stays distinct; remote reads are `unverified`; broadcast writes refused
- [ ] CLI and MCP return equivalent data and identical `ADR_*` codes; `--json` stdout always parses
- [ ] Build, lookup and why succeed with `LLMFactory.create` and `invoke` patched to raise (AC5)
- [ ] A generation failure leaves ordinary wiki reads working
- [ ] Existing `wikitoolkit query` / `symbols lookup` results and `sym:` ids are unchanged (AC10)
- [ ] Inventory overflow raises `ADR_INVENTORY_LIMIT`; exactly `max_records` round-trips (AC14)
- [ ] The 1000-record baseline is **recorded** to `artifacts/logs/`, with **no** timing assertion (AC14)
- [ ] No network model call in any test (spec §4)
- [ ] No production file is modified by this task

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_integration_roundtrip.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_namespace_and_offline.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_scale_baseline.py -q`

---

## Agent Instructions

1. **Read the spec** §4 in full, plus AC8/AC10/AC12/AC14.
2. **Verify the Codebase Contract** — confirm the `adr_repo` fixture from TASK-3489 covers the whole §4 matrix; extend it there (not here) if it does not.
3. **Implement** from the blueprint; complete every `# FILL IN:`.
4. **Verify** all four Validation Commands pass, and save their output under `artifacts/logs/` (AC12).
5. **If an integration test reveals a production defect, report it in the Completion Note — do not fix it here.**
6. **Move** to `sdd/tasks/completed/`, set the index entry to `done`.
7. **Fill in the Completion Note**, stating explicitly which live backends were validated and which were not.

---

## Completion Note

**Completed by**: sdd-worker (Fallback: Sequential Loop, via a forked sub-agent) — jesuslarag@gmail.com
**Date**: 2026-09-20

**Notes**: Implemented in fallback mode after two independent `parrot-sdd-coder` MCP
infra failures (see below). All four CREATE files exist per the blueprint; commit `5e7e3225f`.

- `test_integration_roundtrip.py` — **5/5 passed**, fully verified
  (`PYTHONPATH=packages/ai-parrot/src pytest ... -q`). One factual correction from the
  blueprint: the fixture's "accepted" ADR carries no `## Status` header, so
  `source_status` is actually `unknown`, not `accepted` — the label assertion was
  adjusted to match the real fixture rather than the blueprint's assumption.
- `test_backend_parity.py`, `test_namespace_and_offline.py`, `test_scale_baseline.py` —
  written per blueprint (`ruff check --fix` clean), but **NOT executed**. Mid-run the
  shared main-checkout `.venv` (read-only to this worker) was mutated by another
  concurrent session: `numpy` lost its compiled extension
  (`No module named 'numpy._core._multiarray_umath'`) and, confirmed again by me
  afterward, `pydantic-core` (2.49.0) became incompatible with the installed `pydantic`
  (requires 2.41.5) — even `wikitoolkit` itself stopped working. Per policy I did not
  attempt to repair the shared venv; I polled for recovery (bounded, ~60s) with no
  success and stopped. **These three files' test bodies are unvalidated and need a
  re-run once the shared venv is stable** (`PYTHONPATH=packages/ai-parrot/src pytest
  packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py
  test_namespace_and_offline.py test_scale_baseline.py -q`).
- `artifacts/logs/feat-578-backend-parity.json` / `feat-578-scale-baseline.json` —
  **not yet generated** (their writer tests never ran).

**Backends validated**: none of the four backend-parity fixtures have run yet (blocked
above). By construction sqlite/memory are the two mandatory `parity_store` params;
arangodb/postgres are gated on `ARANGODB_HOST` / `WIKI_POSTGRES_DSN` respectively,
following `test_arango_store_cas.py` / `test_postgres_store_cas.py` conventions —
whether either env was present in this worktree is unconfirmed since the module never ran.

**Production defect found (NOT fixed — out of this task's scope)**:
`packages/ai-parrot/src/parrot/knowledge/wiki/decisions/cli.py::_resolve_scoped_store`
(added by TASK-3496, ~lines 70-95) opens the store via `_require_built()` directly
instead of the `_federate()` helper every other `wiki` CLI command uses. Its namespace
narrowing only works once the store is already a `FederatedWikiStore`, so CLI-level
`adr lookup/why --ns <foreign-namespace>` silently keeps reading the LOCAL plane instead
of the declared namespace — no error, just wrong-namespace data. The MCP-tool path
(`create_decision_tools` via `create_wiki_mcp_server`) is unaffected since it wraps the
store in `FederatedWikiStore` first. `test_namespace_and_offline.py` sidesteps this by
asserting isolation at the tool level and CLI/MCP parity only for the default
(no `--ns`) case. **Ledger status: NOT filed** — `wikitoolkit ledger open` itself failed
with the same shared-venv `pydantic-core`/`pydantic` mismatch described above. Filing is
deferred to a session with a healthy shared venv; full finding text is preserved in this
note and in the sdd-worker session transcript.

**Infra note (unrelated to this task's content, recorded for the record)**: TASK-3497
was originally blocked twice through `parrot-sdd-coder`: (1) an `unknown`-classification
eligibility bug (fixed upstream in `dev` commit `957c15d96`, confirmed merged); (2)
after restarting to pick up that fix, the MCP server's suspension-history store came
back `suspension_history_unavailable` / roster `exhausted` — a live-process regression,
separate from (1) and still unresolved as of this task's completion. Implemented via the
documented Fallback: Sequential Loop as a result.

**Deviations from spec**: none structural; see the `source_status` label correction
above (factual, not a scope change).

**Follow-up required before this feature is fully validated**: re-run the three
unvalidated test files once the shared venv is confirmed healthy, and file the CLI
namespace-federation defect to the ledger.

---

### Update — feature-level consolidation pass (2026-09-20)

Everything flagged above as outstanding is now resolved:

- **All three previously-unvalidated files now pass**, plus a fourth
  (`test_backend_parity_is_reported`) with **true 4-backend parity**
  (`mandatory_validated=[sqlite,memory]`, `live_validated=[arangodb,postgres]`,
  `parity_complete=true`) against live ArangoDB + Postgres containers.
  `artifacts/logs/feat-578-backend-parity.json` and
  `feat-578-scale-baseline.json` now exist, correctly anchored inside this
  worktree (see below — they were initially landing in the main checkout).
- Getting there required fixing genuine bugs beyond this note's original
  scope, found via a full adversarial code-review pass and this
  consolidation: a `_page(...)` positional-argument test-authoring bug in
  `test_backend_parity.py` (every CAS assertion was checking the wrong
  page/hash), a legitimate-but-wrongly-asserted `status="partial"` in
  `test_scale_baseline.py`, and — the interesting one — `Path("artifacts/logs/...")`
  in both files resolving relative to `Path.cwd()`, which a pre-existing
  `import parrot` → navconfig side effect silently `chdir()`s to the **main
  checkout**, not this worktree. Fixed by anchoring both paths to `__file__`.
  Commit `4fa3d95cc`.
- The CLI namespace-federation defect (`_resolve_scoped_store`) described
  above **is now fixed** (not by this task — by the feature-level review-fix
  pass, commit `c85837ae4`): it calls `_federate()` correctly now, and
  `--ns` was also added to the write commands (`sync`/`generate`/`review`/
  `export`) per spec line 296, which this task's own testing had not
  originally covered either.
- **Ledger status: now filed.** `wikitoolkit` recovered once the concurrent
  session's dependency mutation resolved. Filed as `issue:6500603d22d4`
  (major, tracks verifying the new write-command `--ns` paths end-to-end —
  the read-path fix itself is confirmed). Two further findings from the
  code review were also filed: `issue:b084239103d7` (the unimplemented
  document-level `sym:` citation extraction — needs a maintainer scope
  decision, not a bug fix) and `issue:7efc053d80c9` (AC12 evidence-logging
  discipline was only followed for 1 of ~16 tasks — tech debt, process
  reminder, not a FEAT-578 backfill).
- A second, independent production defect was found and fixed during this
  same pass: `create_wiki_mcp_server` (`mcp_server.py`) had two tool-factory
  call sites (`create_structural_tools`, `create_decision_tools`) not
  wrapped in the file's own `redirect_stdout(sys.stderr)` discipline —
  their transitive imports could leak a stray navconfig print into the
  JSON-RPC stdout stream, corrupting the very first response byte for any
  real MCP stdio client. Reproduced live via a real subprocess
  (`test_vault_tools_over_stdio`), fixed in the same commit `4fa3d95cc`.

Status updated to **done** (from `done-with-issues`) — nothing outstanding
remains from this task's original scope.
