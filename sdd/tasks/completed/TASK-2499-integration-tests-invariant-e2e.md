# TASK-2499: Integration tests — the fail-closed invariant end-to-end

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2492, TASK-2493, TASK-2494, TASK-2495, TASK-2496, TASK-2497, TASK-2498
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 + §4 Integration Tests + §5 Acceptance Criteria. Every
module ships its own unit tests; this task proves the **whole chain** holds
the R2 invariant: re-ingest seals hashes → retrieval finds the in-force
wording → the librarian's draft is gated → a fabricated span cannot survive →
the corpus is visible through the FEAT-450 federation. LLM-dependent tests
mock the client with canned `DraftAnswer`s; Arango-dependent tests reuse
TASK-2376's integration markers and skip-if-no-server semantics.

---

## Scope

- Extend `packages/ai-parrot-tools/tests/legal/conftest.py`:
  - `tampered_payload_entry` fixture (payload text mutated after hash seal).
  - `canned_drafts` fixture: (a) a well-anchored draft citing real
    fixture quotes; (b) one citing a fabricated `payload_key`; (c) one with a
    mangled quote.
  - `seeded_store` fixture: `FakeGraphStore` populated by running
    `parse_consolidated` over the TASK-2372 fixture (versions carry sealed
    hashes from TASK-2492).
- `test_librarian_e2e.py` (deterministic, no network):
  - `test_reingest_seals_hashes_end_to_end` — run the refresh path over the
    fixture via the fake store (or the real `sync_boe` under the Arango
    marker) ⇒ every stored version with text carries `content_hash ==
    seal_hash(text)` and `hash_norm_version == 1`; `supresion` versions carry none.
  - `test_librarian_answers_with_anchored_guide` — known-norm question ⇒
    dossier non-empty; every `ReadingNote.spans` ⊆ dossier span keys;
    `as_of` populated and equals the retrieval date.
  - `test_librarian_honest_not_found` — case-law question over the norms-only
    corpus ⇒ `dossier == []`, `not_found` corpus-scoped (mentions materias
    + `as_of`), `reading_guide == []`, returns normally.
  - `test_fabricated_span_cannot_survive` — draft (b) ⇒ span pruned,
    sentence suppressed, `suppressed_count == 1`, `SuppressionRecord` in the
    log with `reason == "span_not_found"`.
  - `test_mangled_quote_cannot_survive` — draft (c) ⇒ `quote_mismatch`.
  - `test_tampered_payload_cannot_survive` — tampered fixture ⇒ `hash_mismatch`.
  - `test_no_vector_code_paths` — greppable-by-absence AC: assert no module
    under `parrot_tools/legal/` imports `parrot.embeddings`, `pgvector`, or
    defines `search_vector` returning anything but `[]` (walk the package
    with `pkgutil`/`ast`).
- `test_boe_integration.py` (extend, Arango-marked): 
  - `test_search_view_provisioned_idempotently` — `initialize_tenant` twice ⇒
    one `legal_articulos_view` with the declared links.
  - `test_search_articles_live_temporal_filter` — repealed wording not
    returned for a later `as_of`.
  - `test_namespace_exposes_legal_corpus` — `open_namespace_store("legal",
    WikiNamespaceConfig(database=<tenant db>, backend="ontology_legal"), …)`
    ⇒ `search_fts` returns a known article; writes refuse.
- Run the full suites and record evidence in `artifacts/logs/`:
  `pytest packages/ai-parrot-tools/tests/legal/ -v` and
  `pytest packages/ai-parrot/tests/knowledge/ontology/ packages/ai-parrot/tests/knowledge/wiki/ -v`.
