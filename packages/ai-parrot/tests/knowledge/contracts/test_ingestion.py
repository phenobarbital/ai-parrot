"""Staged ingestion and source-identity tests (TASK-3034)."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.knowledge.contracts.evidence import EvidenceRef
from parrot.knowledge.contracts.library import (
    SUPPORTED_FORMATS,
    ContractLibrary,
    OwnerRule,
    deterministic_sections,
    pdf_markdown,
)
from parrot.knowledge.contracts.models import Citation, FieldProvenance

from .test_catalog_contract import InMemoryContractCatalog

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 9)

MSA_MARKDOWN = """# ACME Master Services Agreement

This Agreement is entered into between Troc Global Inc. and ACME, Inc.

## Term

This Agreement is effective as of January 1, 2026 for twelve (12) months.

## Compliance

Vendor shall maintain SOC 2 Type II certification and must report annually.

## Signatures

Signed by Jane Doe, CFO of ACME, Inc.
"""

_HEADING = re.compile(r"^##?\s+(.*)$")


class FakeIndexer:
    """A minimal PageIndex tree builder over a real content store.

    Splits markdown on ``#``/``##`` headings into numbered nodes and writes
    each body through the injected :class:`NodeContentStore`, mirroring the
    lean-tree contract (bodies live in sidecars, not in the JSON).
    """

    def __init__(self, storage_dir: Path, adapter: Any = None) -> None:
        from parrot.knowledge.pageindex.content_store import NodeContentStore
        from parrot.knowledge.pageindex.store import JSONTreeStore

        self.storage_dir = Path(storage_dir)
        self.adapter = adapter
        self.content = NodeContentStore(self.storage_dir)
        self.store = JSONTreeStore(self.storage_dir)
        self.fail_on: set[str] = set()

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict:
        if tree_name in self.fail_on:
            raise RuntimeError("indexer exploded")
        tree = {"doc_name": doc_name or tree_name, "structure": []}
        self.store.save(tree_name, tree)
        return {"tree_name": tree_name}

    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: Optional[str] = None,
        doc_name: Optional[str] = None,
    ) -> dict:
        if tree_name in self.fail_on:
            raise RuntimeError("indexer exploded")
        tree = self.store.load(tree_name)
        nodes: list[dict] = []
        current_title = doc_name or tree_name
        current_lines: list[str] = []

        def _flush() -> None:
            if not current_lines and not nodes:
                return
            node_id = f"{len(nodes):04d}"
            body = "\n".join(current_lines).strip()
            nodes.append({"node_id": node_id, "title": current_title, "nodes": []})
            self.content.save(tree_name, node_id, f"{current_title}\n\n{body}")

        for line in markdown.splitlines():
            match = _HEADING.match(line)
            if match:
                _flush()
                current_title = match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        _flush()

        tree["structure"] = nodes
        self.store.save(tree_name, tree)
        return {"tree_name": tree_name, "new_node_ids": [node["node_id"] for node in nodes]}

    async def get_tree(self, tree_name: str) -> dict:
        return self.store.load(tree_name)

    async def delete_tree(self, tree_name: str) -> dict:
        self.store.delete(tree_name)
        self.content.delete_tree(tree_name)
        return {"tree_name": tree_name}


@pytest.fixture()
def indexers() -> dict[Path, FakeIndexer]:
    return {}


@pytest.fixture()
def library(tmp_path, indexers):
    """A library over an in-memory catalog and fake indexer (no LLM)."""
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)

    def factory(storage_dir: Path, adapter: Any) -> FakeIndexer:
        indexer = indexers.get(Path(storage_dir))
        if indexer is None:
            indexer = FakeIndexer(storage_dir, adapter)
            indexers[Path(storage_dir)] = indexer
        return indexer

    return ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=None,
        indexer_factory=factory,
        now=lambda: FROZEN_NOW,
        today=lambda: TODAY,
    )


def write(tmp_path: Path, name: str, text: str = MSA_MARKDOWN) -> Path:
    """Write a synthetic source document."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Format handling
# --------------------------------------------------------------------------


def test_supported_formats_are_the_pilot_set():
    assert set(SUPPORTED_FORMATS.values()) == {"md", "txt", "docx", "pdf"}


