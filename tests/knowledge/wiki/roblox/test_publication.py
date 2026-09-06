"""Tests for Roblox API generation publication (FEAT-532 TASK-2902).

Isolates every test under its own ``PARROT_HOME`` (``tmp_path``) and
mocks acquisition entirely — no real network, matching the spec's
offline-test-fixture rule. Exercises ``ingest.py`` and ``generations.py``
together, since publication is defined by their interaction.
"""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.roblox import generations, ingest
from parrot.knowledge.wiki.roblox.acquire import AcquiredApiPayloads, RobloxApiAcquisitionError

pytestmark = pytest.mark.usefixtures("_isolated_parrot_home")


@pytest.fixture
def _isolated_parrot_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))


def _dump(studio_version_marker: str = "") -> dict:
    return {
        "Classes": [
            {"Name": f"Players{studio_version_marker}", "Superclass": "<<<ROOT>>>", "Members": []},
        ],
        "Enums": [],
    }


def _payloads(studio_version="0.1.0", commit="a" * 40, marker="") -> AcquiredApiPayloads:
    return AcquiredApiPayloads(
        studio_version=studio_version,
        api_dump=_dump(marker),
        creator_docs_commit=commit,
        class_docs={},
        source_hashes={"api_dump": "x", "creator_docs_tarball": "y"},
    )


def _mock_acquire(monkeypatch, payloads: AcquiredApiPayloads | list, *, fail: bool = False):
    """Install a fake ``acquire_roblox_api_payloads`` returning ``payloads``
    (or successive values from a list) — never touches the network."""
    calls = {"count": 0}
    sequence = payloads if isinstance(payloads, list) else [payloads] * 10

    async def _fake(*, reuse=None, http_timeout=30.0, session=None):
        calls["count"] += 1
        if fail:
            raise RobloxApiAcquisitionError("simulated acquisition failure")
        result = sequence[min(calls["count"] - 1, len(sequence) - 1)]
        reused = (
            reuse is not None
            and reuse.studio_version == result.studio_version
            and reuse.creator_docs_commit == result.creator_docs_commit
        )
        return result, reused

    monkeypatch.setattr(ingest, "acquire_roblox_api_payloads", _fake)
    return calls


def _mock_no_network(monkeypatch):
    async def _boom(**_kwargs):
        raise AssertionError("acquire_roblox_api_payloads must not be called")

    monkeypatch.setattr(ingest, "acquire_roblox_api_payloads", _boom)


# ---------------------------------------------------------------------------
# test_first_use_requires_refresh
# ---------------------------------------------------------------------------


async def test_first_use_requires_refresh(monkeypatch):
    """No-refresh missing plane performs zero requests and explains the command."""
    _mock_no_network(monkeypatch)
    with pytest.raises(ingest.RobloxApiNotIngestedError, match="--refresh"):
        await ingest.ingest_roblox_api(refresh=False)


# ---------------------------------------------------------------------------
# test_no_refresh_reuses_generation_offline
# ---------------------------------------------------------------------------


async def test_no_refresh_reuses_generation_offline(monkeypatch):
    """Existing plane is returned without revision probes or regeneration."""
    _mock_acquire(monkeypatch, _payloads())
    first = await ingest.ingest_roblox_api(refresh=True)
    assert first.published is True

    _mock_no_network(monkeypatch)
    second = await ingest.ingest_roblox_api(refresh=False)
    assert second.reused is True
    assert second.published is False
    assert second.generation_dir == first.generation_dir


# ---------------------------------------------------------------------------
# test_refresh_revision_matrix
# ---------------------------------------------------------------------------


async def test_refresh_revision_matrix_unchanged_skips_rebuild(monkeypatch):
    payloads = _payloads()
    _mock_acquire(monkeypatch, payloads)
    first = await ingest.ingest_roblox_api(refresh=True)

    _mock_acquire(monkeypatch, payloads)  # same identity again
    second = await ingest.ingest_roblox_api(refresh=True)

    assert second.generation_dir == first.generation_dir
    assert second.published is False
    assert second.reused is True
    assert "unchanged" in " ".join(second.diagnostics)


async def test_refresh_revision_matrix_studio_version_change_rebuilds(monkeypatch):
    _mock_acquire(monkeypatch, _payloads(studio_version="0.1.0"))
    first = await ingest.ingest_roblox_api(refresh=True)

    _mock_acquire(monkeypatch, _payloads(studio_version="0.2.0"))
    second = await ingest.ingest_roblox_api(refresh=True)

    assert second.generation_dir != first.generation_dir
    assert second.published is True