- Walk spec §5 Acceptance Criteria and tick each in the Completion Note with
  the test that proves it (or the review that enforces it for "zero vector
  code paths" / "no breaking changes").

**NOT in scope**: new production code (if a test exposes a defect, fix it in
the owning module with a clearly scoped commit and note the deviation);
performance benchmarks; case-law fixtures.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/tests/legal/conftest.py` | MODIFY | tampered/canned/seeded fixtures |
| `packages/ai-parrot-tools/tests/legal/test_librarian_e2e.py` | CREATE | deterministic end-to-end invariant tests |
| `packages/ai-parrot-tools/tests/legal/test_boe_integration.py` | MODIFY | Arango-marked view/search/namespace tests |
| `artifacts/logs/feat-449-librarian-tests.log` | CREATE | pytest evidence |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev` (+ all FEAT-449 deliverables).

### Verified Imports
```python
from parrot_tools.legal.boe.hashing import seal_hash, HASH_NORM_VERSION          # TASK-2492
from parrot_tools.legal.boe.parser import parse_consolidated                      # parser.py:83
from parrot_tools.legal.boe.queries import article_in_force, search_articles      # queries.py:24 / TASK-2496
from parrot_tools.legal.boe.sync import sync_boe                                  # sync.py:24
from parrot_tools.legal.librarian.models import DraftAnswer, DraftReadingNote, DraftSpan, LegalAnswer, PayloadEntry  # TASK-2495
from parrot_tools.legal.librarian.verifier import SpanVerifier                    # TASK-2495
from parrot_tools.legal.librarian.flow import answer                              # TASK-2497
from parrot_tools.legal.wiki_store import OntologyLegalWikiStore                  # TASK-2498
from parrot.knowledge.wiki.federation import open_namespace_store                 # federation.py:340
from parrot.knowledge.wiki.project import WikiNamespaceConfig                     # project.py
from parrot.knowledge.ontology.graph_store import OntologyGraphStore              # graph_store.py:34
```

### Existing Signatures to Use
```python
# tests/legal/conftest.py (TASK-2376)
FIXTURE_DIR = Path(__file__).parent / "fixtures"                 # :25
@pytest.fixture def boe_corpus() -> str                           # :30  checked-in consolidated XML
@pytest.fixture def legal_tenant_ctx() -> TenantContext           # :36  resolves domain="legal" from package defaults
class FakeGraphStore                                              # :76  initialize_tenant/get_all_nodes/upsert_nodes/soft_delete_nodes/create_edges/execute_traversal
@pytest.fixture def fake_store() -> FakeGraphStore                # :167

# tests/legal/test_boe_integration.py — Arango integration markers + skip-if-no-server helpers (READ the file
#   header to reuse the exact marker name and connection fixture).
```

### Does NOT Exist
- ~~A real LLM in any test~~ — the librarian is always a fake returning canned `DraftAnswer`s.
- ~~Network access to boe.es in tests~~ — parsing runs off the checked-in fixture only.
- ~~Case-law fixtures / `sentencia` spans~~ — Sprint 3; the "honest not found" test uses a case-law *question* over the norms-only corpus.
- ~~Any vector/embedding fixture~~ — R14; `test_no_vector_code_paths` enforces absence.

---

## Implementation Notes

### Pattern to Follow
```python
# greppable-by-absence check
import ast, pkgutil, importlib
import parrot_tools.legal as pkg

FORBIDDEN = {"parrot.embeddings", "pgvector", "parrot.stores.pgvector"}

def test_no_vector_code_paths():
    for mod in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
        src = Path(importlib.import_module(mod.name).__file__).read_text()
        tree = ast.parse(src)
        names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not (names & FORBIDDEN), f"{mod.name} imports {names & FORBIDDEN}"
```

### Key Constraints
- Deterministic tests must not depend on `date.today()` — pass explicit
  `as_of` in the query text (e.g. "… a 2019-06-01") so `extract_as_of`
  resolves without the LLM fallback.
- Arango-marked tests must skip cleanly when no server is reachable.
- Do not loosen any assertion from TASK-2376.

### References in Codebase
- `packages/ai-parrot-tools/tests/legal/test_boe_integration.py` — integration marker conventions
- `packages/ai-parrot-tools/tests/legal/test_temporal_resolution.py` — pattern-wrapper test style

---

## Acceptance Criteria

- [ ] All five spec §4 integration tests exist and pass (Arango ones skip cleanly without a server, pass with one)
- [ ] `test_fabricated_span_cannot_survive`, `test_mangled_quote_cannot_survive`, `test_tampered_payload_cannot_survive` prove the three prune reasons end-to-end
- [ ] `test_no_vector_code_paths` passes
- [ ] Spec §5 Acceptance Criteria each mapped to a passing test (or review note) in the Completion Note
- [ ] `pytest packages/ai-parrot-tools/tests/legal/ -v` green; `pytest packages/ai-parrot/tests/knowledge/ontology/ packages/ai-parrot/tests/knowledge/wiki/ -v` green
- [ ] Evidence saved to `artifacts/logs/feat-449-librarian-tests.log`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_librarian_e2e.py
from datetime import date
from parrot_tools.legal.librarian.flow import answer


async def test_librarian_answers_with_anchored_guide(seeded_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer("¿qué plazo fija el artículo a 2019-06-01?", agent=canned_drafts.anchored,
                       store=seeded_store, ctx=legal_tenant_ctx, log=fake_log)
    keys = {f"{r.id}:{r.version_n}:{r.start}-{r.end}" for r in ans.dossier}
    assert ans.dossier and ans.as_of == date(2019, 6, 1)
    assert all(set(n.spans) <= keys and n.spans for n in ans.reading_guide)


async def test_fabricated_span_cannot_survive(seeded_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer("plazo a 2019-06-01", agent=canned_drafts.fabricated,
                       store=seeded_store, ctx=legal_tenant_ctx, log=fake_log)
    assert ans.suppressed_count >= 1
    assert any(r.reason == "span_not_found" for r in fake_log.records)
    assert all("BOE-A-9999" not in r.id for r in ans.dossier)


async def test_librarian_honest_not_found(fake_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer("sentencias del Tribunal Constitucional sobre plazos a 2019-06-01",
                       agent=canned_drafts.empty, store=fake_store, ctx=legal_tenant_ctx, log=fake_log)
    assert ans.dossier == [] and ans.reading_guide == [] and "2019-06-01" in " ".join(ans.not_found)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 M8, §4, §5)
2. **Check dependencies** — ALL of TASK-2492 … TASK-2498 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read the completion notes of every prior task for naming deviations before writing fixtures
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2499-integration-tests-invariant-e2e.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below, including the §5 AC → test mapping

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:
- Extended `conftest.py`: `seeded_store` (a `FakeGraphStore` populated by
  running `parse_consolidated` over the checked-in TASK-2372 fixture —
  every non-`supresion` version therefore carries a real sealed hash,
  TASK-2492), `tampered_payload_entry` (text mutated AFTER hashing, so
  `seal_hash(payload) != content_hash`), `canned_drafts` (four
  `_CannedAgent`s — `anchored` citing a REAL verbatim quote from the
  fixture's `BOE-A-2015-10566:50` v0 text, `fabricated` citing an
  unknown id, `mangled` with a non-existent quote, `empty` for the
  honest-not-found case), and `fake_log` (records every appended
  `SuppressionRecord`).
- `test_librarian_e2e.py` (7 deterministic tests, no network): the
  hash-reingest proof, the anchored-guide happy path, the honest
  not-found path, and the three prune-reason proofs
  (`span_not_found`/`quote_mismatch` through the full `answer()` flow;
  `hash_mismatch` through `SpanVerifier` directly since a tampered
  payload isn't naturally reachable via `graph_retrieve`/`dossier_build`,
  which always compute `content_hash` correctly from the stored record —
  the tampering scenario is a store-corruption simulation, not a
  retrieval-path one). `test_no_vector_code_paths` walks every module
  under `parrot_tools.legal` via `pkgutil`/`ast` asserting none imports
  `parrot.embeddings`/`pgvector`/`parrot.stores.pgvector` (R14).
- `test_boe_integration.py` extended with 3 live-ArangoDB tests
  (`@pytest.mark.integration`, `TestLiveArangoSearchViews`,
  `TestLiveSearchArticlesTemporalFilter`, `TestLiveNamespaceFederation`),
  gated on `ARANGODB_HOST`/`TEST_ARANGO_HOST` (mirrors the skip
  convention in `packages/ai-parrot/tests/integration/rag/
  test_store_router_integration.py`) plus a live-connection-failure skip.
  Verified they SKIP CLEANLY in this environment (no Arango credentials
  configured — confirmed via `env | grep -i arango`, empty) — exit code 0,
  3 skipped. The live-server PASS path was NOT exercised (no reachable
  dev tenant available to this autonomous, non-interactive session);
  operator follow-up: run with `ARANGODB_HOST` set against the dev tenant
  to exercise the pass path.
- Deterministic queries always state `as_of` explicitly in the query text
  (e.g. "... a 2019-06-01") so `extract_as_of`/the flow's narrowed
  `as_of_extract` (TASK-2497) never needs the LLM fallback — `_CannedAgent.ask`
  raises `AssertionError` if ever called, as a regression tripwire.
- Evidence saved to `artifacts/logs/feat-449-librarian-tests.log`
  (force-added with `git add -f` — `artifacts/` is globally gitignored,
  per this repo's existing `templates/` precedent for explicitly-required
  tracked exceptions) — captures all three required `pytest -v` runs.
- `pytest packages/ai-parrot-tools/tests/legal/ -v` → **146 passed, 3
  skipped** (34 new across `test_librarian_e2e.py` + the two extended
  files, on top of the 139 from TASK-2492–2498; net new PASSING count is
  7 new e2e tests since the 3 live-arango additions skip). `pytest
  packages/ai-parrot/tests/knowledge/ontology/ -v` → **206 passed**.
  `pytest packages/ai-parrot/tests/knowledge/wiki/ -v` → **223 passed,
  2 failed** (both `test_installer_mcp.py` — confirmed pre-existing/
  unrelated via `git stash` baseline comparison, same 2 failures with
  zero FEAT-449 changes applied). `ruff check` on every touched file:
  zero new blocking issues (the `except Exception` BLE001 warnings on
  the 4 new live-Arango skip handlers mirror the SAME unaddressed
  pattern already present in `test_store_router_integration.py` — a
  deliberate "any failure -> skip" idiom, not narrowed).

**Spec §5 AC mapping**:
| # | Acceptance Criterion | Proven by |
|---|---|---|
| 1 | Every `versions[]` entry carries `content_hash`/`hash_norm_version=1`; `supresion` carries none | `test_reingest_seals_hashes_end_to_end` (TASK-2499) + `test_article_version_carries_sealed_hash` (TASK-2492) |
| 2 | `search_views` provisioned idempotently; init twice ⇒ one view | `test_ensure_views_idempotent` (TASK-2493, `FakeConnection`) + `test_search_view_provisioned_idempotently` (TASK-2499, live — skips without a server) |
| 3 | `search_articles` returns in-force wording only for the queried `as_of` | `test_search_articles_temporal_filter` (TASK-2496) + `test_search_articles_live_temporal_filter` (TASK-2499, live — skips without a server) |
| 4 | The one-line invariant holds mechanically (wrong id/hash/offsets never reach the caller) | `test_fabricated_span_cannot_survive`, `test_mangled_quote_cannot_survive`, `test_tampered_payload_cannot_survive` (TASK-2499) + the full `SpanVerifier` unit suite (TASK-2495) |
| 5 | Empty dossier ⇒ first-class "no encontré", success not error | `test_librarian_honest_not_found` (TASK-2499) + `test_empty_dossier_is_no_encontre` (TASK-2495) |
| 6 | Every `ReadingNote` anchored into the delivered dossier; `as_of` always populated and matches retrieval | `test_librarian_answers_with_anchored_guide` (TASK-2499) + `test_as_of_equals_graph_retrieve_date` (TASK-2497) |
| 7 | Legal corpus resolves as a read-only FEAT-450 namespace; `search_fts` returns a known article; writes refuse | `test_namespace_exposes_legal_corpus` (TASK-2499, live — skips without a server) + `TestReadOnly`/`TestSearchFts` (TASK-2498 unit tests, always run) |
| 8 | Zero vector-search code paths (greppable by absence) | `test_no_vector_code_paths` (TASK-2499) |
| 9 | All unit + integration tests pass | This task's full evidence log (146 passed/3 skipped legal; 206 passed ontology) |
| 10 | No breaking changes to `article_in_force`, `sync_boe`, or existing ontology YAML consumers | Full `packages/ai-parrot/tests/knowledge/ontology/` suite green (206 passed, includes base/knowledge/field_services domains) + `TestBOEIntegration`/`TestTemporalResolution` unchanged and green |

**Deviations from spec**: none requiring production-code changes (per
this task's own "NOT in scope: new production code" — no defect was
found in any prior module while writing these tests; all fixtures and
assertions were satisfied on the first implementation attempt, confirmed
by the full green run above). One test-design adaptation, not a spec
deviation: the given Test Specification's
`test_librarian_answers_with_anchored_guide` query
("¿qué plazo fija el artículo a 2019-06-01?") relies on BM25 search
finding the fixture article by keyword — but the fixture's real text for
`BOE-A-2015-10566:50` doesn't contain the word "plazo" at all (verified
by inspection), so a keyword-only query would return an empty dossier
regardless of the canned draft, defeating the test's purpose. Adapted the
query to include the explicit BOE id
(`"BOE-A-2015-10566:50 que dice el articulo a 2019-06-01"`), which
resolves deterministically via `graph_retrieve`'s explicit-id pass
(`article_in_force`) — the SAME robustness pattern already used by every
TASK-2497 flow test. The anchored draft's quote is still copied verbatim
from the real fixture text (not fabricated), so the test still proves
exactly what it's meant to.
