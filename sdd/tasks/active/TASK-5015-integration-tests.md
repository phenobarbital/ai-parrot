# TASK-5015: Integration tests — e2e, conflict paths, backend & surface parity

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5009, TASK-5010, TASK-5013
**Assigned-to**: unassigned

---

## Context

Spec §4 "Integration Tests" (all five rows) and S11 (backend and transport parity), closing AC1, AC10,
AC12 and AC13 across the whole stack. Unit tests of each module live with their tasks; this task proves
the pieces compose on a real (temporary) git repository with a built wiki plane:

| Test | Spec §4 row |
|---|---|
| `test_end_to_end_preview_and_publish` | spec with two entries → render → check pass → approval entry → publish → next spec's governing dossier lists both |
| `test_conflict_resolution_paths` | declared conflict blocks; prospective supersession of the exact predecessor resolves only that conflict; approved waiver resolves; unapproved does not |
| `test_backend_parity_schema2` | SQLite and memory stores round-trip schema-2 records identically |
| `test_evaluation_parity_backends` | `evaluate()` yields identical `evaluation_digest` on SQLite and memory |
| `test_cli_mcp_json_equivalence` | `wikitoolkit spec consequences check --json`, `wiki_spec_consequences(mode="check")`, `check_spec_consequences.py --json` emit the same `ConsequenceReport` |

---

## Scope

- Create `T/test_decision_audit_integration.py` (T = `packages/ai-parrot/tests/knowledge/wiki/decisions`)
  with the e2e, conflict-path and CLI/MCP/script equivalence tests, plus an AC1 offline guard
  (`LLMFactory.create` monkeypatched to raise) wrapping the e2e run.
- Modify `T/test_backend_parity.py`: insert a `TestSchema2Parity` class (schema-2 round-trip +
  evaluation-digest parity) on the existing `parity_store` fixture (MANDATORY_BACKENDS sqlite + memory).

