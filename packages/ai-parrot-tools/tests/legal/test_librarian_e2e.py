"""End-to-end tests for the fail-closed invariant (FEAT-449 TASK-2499, spec §4).

Deterministic, no network, no live LLM — the librarian is always a
``_CannedAgent`` (``conftest.py``) returning a fixed ``DraftAnswer``, and
every query states its ``as_of`` explicitly so ``extract_as_of`` never
needs the LLM fallback. Arango-dependent tests live in
``test_boe_integration.py`` (skip cleanly without a live server).
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from datetime import date
from pathlib import Path

import parrot_tools.legal as legal_pkg
from parrot_tools.legal.boe.hashing import HASH_NORM_VERSION, seal_hash
from parrot_tools.legal.boe.parser import parse_consolidated
from parrot_tools.legal.librarian.flow import answer
from parrot_tools.legal.librarian.models import DraftAnswer, DraftReadingNote, DraftSpan
from parrot_tools.legal.librarian.verifier import SpanVerifier

# ---------------------------------------------------------------------------
# test_reingest_seals_hashes_end_to_end
# ---------------------------------------------------------------------------


def test_reingest_seals_hashes_end_to_end(boe_corpus):
    """Every re-ingested version with text carries a verifiable sealed hash."""
    parsed = parse_consolidated(boe_corpus)
    assert parsed.articulos, "fixture must yield at least one articulo"
    for art in parsed.articulos:
        for v in art["versions"]:
            if v["text"] is None:
                assert v["content_hash"] is None
                assert v["hash_norm_version"] is None
            else:
                assert v["content_hash"] == seal_hash(v["text"])
                assert v["hash_norm_version"] == HASH_NORM_VERSION


# ---------------------------------------------------------------------------
# test_librarian_answers_with_anchored_guide
# ---------------------------------------------------------------------------


async def test_librarian_answers_with_anchored_guide(seeded_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer(
        "BOE-A-2015-10566:50 que dice el articulo a 2019-06-01",
        agent=canned_drafts.anchored,
        store=seeded_store,
        ctx=legal_tenant_ctx,
        log=fake_log,
    )
    keys = {f"{r.id}:{r.version_n}:{r.start}-{r.end}" for r in ans.dossier}
    assert ans.dossier
    assert ans.as_of == date(2019, 6, 1)
    assert all(set(n.spans) <= keys and n.spans for n in ans.reading_guide)
    assert fake_log.records == []


# ---------------------------------------------------------------------------
# test_librarian_honest_not_found
# ---------------------------------------------------------------------------


async def test_librarian_honest_not_found(fake_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer(
        "sentencias del Tribunal Constitucional sobre plazos a 2019-06-01",
        agent=canned_drafts.empty,
        store=fake_store,
        ctx=legal_tenant_ctx,
        log=fake_log,
    )
    assert ans.dossier == []
    assert ans.reading_guide == []
    assert "2019-06-01" in " ".join(ans.not_found)


# ---------------------------------------------------------------------------
# test_fabricated_span_cannot_survive
# ---------------------------------------------------------------------------


async def test_fabricated_span_cannot_survive(seeded_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer(
        "plazo a 2019-06-01",
        agent=canned_drafts.fabricated,
        store=seeded_store,
        ctx=legal_tenant_ctx,
        log=fake_log,
    )
    assert ans.suppressed_count >= 1
    assert any(r.reason == "span_not_found" for r in fake_log.records)
    assert all("BOE-A-9999" not in r.id for r in ans.dossier)


# ---------------------------------------------------------------------------
# test_mangled_quote_cannot_survive
# ---------------------------------------------------------------------------


async def test_mangled_quote_cannot_survive(seeded_store, legal_tenant_ctx, canned_drafts, fake_log):
    ans = await answer(
        "BOE-A-2015-10566:50 texto a 2019-06-01",
        agent=canned_drafts.mangled,
        store=seeded_store,
        ctx=legal_tenant_ctx,
        log=fake_log,
    )
    assert ans.dossier == []
    assert any(r.reason == "quote_mismatch" for r in fake_log.records)


# ---------------------------------------------------------------------------
# test_tampered_payload_cannot_survive
# ---------------------------------------------------------------------------


async def test_tampered_payload_cannot_survive(tampered_payload_entry):
    """Store tampering/drift since ingest -> hash_mismatch, defence in depth."""
    draft = DraftAnswer(
        reading_order=[tampered_payload_entry.payload_key],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="El plazo es de veinte meses.",
                basis="llm",
                spans=[
                    DraftSpan(
                        payload_key=tampered_payload_entry.payload_key,
                        quote="El plazo sera de VEINTE meses.",
                    )
                ],
            )
        ],
    )
    ans, records = SpanVerifier().verify(
        draft,
        {tampered_payload_entry.payload_key: tampered_payload_entry},
        as_of=date(2019, 6, 1),
        materias=["civil"],
        execution_id="e2e-tampered",
    )
    assert ans.dossier == []
    assert records and records[0].reason == "hash_mismatch"
    assert ans.suppressed_count == 1


# ---------------------------------------------------------------------------
# test_no_vector_code_paths
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORTS = {"parrot.embeddings", "pgvector", "parrot.stores.pgvector"}


def test_no_vector_code_paths():
    """Greppable-by-absence: no module under parrot_tools/legal/ touches vectors (R14)."""
    for mod in pkgutil.walk_packages(legal_pkg.__path__, legal_pkg.__name__ + "."):
        module = importlib.import_module(mod.name)
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        src = Path(module_file).read_text(encoding="utf-8")
        tree = ast.parse(src)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        hit = names & _FORBIDDEN_IMPORTS
        assert not hit, f"{mod.name} imports forbidden vector modules: {hit}"
