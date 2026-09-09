"""Immutable, tenant-scoped evidence storage tests (TASK-3033)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.knowledge.contracts.evidence import (
    EvidenceArchive,
    EvidenceError,
    EvidenceRef,
    StagingArea,
    normalize_quote,
    validate_path_segment,
)
from parrot.knowledge.contracts.models import Citation

BODIES_V1 = {
    "0001": "MASTER SERVICES AGREEMENT between Troc Global and ACME Inc.",
    "0005": "Vendor shall maintain SOC 2 Type II certification.",
}
BODIES_V2 = {
    "0001": "MASTER SERVICES AGREEMENT between Troc Global and ACME Inc.",
    "0009": "Vendor shall maintain SOC 2 Type II certification.",
}


def citation(**overrides) -> Citation:
    """A citation pinned to version 1 of the ACME MSA."""
    payload = {
        "contract_id": "acme-msa",
        "title": "ACME MSA",
        "node_id": "0005",
        "quote": "Vendor shall maintain SOC 2 Type II certification.",
        "version_n": 1,
        "source_sha256": "sha-v1",
        "page": None,
    }
    payload.update(overrides)
    return Citation(**payload)


@pytest.fixture()
def archive(tmp_path: Path) -> EvidenceArchive:
    return EvidenceArchive(tmp_path / "evidence", tenant_id="troc")


@pytest.fixture()
def staging(tmp_path: Path) -> StagingArea:
    return StagingArea(tmp_path / "storage", tenant_id="troc")


# --------------------------------------------------------------------------
# Path safety and tenancy
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["../escape", "a/b", "", "  ", "x" * 129, "tenant\x00", "/absolute", "..", "a b"],
)
def test_path_segments_reject_traversal_and_separators(value):
    with pytest.raises(EvidenceError):
        validate_path_segment(value, what="tenant id")


def test_archive_and_staging_reject_unsafe_tenants(tmp_path):
    with pytest.raises(EvidenceError):
        EvidenceArchive(tmp_path, tenant_id="../other")
    with pytest.raises(EvidenceError):
        StagingArea(tmp_path, tenant_id="../other")


@pytest.mark.asyncio
async def test_unsafe_node_ids_are_rejected_on_read_and_write(archive):
    ref = archive.reference("acme-msa", source_sha256="sha-v1")
    with pytest.raises(EvidenceError):
        await archive.archive(ref, {"../../etc/passwd": "boom"})
    with pytest.raises(EvidenceError):
        await archive.load_body(ref, "../../etc/passwd")


@pytest.mark.asyncio
async def test_two_tenants_reusing_slugs_and_node_ids_cannot_cross_read(tmp_path):
    root = tmp_path / "evidence"
    troc = EvidenceArchive(root, tenant_id="troc")
    zeta = EvidenceArchive(root, tenant_id="zeta")

    troc_ref = await troc.archive(troc.reference("acme-msa", source_sha256="sha-troc"), {"0005": "troc secret clause"})
    zeta_ref = await zeta.archive(zeta.reference("acme-msa", source_sha256="sha-zeta"), {"0005": "zeta secret clause"})

    assert await troc.load_body(troc_ref, "0005") == "troc secret clause"
    assert await zeta.load_body(zeta_ref, "0005") == "zeta secret clause"

    # A reference from the other tenant is refused, not silently served.
    with pytest.raises(EvidenceError, match="bound to"):
        await troc.load_body(zeta_ref, "0005")
    with pytest.raises(EvidenceError):
        await zeta.load_body(troc_ref, "0005")

    assert [ref.as_string() for ref in await troc.versions("acme-msa")] == [troc_ref.as_string()]


def test_reference_round_trip_and_malformed_references():
    ref = EvidenceRef(tenant_id="troc", contract_id="acme-msa", version_n=2, revision=3, source_sha256="abc123")
    assert ref.as_string() == "troc/acme-msa/v2-r3-abc123"
    assert EvidenceRef.parse(ref.as_string()) == ref

    for bad in ["", "troc/acme-msa", "troc/acme-msa/not-a-version", "a/b/c/d"]:
        with pytest.raises(EvidenceError):
            EvidenceRef.parse(bad)


# --------------------------------------------------------------------------
# Immutability and archived lookups
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_writes_bodies_pages_and_a_manifest(archive, tmp_path):
    ref = archive.reference("acme-msa", source_sha256="sha-v1")
    await archive.archive(ref, BODIES_V1, pages={"0001": 1, "0005": 12})

    manifest = await archive.manifest(ref)
    assert manifest["nodes"] == ["0001", "0005"]
    assert manifest["pages"] == {"0001": 1, "0005": 12}
    assert manifest["source_sha256"] == "sha-v1"
    assert await archive.load_body(ref, "0005") == BODIES_V1["0005"]
    assert await archive.load_body(ref, "9999") is None


@pytest.mark.asyncio
async def test_archived_evidence_is_immutable_unless_explicitly_overwritten(archive):
    ref = archive.reference("acme-msa", source_sha256="sha-v1")
    await archive.archive(ref, BODIES_V1)
    with pytest.raises(EvidenceError, match="immutable"):
        await archive.archive(ref, {"0005": "tampered"})
    assert await archive.load_body(ref, "0005") == BODIES_V1["0005"]

    await archive.archive(ref, {"0005": "retried"}, overwrite=True)
    assert await archive.load_body(ref, "0005") == "retried"


@pytest.mark.asyncio
async def test_only_derived_text_is_archived_never_the_original(archive, tmp_path):
    original = tmp_path / "acme-msa.pdf"
    original.write_bytes(b"%PDF-1.7 binary payload")

    ref = archive.reference("acme-msa", source_sha256="sha-v1")
    await archive.archive(ref, BODIES_V1)

    archived = list((tmp_path / "evidence").rglob("*"))
    assert all(path.suffix in {"", ".md", ".json"} for path in archived)
    assert not any(path.suffix == ".pdf" for path in archived)
    assert original.read_bytes() == b"%PDF-1.7 binary payload"


@pytest.mark.asyncio
async def test_archive_from_loader_offloads_and_skips_missing_nodes(archive):
    calls: list[str] = []

    def loader(node_id: str):
        calls.append(node_id)
        if node_id == "missing":
            return None
        if node_id == "broken":
            raise RuntimeError("unreadable sidecar")
        return BODIES_V1.get(node_id)

    ref = archive.reference("acme-msa", source_sha256="sha-v1")
    await archive.archive_from_loader(ref, loader, ["0001", "missing", "broken", "0005"])

    manifest = await archive.manifest(ref)
    assert manifest["nodes"] == ["0001", "0005"]
    assert calls == ["0001", "missing", "broken", "0005"]


# --------------------------------------------------------------------------
# Citation resolution
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_historical_citation_still_resolves_after_a_refresh(archive):
    v1 = await archive.archive(
        archive.reference("acme-msa", version_n=1, revision=1, source_sha256="sha-v1"),
        BODIES_V1,
        pages={"0005": 12},
    )
    # The refresh renumbers the clause into another node and archives v2.
    await archive.archive(
        archive.reference("acme-msa", version_n=2, revision=1, source_sha256="sha-v2"),
        BODIES_V2,
    )

    lookup = await archive.resolve(citation(page=12), v1)
    assert lookup.found is True
    assert lookup.page == 12
    assert "SOC 2" in lookup.body

    assert [ref.version_n for ref in await archive.versions("acme-msa")] == [1, 2]


@pytest.mark.asyncio
async def test_wrong_version_hash_node_page_and_contract_all_fail(archive):
    ref = await archive.archive(
        archive.reference("acme-msa", version_n=1, revision=1, source_sha256="sha-v1"),
        BODIES_V1,
        pages={"0005": 12},
    )

    assert (await archive.resolve(citation(version_n=2), ref)).reason.startswith("citation version")
    assert "source hash" in (await archive.resolve(citation(source_sha256="other"), ref)).reason
    assert "not in this version" in (await archive.resolve(citation(node_id="0009"), ref)).reason
    assert "page does not match" in (await archive.resolve(citation(page=99), ref)).reason
    assert "another contract" in (await archive.resolve(citation(contract_id="zeta-nda"), ref)).reason


@pytest.mark.asyncio
async def test_a_quote_that_is_not_verbatim_is_refused(archive):
    ref = await archive.archive(archive.reference("acme-msa", source_sha256="sha-v1"), BODIES_V1)
    lookup = await archive.resolve(citation(quote="Vendor shall donate a pony."), ref)
    assert lookup.found is False
    assert "not verbatim" in lookup.reason


@pytest.mark.asyncio
async def test_rewrapped_whitespace_still_resolves(archive):
    ref = await archive.archive(
        archive.reference("acme-msa", source_sha256="sha-v1"),
        {"0005": "Vendor shall maintain\n   SOC 2 Type II certification."},
    )
    assert (await archive.resolve(citation(), ref)).found is True


# --------------------------------------------------------------------------
# Evidence mapping for retirement propagation and refresh
# --------------------------------------------------------------------------


def test_moved_nodes_map_only_nonempty_exact_evidence():
    mapping = EvidenceArchive.map_evidence(
        {
            "obligations.ob-1": "Vendor shall maintain SOC 2 Type II certification.",
            "title": "",
            "governing_law": "   ",
            "term.expiration_date": "a clause that no longer exists",
        },
        BODIES_V2,
    )
    assert mapping["obligations.ob-1"] == "0009", "the clause moved from 0005 to 0009"
    assert mapping["title"] is None, "an empty quote never proves unchanged evidence"
    assert mapping["governing_law"] is None
    assert mapping["term.expiration_date"] is None


def test_evidence_mapping_is_deterministic_when_a_quote_appears_twice():
    bodies = {"0007": "Vendor shall comply.", "0003": "Vendor shall comply."}
    mapping = EvidenceArchive.map_evidence({"f": "Vendor shall comply."}, bodies)
    assert mapping["f"] == "0003"
    assert EvidenceArchive.map_evidence({"f": "Vendor shall comply."}, bodies) == mapping


def test_normalize_quote_collapses_whitespace():
    assert normalize_quote("  a\n\tb  c ") == "a b c"
    assert normalize_quote("") == ""


# --------------------------------------------------------------------------
# Staged ingestion
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_staging_begin_creates_a_clean_area_without_touching_published(staging):
    published = await _publish(staging, "acme-msa", "published body")

    staging_root = await staging.begin("acme-msa")
    assert staging_root == staging.staging_root
    assert not staging.staged_tree("acme-msa").exists()
    assert published.read_text() == "published body"
    assert staging.has_published("acme-msa") is True


@pytest.mark.asyncio
async def test_promote_replaces_the_published_tree_and_content(staging):
    await _publish(staging, "acme-msa", "old body")
    await _stage(staging, "acme-msa", "new body")

    await staging.promote("acme-msa")

    assert json.loads(staging.published_tree("acme-msa").read_text())["version"] == "staged"
    assert (staging.published_root / "acme-msa" / "0005.md").read_text() == "new body"
    assert not staging.staged_tree("acme-msa").exists()
    assert not (staging.staging_root / "acme-msa").exists()


@pytest.mark.asyncio
async def test_a_failed_staging_write_preserves_the_current_tree_and_evidence(staging, archive):
    published = await _publish(staging, "acme-msa", "old body")
    ref = await archive.archive(archive.reference("acme-msa", source_sha256="sha-v1"), BODIES_V1)

    await staging.begin("acme-msa")
    # The refresh fails before anything is staged: discard must not touch
    # the published tree or the archived evidence.
    await staging.discard("acme-msa")

    assert published.read_text() == "old body"
    assert json.loads(staging.published_tree("acme-msa").read_text())["version"] == "published"
    assert await archive.load_body(ref, "0005") == BODIES_V1["0005"]


@pytest.mark.asyncio
async def test_promoting_nothing_is_an_explicit_error(staging):
    await _publish(staging, "acme-msa", "old body")
    with pytest.raises(EvidenceError, match="nothing staged"):
        await staging.promote("acme-msa")
    assert staging.has_published("acme-msa") is True


@pytest.mark.asyncio
async def test_first_ingestion_promotes_without_a_previous_tree(staging):
    await _stage(staging, "new-contract", "first body")
    await staging.promote("new-contract")
    assert staging.has_published("new-contract") is True
    assert (staging.published_root / "new-contract" / "0005.md").read_text() == "first body"


@pytest.mark.asyncio
async def test_staging_paths_are_tenant_scoped(tmp_path):
    troc = StagingArea(tmp_path / "storage", tenant_id="troc")
    zeta = StagingArea(tmp_path / "storage", tenant_id="zeta")
    assert troc.published_root != zeta.published_root
    assert "troc" in str(troc.published_tree("acme-msa"))
    assert "zeta" in str(zeta.staged_tree("acme-msa"))
    with pytest.raises(EvidenceError):
        troc.published_tree("../escape")


async def _publish(staging: StagingArea, contract_id: str, body: str) -> Path:
    """Write a fake published tree + content directory."""
    staging.published_root.mkdir(parents=True, exist_ok=True)
    staging.published_tree(contract_id).write_text(json.dumps({"version": "published"}))
    content = staging.published_root / contract_id
    content.mkdir(parents=True, exist_ok=True)
    node = content / "0005.md"
    node.write_text(body)
    return node


async def _stage(staging: StagingArea, contract_id: str, body: str) -> Path:
    """Write a fake staged tree + content directory."""
    await staging.begin(contract_id)
    staging.staged_tree(contract_id).write_text(json.dumps({"version": "staged"}))
    content = staging.staging_root / contract_id
    content.mkdir(parents=True, exist_ok=True)
    node = content / "0005.md"
    node.write_text(body)
    return node


@pytest.mark.asyncio
async def test_retry_after_sidecars_moved_preserves_the_published_content(staging):
    import shutil

    await _publish(staging, "acme-msa", "old body")
    await _stage(staging, "acme-msa", "new body")
    staged_index = staging.staged_tree("acme-msa")
    published_index = staging.published_tree("acme-msa")
    # Simulate process death after the last rename, before staged-index cleanup.
    published_index.replace(published_index.with_suffix(".json.previous"))
    (staging.published_root / "acme-msa").rename(staging.published_root / "acme-msa.previous")
    shutil.copyfile(staged_index, published_index)
    (staging.staging_root / "acme-msa").rename(staging.published_root / "acme-msa")
    await staging.promote("acme-msa")
    assert (staging.published_root / "acme-msa" / "0005.md").read_text() == "new body"
    assert not staged_index.exists()