**NOT in scope**: new production code — if an integration test exposes a defect, fix it only when it is
inside a file this feature created and record it in the Completion Note; otherwise open a ledger issue.
Live Arango/Postgres parity beyond the existing reporting guard (S11 says "configured live backends report
gaps explicitly" — the existing `test_backend_parity_is_reported` already does). CI wiring.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_decision_audit_integration.py` | CREATE | e2e preview/publish, conflict paths, surface equivalence, offline guard |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py` | MODIFY | Add `TestSchema2Parity` (schema-2 round-trip + evaluation parity) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from click.testing import CliRunner                                                    # used by test_namespace_and_offline.py:9
from parrot.knowledge.wiki.cli import wiki                                             # verified: test_namespace_and_offline.py:11
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord      # verified: models.py:63,172
from parrot.knowledge.wiki.decisions.repository import DecisionRepository              # verified: repository.py:26
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store              # verified: test_backend_parity.py:24
from parrot.clients.factory import LLMFactory                                          # verified: test_namespace_and_offline.py:162
# created by earlier tasks of this feature
from parrot.knowledge.wiki.decisions.models import DecisionRef, DecisionTarget          # TASK-4997
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService             # TASK-5005
from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec # TASK-5006
from parrot.knowledge.wiki.decisions.publish import BatchPublisher                      # TASK-5007
from parrot.knowledge.wiki.decisions.operations import SpecConsequencesInput, op_spec_consequences   # TASK-5008
from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service         # TASK-5008
import scripts.sdd.check_spec_consequences as gate                                     # TASK-5010
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py
MANDATORY_BACKENDS = ("sqlite", "memory")                                          # line 27
@pytest.fixture(params=MANDATORY_BACKENDS)
def parity_store(request, tmp_path): ...   # create_wiki_store(..., backend="sqlite"|"memory")   # lines 76-83
class TestMandatoryBackends:                                                       # line 124
    async def test_full_record_roundtrip(self, parity_store)                       # line 134 — pattern to copy
class TestLiveBackends:                                                            # line 168 (count 1) — insert ABOVE it
def test_backend_parity_is_reported(tmp_path)                                      # line 185

# packages/ai-parrot/tests/knowledge/wiki/decisions/test_namespace_and_offline.py
def _build(runner: CliRunner, root) -> None:                                       # line 25
    result = runner.invoke(wiki, ["build", "--path", str(root), "--no-graph", "--quiet"])
def test_build_lookup_why_never_construct_an_llm(self, runner, adr_repo, monkeypatch)  # line 160 — offline guard pattern

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
async def save(self, record, expected_content_hash) -> DecisionRecord              # line 96
async def get(self, decision_id) -> tuple[DecisionRecord, str | None] | None       # line 45

# Contracts from earlier tasks (spec §3 skeletons)
class ConsequenceService:
    async def evaluate(self, spec_path: Path, *, mode: Literal["preview", "replay"] = "preview") -> ConsequenceReport
    async def governing(self, spec_path: Path, *, budget_tokens: int = 3000) -> GoverningDossier
class BatchPublisher:
    async def publish(self, batch_id: str) -> PublishResult      # status published|already-published|refused
async def render_spec(service, spec_path, *, budget_tokens) -> ConsequenceReport
async def check_spec(service, spec_path) -> CheckResult          # status current|stale|missing
class SpecConsequencesInput(BaseModel): spec_path: str; mode: Literal["check", "governing"] = "check"; budget_tokens: int
async def op_spec_consequences(store, params, **context) -> OperationResult   # transport binds root=ctx.root, store=ctx.store, config=ctx.config (TASK-5008)
def open_consequence_service(root: Path, *, store: Any = None, config: Any = None, base_branch: str = "dev") -> Any
def gate.main(argv: list[str] | None = None) -> int
# CLI (TASK-5009): `wikitoolkit spec consequences check <spec> --json` (group `spec`, LazyGroup in wiki/cli.py)
```

### Does NOT Exist
- ~~a shared integration fixture for a decision-audit repo~~ — build it in this module (`tmp_path` git repo).
- ~~multi-record transactions on `BaseWikiStore`~~ — batch atomicity is the marker protocol (PLAN decision 4).
- ~~`fakeredis`~~ — not installed; not needed (memory + sqlite stores only).
- ~~`ConsequenceReport.equals` / custom comparison~~ — compare `model_dump(mode="json")` dicts.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_decision_audit_integration.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The e2e fixture is a real temporary git repo: `git init -b dev`, a tiny `src/pkg/mod.py` (gives
  `file:`/`sym:`/`dir:` targets), `sdd/taxonomy/subsystems.yaml`, an empty `sdd/decisions/approvals.jsonl`,
  then `_build(runner, root)` so the structural plane exists. Run git through `subprocess.run(..., check=True)`
  with an explicit author (`-c user.name=… -c user.email=…`) — sync helpers in a test are fine.
- The approval adapter checks ancestry against `origin/<base>` or the local base with
  `APPROVAL_LOCAL_BASE`; approval `actor` is `%an <%ae>`; retirement/waiver entries skip the block-hash
  check (TASK-5001). The temp repo has no remote, so use TASK-5001's local-base path and assert the
  diagnostic is present (not an error).
- `test_cli_mcp_json_equivalence`: strip nothing — the three outputs must be equal dicts (minus the gate's
  extra `"check"` key, which only the script adds in check mode; drop that single key before comparing).
- If a test builds `InventorySnapshot` directly, `take()` also needs the keyword-only `store`, `root`,
  `config_digest` arguments (TASK-5003); prefer going through `ConsequenceService` so this stays internal.
- Evaluation parity: seed the same records into both `parity_store` params and compare
  `evaluation_digest`; the structural revision must be identical, so feed the same structural fixture
  pages (or the same built plane copied per backend — FILL IN per TASK-5005's StructuralService needs).

---

## Implementation Blueprint

### Steps (in order)
1. Write the `audit_repo` fixture (git repo + taxonomy + manifest + build) — *why*: every integration test needs it.
2. Write `test_end_to_end_preview_and_publish` inside the LLMFactory offline guard — *why*: AC1 + the core flow.
3. Write `test_conflict_resolution_paths` — *why*: AC4/AC9 at system level.
4. Write `test_cli_mcp_json_equivalence` — *why*: S11 surface parity (one wiring, TASK-5008).
5. Insert `TestSchema2Parity` into `test_backend_parity.py` — *why*: S11 backend parity.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_decision_audit_integration.py` (CREATE)
```python
"""FEAT-784 integration: preview → approve → publish, conflict paths, surface parity (spec §4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

import scripts.sdd.check_spec_consequences as gate
from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.decisions.consequences_render import check_spec, render_spec
from parrot.knowledge.wiki.decisions.operations import SpecConsequencesInput, op_spec_consequences
from parrot.knowledge.wiki.decisions.publish import BatchPublisher
from parrot.knowledge.wiki.decisions.spec_audit import open_consequence_service


def _git(root: Path, *args: str) -> str:
    cmd = ["git", "-C", str(root), "-c", "user.name=Audit Tester", "-c", "user.email=audit@example.test", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def audit_repo(tmp_path: Path) -> Path:
    """Temp git repo on `dev` with taxonomy, empty approvals manifest, one module, and a built plane."""
    # FILL IN: git init -b dev; write src/pkg/mod.py (one class), sdd/taxonomy/subsystems.yaml (two subsystems
    #   in TASK-5000's shape: schema_version 1, subsystems list, optional mapping), sdd/decisions/approvals.jsonl
    #   (empty); commit; then
    #   CliRunner().invoke(wiki, ["build", "--path", str(tmp_path), "--no-graph", "--quiet"]) exit 0
    raise NotImplementedError


def _spec(root: Path, slug: str, entries_yaml: str) -> Path:
    """Write sdd/specs/<slug>.spec.md with frontmatter projects/tags and a ## Decisions block."""
    # FILL IN: minimal spec text: frontmatter, "## 2. Architectural Design", "## 8. Open Questions",
    #   and a "## Decisions" fenced yaml block (schema_version 1, document_id slug, entries_yaml)
    raise NotImplementedError


async def test_end_to_end_preview_and_publish(audit_repo: Path, monkeypatch) -> None:
    from parrot.clients.factory import LLMFactory

    def _boom(*args, **kwargs):
        raise AssertionError("LLMFactory.create must never be called by the decision audit (AC1)")

    monkeypatch.setattr(LLMFactory, "create", staticmethod(_boom))
    # FILL IN: spec A with two entries → render_spec → check_spec == "current" and status "pass";
    #   set **Status**: approved, commit, append an ApprovalEntry (kind spec, actor = "Audit Tester
    #   <audit@example.test>" i.e. `%an <%ae>`, TASK-5001) for A, commit;
    #   BatchPublisher(...).publish(batch) == "published"; retry == "already-published" (AC12);
    #   spec B whose about/targets overlap → governing() lists both adr:spec:A#… ids (AC14)
    raise NotImplementedError


async def test_conflict_resolution_paths(audit_repo: Path) -> None:
    # FILL IN: published decision P; spec C with `contradicts: [P@rev]` ⇒ status conflict, exit 1;
    #   C with `supersedes: [P@rev]` (exact predecessor, identical target set) ⇒ that conflict resolved only;
    #   C with a waiver recorded as an approved manifest entry ⇒ resolved; same waiver without the entry ⇒
    #   still conflict — bounded by AC4, AC8, AC9
    raise NotImplementedError


async def test_cli_mcp_json_equivalence(audit_repo: Path) -> None:
    # FILL IN: after render, collect
    #   (1) json.loads(CliRunner().invoke(wiki, ["spec", "consequences", "check", str(spec), "--json",
    #        "--path", str(audit_repo)]).output)   [flag names per TASK-5009]
    #   (2) op_spec_consequences(None, SpecConsequencesInput(spec_path=str(spec), mode="check"), root=audit_repo,
    #        store=<built store>, config=<WikiProjectConfig>).data   [kwargs as transport binds them, TASK-5008]
    #   (3) gate.main([str(spec), "--root", str(audit_repo), "--json"]) stdout, minus the "check" key
    #   and assert (1) == (2) == (3) — bounded by spec §4 / S11
    raise NotImplementedError
```
**Why**: one fixture, real git, real plane; the three surfaces share TASK-5008's wiring, so equality is
the contract. `check_spec`, `render_spec`, `open_consequence_service` are imported for the FILL IN bodies.

### `packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^class TestLiveBackends:' packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py)
# BEFORE — insert above `class TestLiveBackends:` (verified: test_backend_parity.py:168)
class TestSchema2Parity:
    """FEAT-784 S11: schema-2 records and evaluations are backend-independent (sqlite + memory)."""

    async def test_backend_parity_schema2(self, parity_store):
        from parrot.knowledge.wiki.decisions.models import DecisionRef, DecisionTarget

        record = DecisionRecord(
            schema_version=2,
            decision_id="adr:spec:demo#rule",
            decision="Clients never persist history",
            origin="documented",
            source_status="accepted",
            normative="forbids",
            about=["clients"],
            targets=[DecisionTarget(target_id="dir:src/pkg", kind="dir")],
            contradicts=[DecisionRef(decision_id="adr:doc:x", revision=1)],
            document_id="demo",
            entry_id="rule",
            batch_id="b1",
        )
        repo = DecisionRepository(parity_store)
        await repo.save(record, None)
        loaded, _hash = await repo.get("adr:spec:demo#rule")
        assert loaded == record

    async def test_evaluation_parity_backends(self, parity_store, tmp_path):
        # FILL IN: seed identical records + structural fixture pages, build a ConsequenceService on
        #   parity_store, evaluate the same spec, and assert evaluation_digest equals a value computed once
        #   on the memory backend (store it via a module-level dict keyed by fixture param, or evaluate both
        #   backends inside one test with create_wiki_store for each) — bounded by S11 / AC10
        raise NotImplementedError


```
**Why**: reuses the module's existing mandatory-backend fixture so the report guard below keeps covering it.
FILL IN: confirm the `DecisionRecord` schema-2 field names against TASK-4997's final `models.py` before running.

### FILL IN checklist
- [ ] `audit_repo` fixture
- [ ] `_spec` helper
- [ ] e2e, conflict paths, surface equivalence bodies
- [ ] `test_evaluation_parity_backends` body
- [ ] schema-2 field names re-checked against TASK-4997

---

## Acceptance Criteria

- [ ] Preview → approval → publish → governing works end to end with zero LLM calls (AC1, AC12, AC14).
- [ ] Explicit conflict blocks; exact supersession and approved waiver resolve; unapproved waiver does not (AC4, AC8, AC9).
- [ ] CLI, MCP and gate script emit the same `ConsequenceReport` (S11).
- [ ] Schema-2 round-trip and `evaluation_digest` identical on sqlite and memory (S11, AC10).
- [ ] Existing `test_backend_parity.py` tests still pass unchanged.
- [ ] `ruff check` clean on both files.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_decision_audit_integration.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_backend_parity.py -q`

---

## Test Specification

See blueprint: `test_end_to_end_preview_and_publish`, `test_conflict_resolution_paths`,
`test_cli_mcp_json_equivalence`, `TestSchema2Parity.test_backend_parity_schema2`,
`TestSchema2Parity.test_evaluation_parity_backends`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Confirm TASK-5009, TASK-5010 and TASK-5013 are `done` (transitively everything else); re-read the final
   signatures of `consequences.py`, `publish.py`, `operations.py`, `spec_cli.py`, the gate script.
3. Mark in-progress, implement, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
   (the gate import needs the repo root on `sys.path`; run pytest from the worktree root).
4. Commit only the two listed files; close with `scripts/sdd/close_task.sh TASK-5015 sdd-decision-audit verified`.

---

## Completion Note

*(Agent fills this in when done)*