async def test_refresh_revision_matrix_docs_commit_change_rebuilds(monkeypatch):
    _mock_acquire(monkeypatch, _payloads(commit="a" * 40))
    first = await ingest.ingest_roblox_api(refresh=True)

    _mock_acquire(monkeypatch, _payloads(commit="b" * 40))
    second = await ingest.ingest_roblox_api(refresh=True)

    assert second.generation_dir != first.generation_dir
    assert second.published is True


async def test_refresh_revision_matrix_schema_bump_rebuilds(monkeypatch):
    payloads = _payloads()
    _mock_acquire(monkeypatch, payloads)
    first = await ingest.ingest_roblox_api(refresh=True)

    monkeypatch.setattr(ingest, "RENDERER_SCHEMA_VERSION", ingest.RENDERER_SCHEMA_VERSION + 1)
    _mock_acquire(monkeypatch, payloads)
    second = await ingest.ingest_roblox_api(refresh=True)

    assert second.generation_dir != first.generation_dir
    assert second.published is True
    assert second.manifest.renderer_schema_version == first.manifest.renderer_schema_version + 1


# ---------------------------------------------------------------------------
# test_failed_refresh_keeps_old_generation
# ---------------------------------------------------------------------------


async def test_failed_refresh_keeps_old_generation(monkeypatch):
    """Every acquisition/render/promotion failure preserves old readability."""
    _mock_acquire(monkeypatch, _payloads())
    first = await ingest.ingest_roblox_api(refresh=True)

    _mock_acquire(monkeypatch, _payloads(), fail=True)
    second = await ingest.ingest_roblox_api(refresh=True)

    assert second.generation_dir == first.generation_dir
    assert second.reused is True
    assert second.published is False
    assert "failed" in " ".join(second.diagnostics)

    # And a plain (no-refresh) read afterwards still works, offline.
    _mock_no_network(monkeypatch)
    still_readable = await ingest.ingest_roblox_api(refresh=False)
    assert still_readable.generation_dir == first.generation_dir


async def test_first_ingest_failure_raises_with_nothing_to_fall_back_to(monkeypatch):
    _mock_acquire(monkeypatch, _payloads(), fail=True)
    with pytest.raises(RobloxApiAcquisitionError):
        await ingest.ingest_roblox_api(refresh=True)

    # Confirms nothing was left half-published.
    assert generations.read_active_pointer() is None


# ---------------------------------------------------------------------------
# test_concurrent_publication_and_registry_conflict
# ---------------------------------------------------------------------------


def test_concurrent_publication_cas_conflict_no_lost_update():
    """No torn/lost registry update: a stale expected_current_id loses the race."""
    first_pointer = generations.ActivePointer("gen-a", {"studio_version": "0.1.0"})
    assert generations.publish_generation_cas(None, first_pointer) is True

    # Writer B observed "gen-a" as current and tries to promote gen-b.
    second_pointer = generations.ActivePointer("gen-b", {"studio_version": "0.2.0"})
    assert generations.publish_generation_cas("gen-a", second_pointer) is True

    # Writer A (stale observation of None/no-generation) retries with the
    # now-outdated expectation and must lose — active must stay "gen-b".
    stale_pointer = generations.ActivePointer("gen-a-retry", {"studio_version": "0.1.0"})
    assert generations.publish_generation_cas(None, stale_pointer) is False

    current = generations.read_active_pointer()
    assert current.generation_id == "gen-b"


async def test_registry_never_mutated_by_ingest(monkeypatch):
    """ingest_roblox_api never writes the global namespace registry —
    registration is always a manual, explicit `ns add` step."""
    from parrot.knowledge.wiki import project as wiki_project

    def _boom_save(*_args, **_kwargs):
        raise AssertionError("save_global_registry must never be called by ingest")

    monkeypatch.setattr(wiki_project, "save_global_registry", _boom_save)

    _mock_acquire(monkeypatch, _payloads())
    result = await ingest.ingest_roblox_api(refresh=True)
    assert result.published is True
    assert any("ns add roblox" in d for d in result.diagnostics)


async def test_registration_hint_absent_when_namespace_already_declared(monkeypatch):
    """An existing `roblox` namespace (any content) suppresses the hint —
    ingest never judges or overwrites it as "unrelated"."""
    from parrot.knowledge.wiki.project import GlobalWikiRegistry, WikiNamespaceConfig

    existing = GlobalWikiRegistry(namespaces={"roblox": WikiNamespaceConfig(store="/some/unrelated/path")})
    monkeypatch.setattr(
        "parrot.knowledge.wiki.project.load_global_registry",
        lambda *_a, **_k: existing,
    )

    _mock_acquire(monkeypatch, _payloads())
    result = await ingest.ingest_roblox_api(refresh=True)
    assert result.diagnostics == []  # no registration hint - already declared
