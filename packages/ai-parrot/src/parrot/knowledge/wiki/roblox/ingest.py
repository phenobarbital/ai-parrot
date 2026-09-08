"""Generation validation, selection, explicit refresh and publication
(FEAT-532 TASK-2902).

``ingest_roblox_api(*, refresh: bool = False)`` is the single async entry
point spec §2 proposes. Without ``--refresh`` it never touches the
network — it validates and returns the existing published generation, or
raises an actionable error instructing the caller to run ``--refresh``
(spec: "First acquisition therefore requires ``--refresh``" — there is no
implicit first-build). With ``--refresh`` it compares identities (Studio
version, creator-docs commit, renderer schema version) against the
currently active generation and either reuses it unchanged or rebuilds
and atomically republishes — every acquisition/render/build failure
leaves the previous generation selected and readable (spec: "Preserve the
last good generation on all acquisition/render/publication failures").

Never mutates the global namespace registry itself — spec: "Do not
silently replace a user's existing ``roblox`` declaration." Registration
is always a manual, explicit ``wikitoolkit ns add`` step; this module
only returns the exact command as a hint.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime

from parrot.knowledge.wiki.roblox import generations
from parrot.knowledge.wiki.roblox.acquire import (
    AcquiredApiPayloads,
    RobloxApiAcquisitionError,
    acquire_roblox_api_payloads,
)
from parrot.knowledge.wiki.roblox.models import RobloxApiIngestResult, RobloxApiManifest
from parrot.knowledge.wiki.roblox.render import RenderedGeneration, build_normalized_dump, render_generation
from parrot.knowledge.wiki.store import SQLiteWikiStore, create_wiki_store

logger = logging.getLogger(__name__)

#: Bumping this forces every generation to rebuild on the next --refresh,
#: even when Studio version and creator-docs commit are both unchanged
#: (spec: "regenerate ... when ... the schema of the renderer" changes).
RENDERER_SCHEMA_VERSION = 1

_PAYLOADS_FILENAME = "payloads.json"


class RobloxApiNotIngestedError(Exception):
    """Raised by a no-``--refresh`` call with no valid published generation.

    Carries an actionable message (the exact ``--refresh`` command) —
    never a bare "not found".
    """


def _generation_id_for(studio_version: str, creator_docs_commit: str, schema_version: int) -> str:
    """A deterministic generation id: identical inputs -> identical id.

    This is what makes refresh's "unchanged -> no rebuild" cheap to
    detect (compare ids, no content diffing) and what lets a crashed
    publish resume idempotently (rebuilding the same inputs always lands
    on the same directory name).
    """
    raw = f"{studio_version}|{creator_docs_commit}|{schema_version}"
    return "gen-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _payloads_path_for(generation_id: str):
    return generations.generation_dir_for(generation_id) / _PAYLOADS_FILENAME


def _load_reuse_payloads(generation_id: str) -> AcquiredApiPayloads | None:
    """Load a previously published generation's full acquisition inputs.

    Persisted as **one** file per generation (spec: "Persist reusable
    inputs outside the repository without a per-file docs cache" — one
    blob, not one file per class), so a later ``--refresh`` can hand it
    back to :func:`acquire_roblox_api_payloads` for its identity-based
    reuse-skip without ever having cached individual class YAML files.
    """
    path = _payloads_path_for(generation_id)
    if not path.is_file():
        return None
    try:
        return AcquiredApiPayloads.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("Could not load persisted payloads for %s: %s", generation_id, exc)
        return None


def _save_payloads(generation_id: str, payloads: AcquiredApiPayloads) -> None:
    path = _payloads_path_for(generation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payloads.model_dump_json(), encoding="utf-8")


def _build_manifest(payloads: AcquiredApiPayloads, rendered: RenderedGeneration) -> RobloxApiManifest:
    return RobloxApiManifest(
        studio_version=payloads.studio_version,
        creator_docs_commit=payloads.creator_docs_commit,
        renderer_schema_version=RENDERER_SCHEMA_VERSION,
        source_hashes=payloads.source_hashes,
        downloaded_at=datetime.now(UTC).isoformat(),
        class_count=rendered.class_count,
        enum_count=rendered.enum_count,
        structural_only_count=rendered.structural_only_count,
        missing_doc_classes=rendered.missing_doc_classes,
        skipped=rendered.skipped,
    )


async def _build_generation(
    generation_id: str, rendered: RenderedGeneration, payloads: AcquiredApiPayloads
) -> RobloxApiManifest:
    """Build, write, and validate one immutable generation's SQLite plane.

    Args:
        generation_id: Target directory name under
            :func:`generations.generations_dir`.
        rendered: Pages/edges to write.
        payloads: The acquisition inputs, persisted alongside the
            generation for a future ``--refresh``'s reuse check.

    Returns:
        The built generation's :class:`RobloxApiManifest`.

    Raises:
        Exception: Any store/write failure propagates to the caller,
            which is responsible for preserving the previous generation
            (this function never touches the active pointer).
    """
    gen_dir = generations.generation_dir_for(generation_id)
    await asyncio.to_thread(gen_dir.mkdir, parents=True, exist_ok=True)

    store = create_wiki_store(gen_dir, wiki_name="roblox-api", backend="sqlite")
    await store.upsert_pages(rendered.pages)
    if rendered.edges:
        await store.add_edges(rendered.edges)

    # Close and validate before making it visible (spec §"API plane
    # acquisition and publication"): reopen strictly read-only and prove
    # the plane actually answers a query, rather than trusting the write
    # path alone.
    validator = SQLiteWikiStore(gen_dir / "wiki.db", read_only=True)
    await validator.broken_edges()

    manifest = _build_manifest(payloads, rendered)
    await asyncio.to_thread(_save_payloads, generation_id, payloads)
    return manifest


def _registration_hint() -> str | None:
    """A copy-pasteable registration command, or ``None`` if already registered.

    Never mutates the registry (spec: registration is manual). Reads
    :func:`~parrot.knowledge.wiki.project.load_global_registry` purely to
    decide whether a hint is still useful — a namespace named ``roblox``
    already present (whatever it points at — this module never judges
    "unrelated") means the user has already made a registration choice.
    """
    from parrot.knowledge.wiki.project import load_global_registry

    registry = load_global_registry()
    if "roblox" in registry.namespaces:
        return None
    return f"wikitoolkit ns add roblox --store {generations.current_store_dir()} --backend sqlite --global"


async def ingest_roblox_api(
    *,
    refresh: bool = False,
    http_timeout: float = 30.0,
    session=None,
) -> RobloxApiIngestResult:
    """Ingest (or validate/reuse) the Roblox API plane.

    Args:
        refresh: When ``False`` (default), performs **zero** network
            requests: validates and returns the existing published
            generation, or raises :class:`RobloxApiNotIngestedError`
            with the exact command to run. When ``True``, resolves
            current Studio version/creator-docs commit, reuses the
            active generation unchanged when both (and the renderer
            schema) match, and otherwise rebuilds and atomically
            republishes.
        http_timeout: Per-request timeout forwarded to acquisition.
        session: An existing ``aiohttp.ClientSession`` to reuse (mainly
            for tests); ``None`` lets acquisition manage its own.

    Returns:
        The :class:`RobloxApiIngestResult`.

    Raises:
        RobloxApiNotIngestedError: No ``--refresh`` and nothing valid published yet.
        RobloxApiAcquisitionError: A ``--refresh`` acquisition/build
            failure with **no** previous generation to fall back to
            (the very first ingest). Any subsequent failure instead
            returns the preserved previous generation with a diagnostic.
    """
    current_pointer = generations.read_active_pointer()
    current_valid = current_pointer is not None and generations.generation_is_valid(current_pointer.generation_id)

    if not refresh:
        if not current_valid:
            raise RobloxApiNotIngestedError(
                "No Roblox API plane has been ingested yet. Run "
                "`wikitoolkit ingest roblox-api --refresh` to fetch and publish it "
                "(this is the only command that ever makes network requests)."
            )
        manifest = RobloxApiManifest.model_validate(current_pointer.manifest)
        return RobloxApiIngestResult(
            generation_dir=str(generations.generation_dir_for(current_pointer.generation_id)),
            manifest=manifest,
            reused=True,
            published=False,
            diagnostics=["no --refresh: returning existing validated generation, zero network requests"],
        )

    reuse_payloads = _load_reuse_payloads(current_pointer.generation_id) if current_valid else None

    try:
        payloads, acquisition_reused = await acquire_roblox_api_payloads(
            reuse=reuse_payloads, http_timeout=http_timeout, session=session
        )
    except RobloxApiAcquisitionError:
        if current_valid:
            manifest = RobloxApiManifest.model_validate(current_pointer.manifest)
            return RobloxApiIngestResult(
                generation_dir=str(generations.generation_dir_for(current_pointer.generation_id)),
                manifest=manifest,
                reused=True,
                published=False,
                diagnostics=["--refresh acquisition failed; previous generation preserved"],
            )
        raise

    generation_id = _generation_id_for(payloads.studio_version, payloads.creator_docs_commit, RENDERER_SCHEMA_VERSION)

    if current_valid and current_pointer.generation_id == generation_id:
        manifest = RobloxApiManifest.model_validate(current_pointer.manifest)
        return RobloxApiIngestResult(
            generation_dir=str(generations.generation_dir_for(generation_id)),
            manifest=manifest,
            reused=True,
            published=False,
            diagnostics=["--refresh: identities and schema unchanged, generation already active"],
        )

    dump = build_normalized_dump(payloads.api_dump, payloads.class_docs)
    rendered = render_generation(dump, generation_id=generation_id, schema_version=RENDERER_SCHEMA_VERSION)

    try:
        manifest = await _build_generation(generation_id, rendered, payloads)
    except Exception as exc:  # noqa: BLE001 - preserve previous generation, report once
        if current_valid:
            old_manifest = RobloxApiManifest.model_validate(current_pointer.manifest)
            return RobloxApiIngestResult(
                generation_dir=str(generations.generation_dir_for(current_pointer.generation_id)),
                manifest=old_manifest,
                reused=True,
                published=False,
                diagnostics=[f"--refresh build failed ({exc}); previous generation preserved"],
            )
        raise RobloxApiAcquisitionError(f"generation build failed and no previous generation exists: {exc}") from exc

    promoted = generations.publish_generation_cas(
        current_pointer.generation_id if current_valid else None,
        generations.ActivePointer(generation_id, manifest.model_dump(mode="json")),
    )

    if not promoted:
        winner = generations.read_active_pointer()
        assert winner is not None  # a promotion just happened concurrently
        winner_manifest = RobloxApiManifest.model_validate(winner.manifest)
        return RobloxApiIngestResult(
            generation_dir=str(generations.generation_dir_for(winner.generation_id)),
            manifest=winner_manifest,
            reused=True,
            published=False,
            diagnostics=["a concurrent --refresh published first; deferred to it"],
        )

    diagnostics = []
    hint = _registration_hint()
    if hint is not None:
        diagnostics.append(f"Not yet registered as a namespace. Register with: {hint}")

    return RobloxApiIngestResult(
        generation_dir=str(generations.generation_dir_for(generation_id)),
        manifest=manifest,
        reused=acquisition_reused,
        published=True,
        diagnostics=diagnostics,
    )


def get_roblox_status() -> dict | None:
    """Offline status: recorded versions + download timestamp, no network.

    Returns:
        ``{"generation_id", "studio_version", "creator_docs_commit",
        "downloaded_at", "class_count", "enum_count"}``, or ``None`` when
        nothing has been ingested yet. Never makes a network request —
        spec: "`wikitoolkit status` ... never does network."
    """
    pointer = generations.read_active_pointer()
    if pointer is None or not generations.generation_is_valid(pointer.generation_id):
        return None
    manifest = pointer.manifest
    return {
        "generation_id": pointer.generation_id,
        "studio_version": manifest.get("studio_version"),
        "creator_docs_commit": manifest.get("creator_docs_commit"),
        "downloaded_at": manifest.get("downloaded_at"),
        "class_count": manifest.get("class_count"),
        "enum_count": manifest.get("enum_count"),
    }