@pytest.mark.asyncio
async def test_markdown_ingestion_produces_a_card_and_pending_publication(library, tmp_path):
    result = await library.add_contract(write(tmp_path, "acme-msa.md"))

    assert result.outcome == "added"
    assert result.publication_state == "pending"
    card = result.card
    assert card.contract_id == "acme-msa"
    assert card.tree_name == "acme-msa"
    assert card.source_format == "md"
    assert card.card_origin == "fallback", "no adapter configured"
    assert card.contract_type == "msa"
    assert await library.catalog.get("acme-msa") is not None
    assert library.staging.has_published("acme-msa") is True
    assert not library.staging.staged_tree("acme-msa").exists()


@pytest.mark.asyncio
async def test_headingless_text_is_sectioned_deterministically(library, tmp_path):
    body = "\n\n".join(f"Paragraph {index} of the agreement." for index in range(6))
    result = await library.add_contract(write(tmp_path, "acme-notes.txt", body))

    assert result.outcome == "added"
    titles = [entry.title for entry in result.card.toc]
    assert titles and all(title.startswith("Section ") for title in titles)
    assert result.card.source_format == "txt"


@pytest.mark.asyncio
async def test_unsupported_format_is_skipped_with_a_reason(library, tmp_path):
    result = await library.add_contract(write(tmp_path, "notes.rtf", "x"))
    assert result.outcome == "skipped"
    assert "unsupported format .rtf" in result.reason
    assert result.card is None


@pytest.mark.asyncio
async def test_missing_source_is_an_error(library, tmp_path):
    result = await library.add_contract(tmp_path / "ghost.md")
    assert result.outcome == "error"
    assert "source not found" in result.reason


@pytest.mark.asyncio
async def test_empty_document_is_skipped(library, tmp_path):
    result = await library.add_contract(write(tmp_path, "blank.md", "   \n\n"))
    assert result.outcome == "skipped"
    assert "no readable content" in result.reason


@pytest.mark.asyncio
async def test_no_text_pdf_is_skipped_explicitly(library, tmp_path, monkeypatch):
    async def no_text(self, path):
        return ["", "  ", ""]

    monkeypatch.setattr(ContractLibrary, "_extract_pdf_pages", no_text)
    result = await library.add_contract(write(tmp_path, "scanned.pdf", "%PDF-1.7"))

    assert result.outcome == "skipped"
    assert "no extractable text" in result.reason
    assert "OCR is out of scope" in result.reason
    assert result.card is None


@pytest.mark.asyncio
async def test_text_pdf_keeps_physical_page_anchors(library, tmp_path, monkeypatch):
    async def pages(self, path):
        return [
            "MASTER SERVICES AGREEMENT between Troc Global and ACME, Inc.",
            "",
            "Vendor shall maintain SOC 2 Type II certification.",
        ]

    monkeypatch.setattr(ContractLibrary, "_extract_pdf_pages", pages)
    result = await library.add_contract(write(tmp_path, "acme-msa.pdf", "%PDF-1.7"))

    assert result.outcome == "added"
    titles = [entry.title for entry in result.card.toc]
    assert titles == ["Page 1", "Page 3"]
    assert result.card.page_count == 2


@pytest.mark.asyncio
async def test_docx_uses_the_shared_bookstore_helper(library, tmp_path, monkeypatch):
    calls: list[Path] = []

    async def fake_docx(path: Path) -> str:
        calls.append(path)
        return MSA_MARKDOWN

    monkeypatch.setattr("parrot.knowledge.contracts.library.docx_to_markdown", fake_docx)
    result = await library.add_contract(write(tmp_path, "acme-msa.docx", "binary"))

    assert result.outcome == "added"
    assert result.card.source_format == "docx"
    assert calls == [tmp_path / "acme-msa.docx"]


# --------------------------------------------------------------------------
# Source identity
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unchanged_content_creates_no_revision(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    first = await library.add_contract(path)
    second = await library.add_contract(path)

    assert second.outcome == "skipped"
    assert "unchanged content" in second.reason
    assert second.card.revision == first.card.revision == 1
    assert len(await library.catalog.versions("acme-msa")) == 1


@pytest.mark.asyncio
async def test_force_recards_unchanged_content_as_a_new_revision(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    await library.add_contract(path)
    forced = await library.add_contract(path, force=True)

    assert forced.outcome == "updated"
    assert forced.card.revision == 2
    history = await library.catalog.versions("acme-msa")
    assert [version.n for version in history] == [1, 2]


@pytest.mark.asyncio
async def test_changed_content_at_the_same_uri_updates_the_card(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    await library.add_contract(path)
    path.write_text(MSA_MARKDOWN + "\n## Insurance\n\nVendor shall carry insurance.\n")

    updated = await library.add_contract(path)
    assert updated.outcome == "updated"
    assert updated.card.revision == 2
    assert updated.card.source_sha256 != (await library.catalog.versions("acme-msa"))[0].source_sha256


@pytest.mark.asyncio
async def test_duplicate_content_at_another_uri_resolves_to_the_existing_card(library, tmp_path):
    original = write(tmp_path / "legal", "acme-msa.md")
    await library.add_contract(original)
    copy = write(tmp_path / "backup", "acme-msa-copy.md")

    result = await library.add_contract(copy)
    assert result.outcome == "skipped"
    assert "duplicate content of 'acme-msa'" in result.reason
    assert result.card.contract_id == "acme-msa"
    assert result.card.source_uri == original.as_uri(), "the canonical URI is retained"
    assert await library.catalog.taken_slugs() == {"acme-msa"}


@pytest.mark.asyncio
async def test_slug_collisions_get_a_suffix(library, tmp_path):
    first = await library.add_contract(write(tmp_path / "a", "acme-msa.md"))
    second = await library.add_contract(write(tmp_path / "b", "acme-msa.md", MSA_MARKDOWN + "\n\nDifferent body.\n"))
    assert first.card.contract_id == "acme-msa"
    assert second.card.contract_id == "acme-msa-2"


# --------------------------------------------------------------------------
# Folder ingestion and ownership
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_folder_ingestion_is_recursive_and_deterministic(library, tmp_path):
    root = tmp_path / "legal"
    write(root, "a-msa.md")
    write(root, "b-sow.md", MSA_MARKDOWN + "\n\nStatement of work body.\n")
    write(root / "archive", "c-nda.md", MSA_MARKDOWN + "\n\nNDA body.\n")
    write(root, "ignored.rtf", "x")

    shallow = await library.add_folder(root)
    assert shallow.summary() == {"added": 2, "updated": 0, "skipped": 0, "errors": 0}
    assert all(item.source_uri.endswith(".md") for item in shallow.items)
    assert [item.contract_id for item in shallow.items if item.outcome == "added"] == [
        "a-msa",
        "b-sow",
    ]

    deep = await library.add_folder(root, recursive=True)
    assert deep.added == 1  # only the archived NDA is new
    assert deep.skipped == 2  # the two already-ingested documents are unchanged


@pytest.mark.asyncio
async def test_folder_that_does_not_exist_is_reported(library, tmp_path):
    report = await library.add_folder(tmp_path / "nope")
    assert report.errors == 1
    assert "not a folder" in report.items[0].reason


@pytest.mark.asyncio
async def test_most_specific_owner_rule_wins_and_unmatched_stays_unassigned(tmp_path, indexers):
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    library = ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=None,
        indexer_factory=lambda directory, adapter: indexers.setdefault(
            Path(directory), FakeIndexer(directory, adapter)
        ),
        owner_rules=[
            OwnerRule(path_prefix=str(tmp_path / "legal"), owner_employee_id="emp-1", department="legal"),
            OwnerRule(
                path_prefix=str(tmp_path / "legal" / "emea"),
                owner_employee_id="emp-2",
                department="legal-emea",
            ),
        ],
        now=lambda: FROZEN_NOW,
        today=lambda: TODAY,
    )

    generic = await library.add_contract(write(tmp_path / "legal", "a-msa.md"))
    specific = await library.add_contract(
        write(tmp_path / "legal" / "emea", "b-msa.md", MSA_MARKDOWN + "\n\nEMEA body.\n")
    )
    unmatched = await library.add_contract(write(tmp_path / "other", "c-msa.md", MSA_MARKDOWN + "\n\nOther body.\n"))

    assert (generic.card.owner_employee_id, generic.card.department) == ("emp-1", "legal")
    assert (specific.card.owner_employee_id, specific.card.department) == (
        "emp-2",
        "legal-emea",
    )
    assert unmatched.card.owner_employee_id is None
    assert unmatched.card.department is None


@pytest.mark.asyncio
async def test_manual_owner_override_survives_later_ingestion(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    first = await library.add_contract(path)

    overridden = first.card.model_copy(
        update={
            "owner_employee_id": "emp-manual",
            "department": "finance",
            "field_provenance": {
                **first.card.field_provenance,
                "owner_employee_id": FieldProvenance(
                    origin="manual",
                    verification="verified",
                    verified_by="bob@troc",
                    verified_at=FROZEN_NOW,
                ),
            },
        }
    )
    await library.catalog.upsert(overridden, expected_revision=1)

    path.write_text(MSA_MARKDOWN + "\n\nRefreshed body.\n")
    updated = await library.add_contract(path)

    assert updated.outcome == "updated"
    assert updated.card.owner_employee_id == "emp-manual"
    assert updated.card.department == "finance"


# --------------------------------------------------------------------------
# Evidence, versions and failure handling
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingestion_archives_evidence_that_citations_can_resolve(library, tmp_path):
    result = await library.add_contract(write(tmp_path, "acme-msa.md"))
    version = (await library.catalog.versions("acme-msa"))[0]
    ref = EvidenceRef.parse(version.evidence_ref)

    assert ref.contract_id == "acme-msa"
    assert ref.version_n == 1
    body = await library.evidence.load_body(ref, "0001")
    assert "effective as of January 1, 2026" in body

    citation = Citation(
        contract_id="acme-msa",
        node_id="0001",
        quote="effective as of January 1, 2026",
        version_n=1,
        source_sha256=result.card.source_sha256,
    )
    assert (await library.evidence.resolve(citation, ref)).found is True


@pytest.mark.asyncio
async def test_each_revision_archives_its_own_evidence(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    await library.add_contract(path)
    path.write_text(MSA_MARKDOWN.replace("twelve (12) months", "twenty-four (24) months"))
    await library.add_contract(path)

    refs = await library.evidence.versions("acme-msa")
    assert [ref.version_n for ref in refs] == [1, 2]
    assert "twelve (12) months" in await library.evidence.load_body(refs[0], "0001")
    assert "twenty-four (24) months" in await library.evidence.load_body(refs[1], "0001")


@pytest.mark.asyncio
async def test_indexing_failure_preserves_the_previous_card_and_evidence(library, tmp_path, indexers):
    path = write(tmp_path, "acme-msa.md")
    first = await library.add_contract(path)
    published_before = library.staging.published_tree("acme-msa").read_text()

    for indexer in indexers.values():
        indexer.fail_on.add("acme-msa")
    path.write_text(MSA_MARKDOWN + "\n\nBroken revision.\n")
    failed = await library.add_contract(path)

    assert failed.outcome == "error"
    assert "indexing failed" in failed.reason
    stored = await library.catalog.get("acme-msa")
    assert stored.revision == first.card.revision == 1
    assert library.staging.published_tree("acme-msa").read_text() == published_before
    assert not library.staging.staged_tree("acme-msa").exists()
    refs = await library.evidence.versions("acme-msa")
    assert [ref.version_n for ref in refs] == [1]


@pytest.mark.asyncio
async def test_catalog_failure_between_staging_and_publication_rolls_back(library, tmp_path, monkeypatch):
    path = write(tmp_path, "acme-msa.md")
    first = await library.add_contract(path)
    published_before = library.staging.published_tree("acme-msa").read_text()

    async def boom(*args, **kwargs):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr(library.catalog, "upsert", boom)
    path.write_text(MSA_MARKDOWN + "\n\nSecond revision.\n")
    failed = await library.add_contract(path)

    assert failed.outcome == "error"
    assert "catalog unavailable" in failed.reason
    assert (await library.catalog.get("acme-msa")).revision == first.card.revision
    assert library.staging.published_tree("acme-msa").read_text() == published_before
    assert not library.staging.staged_tree("acme-msa").exists()


@pytest.mark.asyncio
async def test_conversion_failure_is_reported_as_an_error(library, tmp_path, monkeypatch):
    async def boom(path):
        raise RuntimeError("corrupt docx")

    monkeypatch.setattr("parrot.knowledge.contracts.library.docx_to_markdown", boom)
    result = await library.add_contract(write(tmp_path, "acme-msa.docx", "x"))

    assert result.outcome == "error"
    assert "conversion failed: corrupt docx" in result.reason


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def test_deterministic_sections_are_stable_and_numbered():
    text = "\n\n".join(f"Paragraph {index}" for index in range(5))
    first = deterministic_sections(text, chunk_chars=30)
    assert first == deterministic_sections(text, chunk_chars=30)
    assert first.count("## Section ") >= 2
    assert deterministic_sections("") == ""


def test_pdf_markdown_skips_empty_pages_but_keeps_page_numbers():
    markdown = pdf_markdown(["first", "   ", "third"])
    assert "## Page 1" in markdown
    assert "## Page 2" not in markdown
    assert "## Page 3" in markdown
    assert pdf_markdown(["", " "]) == ""
