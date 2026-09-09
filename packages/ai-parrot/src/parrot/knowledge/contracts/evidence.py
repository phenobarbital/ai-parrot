"""Immutable, tenant- and version-scoped evidence storage (FEAT-539 M4).

Two responsibilities live here:

* :class:`StagingArea` — a PageIndex storage root per tenant, split into a
  ``published`` tree store and a ``staging`` one. A refresh builds the new
  tree in staging and only *promotes* it once the new card/evidence pair is
  complete, so a failure never destroys the currently published tree (this
  is deliberately **not** the bookstore's delete-before-reimport refresh).
* :class:`EvidenceArchive` — immutable copies of the *derived* node text for
  one ``(tenant, contract, version, revision, source hash)``, so a citation
  released months ago still resolves to the exact text it quoted. Original
  binaries are never copied: only the indexed markdown and its physical-page
  metadata.

Every path segment is validated; a tenant can never read another tenant's
evidence even when both reuse the same contract slug and node ids.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

from pydantic import BaseModel, Field

from .models import Citation

__all__ = (
    "EvidenceError",
    "EvidenceRef",
    "EvidenceLookup",
    "StagingArea",
    "EvidenceArchive",
    "normalize_quote",
    "validate_path_segment",
)

logger = logging.getLogger(__name__)

_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MANIFEST_NAME = "manifest.json"


class EvidenceError(RuntimeError):
    """Evidence could not be archived, promoted or resolved."""


def validate_path_segment(value: str, *, what: str = "segment") -> str:
    """Validate one on-disk path segment.

    Args:
        value: Tenant id, contract id or node id.
        what: Label used in the error message.

    Returns:
        The validated segment.

    Raises:
        EvidenceError: On empty values, separators or traversal attempts
            (``..``, ``/``, absolute paths, NUL bytes).
    """
    if not _SEGMENT_RE.match(value or ""):
        raise EvidenceError(f"invalid {what} {value!r}: expected 1-128 characters matching " "^[A-Za-z0-9_-]+$")
    return value


def normalize_quote(text: str) -> str:
    """Collapse whitespace so a re-wrapped quote still matches its source."""
    return " ".join((text or "").split())


class EvidenceRef(BaseModel):
    """A stable pointer to one archived evidence set.

    Args:
        tenant_id: Owning tenant.
        contract_id: Owning contract.
        version_n: Contractual version the evidence belongs to.
        revision: Recorded revision of that version.
        source_sha256: SHA-256 of the source bytes behind it.
    """

    tenant_id: str
    contract_id: str
    version_n: int = Field(default=1, ge=1)
    revision: int = Field(default=1, ge=1)
    source_sha256: str = ""

    @property
    def directory(self) -> str:
        """The archive directory name for this reference."""
        digest = (self.source_sha256 or "nohash")[:16] or "nohash"
        return f"v{self.version_n}-r{self.revision}-{digest}"

    def as_string(self) -> str:
        """Serialise to the compact reference stored on a version row."""
        return f"{self.tenant_id}/{self.contract_id}/{self.directory}"

    @classmethod
    def parse(cls, value: str) -> "EvidenceRef":
        """Parse a reference produced by :meth:`as_string`.

        Raises:
            EvidenceError: When the reference is malformed.
        """
        parts = (value or "").split("/")
        if len(parts) != 3:
            raise EvidenceError(f"malformed evidence reference {value!r}")
        tenant_id, contract_id, directory = parts
        match = re.match(r"^v(\d+)-r(\d+)-(.+)$", directory)
        if not match:
            raise EvidenceError(f"malformed evidence reference {value!r}")
        return cls(
            tenant_id=validate_path_segment(tenant_id, what="tenant id"),
            contract_id=validate_path_segment(contract_id, what="contract id"),
            version_n=int(match.group(1)),
            revision=int(match.group(2)),
            source_sha256=match.group(3),
        )


class EvidenceLookup(BaseModel):
    """The result of resolving a citation against archived evidence.

    Args:
        found: Whether the exact quote was located.
        body: The archived node body, when the node exists.
        page: The archived physical page for that node.
        reason: Why a lookup failed (unknown version, unknown node,
            quote not verbatim, page mismatch, empty quote…).
    """

    found: bool = False
    body: Optional[str] = None
    page: Optional[int] = None
    reason: str = ""


class StagingArea:
    """Per-tenant PageIndex storage split into published and staging roots.

    Args:
        root: Root directory holding every tenant's contract storage.
        tenant_id: Tenant this area is bound to.

    Raises:
        EvidenceError: When ``tenant_id`` is not a safe path segment.
    """

    def __init__(self, root: str | Path, *, tenant_id: str) -> None:
        self._root = Path(root)
        self._tenant_id = validate_path_segment(tenant_id, what="tenant id")

    @property
    def tenant_id(self) -> str:
        """The tenant this area is bound to."""
        return self._tenant_id

    @property
    def published_root(self) -> Path:
        """Storage root of the currently published trees."""
        return self._root / self._tenant_id / "published"

    @property
    def staging_root(self) -> Path:
        """Storage root where a refresh builds its replacement tree."""
        return self._root / self._tenant_id / "staging"

    def published_tree(self, contract_id: str) -> Path:
        """Path of one published tree's JSON index."""
        validate_path_segment(contract_id, what="contract id")
        return self.published_root / f"{contract_id}.json"

    def staged_tree(self, contract_id: str) -> Path:
        """Path of one staged tree's JSON index."""
        validate_path_segment(contract_id, what="contract id")
        return self.staging_root / f"{contract_id}.json"

    def has_published(self, contract_id: str) -> bool:
        """Whether a published tree exists for ``contract_id``."""
        return self.published_tree(contract_id).exists()

    async def begin(self, contract_id: str) -> Path:
        """Prepare a clean staging directory for ``contract_id``.

        Only *staging* data is discarded — the published tree and its
        content directory are untouched.

        Returns:
            The staging storage root to hand to a PageIndex toolkit.
        """
        validate_path_segment(contract_id, what="contract id")

        def _prepare() -> Path:
            self.staging_root.mkdir(parents=True, exist_ok=True)
            self.published_root.mkdir(parents=True, exist_ok=True)
            stale_index = self.staged_tree(contract_id)
            if stale_index.exists():
                stale_index.unlink()
            stale_content = self.staging_root / contract_id
            if stale_content.exists():
                shutil.rmtree(stale_content)
            return self.staging_root

        return await asyncio.to_thread(_prepare)

    async def promote(self, contract_id: str) -> None:
        """Atomically replace the published tree with the staged one.

        Raises:
            EvidenceError: When nothing was staged for ``contract_id``.
        """
        validate_path_segment(contract_id, what="contract id")

        def _promote() -> None:
            staged_index = self.staged_tree(contract_id)
            if not staged_index.exists():
                raise EvidenceError(f"nothing staged for contract {contract_id!r}")
            self.published_root.mkdir(parents=True, exist_ok=True)
            published_index = self.published_tree(contract_id)
            published_content = self.published_root / contract_id
            staged_content = self.staging_root / contract_id
            previous_index = published_index.with_suffix(".json.previous")
            previous_content = published_content.with_name(f"{contract_id}.previous")
            if (
                not staged_content.exists()
                and published_content.exists()
                and published_index.exists()
                and staged_index.read_bytes() == published_index.read_bytes()
            ):
                # A worker died after moving sidecars but before clearing staging.
                # The published pair is already complete; never move it aside.
                staged_index.unlink()
                if previous_index.exists():
                    previous_index.unlink()
                if previous_content.exists():
                    shutil.rmtree(previous_content)
                return
            try:
                if published_index.exists():
                    published_index.replace(previous_index)
                if published_content.exists():
                    published_content.rename(previous_content)
                # Keep the staged index until the sidecars have moved. If the
                # content rename fails, a retry still has the complete candidate.
                promoting_index = published_index.with_suffix(".json.promoting")
                shutil.copyfile(staged_index, promoting_index)
                promoting_index.replace(published_index)
                if staged_content.exists():
                    staged_content.rename(published_content)
            except OSError as exc:  # pragma: no cover - filesystem failure
                if previous_index.exists():
                    previous_index.replace(published_index)
                if previous_content.exists():
                    previous_content.rename(published_content)
                raise EvidenceError(f"failed to promote {contract_id!r}: {exc}") from exc
            staged_index.unlink()
            if previous_index.exists():
                previous_index.unlink()
            if previous_content.exists():
                shutil.rmtree(previous_content)

        await asyncio.to_thread(_promote)

    async def discard(self, contract_id: str) -> None:
        """Drop staged data only; published evidence is never touched."""
        validate_path_segment(contract_id, what="contract id")

        def _discard() -> None:
            staged_index = self.staged_tree(contract_id)
            if staged_index.exists():
                staged_index.unlink()
            staged_content = self.staging_root / contract_id
            if staged_content.exists():
                shutil.rmtree(staged_content)

        await asyncio.to_thread(_discard)


class EvidenceArchive:
    """Immutable archive of derived node text per contract version.

    Args:
        root: Root directory of the evidence archive.
        tenant_id: Tenant this archive is bound to; never an argument on
            the read/write methods, so cross-tenant reads are impossible.

    Raises:
        EvidenceError: When ``tenant_id`` is not a safe path segment.
    """

    def __init__(self, root: str | Path, *, tenant_id: str) -> None:
        self._root = Path(root)
        self._tenant_id = validate_path_segment(tenant_id, what="tenant id")

    @property
    def tenant_id(self) -> str:
        """The tenant this archive is bound to."""
        return self._tenant_id

    def _directory(self, ref: EvidenceRef) -> Path:
        """Resolve one reference to its on-disk directory, tenant-scoped."""
        if ref.tenant_id != self._tenant_id:
            raise EvidenceError(
                f"evidence reference belongs to tenant {ref.tenant_id!r}, "
                f"this archive is bound to {self._tenant_id!r}"
            )
        validate_path_segment(ref.contract_id, what="contract id")
        return self._root / self._tenant_id / ref.contract_id / ref.directory

    def reference(
        self,
        contract_id: str,
        *,
        version_n: int = 1,
        revision: int = 1,
        source_sha256: str = "",
    ) -> EvidenceRef:
        """Build a tenant-bound reference for this archive."""
        return EvidenceRef(
            tenant_id=self._tenant_id,
            contract_id=validate_path_segment(contract_id, what="contract id"),
            version_n=version_n,
            revision=revision,
            source_sha256=source_sha256,
        )

    async def archive(
        self,
        ref: EvidenceRef,
        bodies: Mapping[str, str],
        *,
        pages: Optional[Mapping[str, int]] = None,
        overwrite: bool = False,
    ) -> EvidenceRef:
        """Archive one version's derived node text immutably.

        Args:
            ref: The version this evidence belongs to.
            bodies: ``node_id -> markdown`` for every indexed node.
            pages: Physical page per node, when the source was a PDF.
            overwrite: Allow rewriting an existing archive (refresh retry).

        Returns:
            The reference that was written.

        Raises:
            EvidenceError: On an invalid node id, a cross-tenant reference,
                or an existing archive when ``overwrite`` is False.
        """
        directory = self._directory(ref)
        page_map = dict(pages or {})
        for node_id in bodies:
            validate_path_segment(node_id, what="node id")

        def _write() -> None:
            if directory.exists() and not overwrite:
                raise EvidenceError(
                    f"evidence for {ref.as_string()} already archived; archived " "evidence is immutable"
                )
            directory.mkdir(parents=True, exist_ok=True)
            for node_id, body in bodies.items():
                (directory / f"{node_id}.md").write_text(body, encoding="utf-8")
            manifest = {
                "tenant_id": ref.tenant_id,
                "contract_id": ref.contract_id,
                "version_n": ref.version_n,
                "revision": ref.revision,
                "source_sha256": ref.source_sha256,
                "nodes": sorted(bodies),
                "pages": {node: page_map[node] for node in sorted(page_map)},
            }
            (directory / _MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

        await asyncio.to_thread(_write)
        logger.debug("Archived %d evidence nodes at %s", len(bodies), ref.as_string())
        return ref

    async def archive_from_loader(
        self,
        ref: EvidenceRef,
        loader: Callable[[str], Optional[str]],
        node_ids: Iterable[str],
        *,
        pages: Optional[Mapping[str, int]] = None,
        overwrite: bool = False,
    ) -> EvidenceRef:
        """Archive node text read through a content-store loader.

        The synchronous reads are offloaded; only derived index text is
        copied — never the original document.
        """
        ids = list(node_ids)

        def _read() -> dict[str, str]:
            bodies: dict[str, str] = {}
            for node_id in ids:
                try:
                    body = loader(node_id)
                except Exception:  # noqa: BLE001 - a missing sidecar is skipped
                    body = None
                if body is not None:
                    bodies[node_id] = body
            return bodies

        bodies = await asyncio.to_thread(_read)
        return await self.archive(ref, bodies, pages=pages, overwrite=overwrite)

    async def manifest(self, ref: EvidenceRef) -> Optional[dict[str, Any]]:
        """Return one archived version's manifest, or ``None``."""
        path = self._directory(ref) / _MANIFEST_NAME

        def _read() -> Optional[dict[str, Any]]:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

        return await asyncio.to_thread(_read)

    async def load_body(self, ref: EvidenceRef, node_id: str) -> Optional[str]:
        """Read one archived node body.

        Raises:
            EvidenceError: On a traversal attempt or a cross-tenant read.
        """
        validate_path_segment(node_id, what="node id")
        path = self._directory(ref) / f"{node_id}.md"

        def _read() -> Optional[str]:
            if not path.is_file():
                return None
            return path.read_text(encoding="utf-8")

        return await asyncio.to_thread(_read)

    async def versions(self, contract_id: str) -> list[EvidenceRef]:
        """List archived references for one contract, oldest first."""
        validate_path_segment(contract_id, what="contract id")
        base = self._root / self._tenant_id / contract_id

        def _list() -> list[str]:
            if not base.is_dir():
                return []
            return sorted(entry.name for entry in base.iterdir() if entry.is_dir())

        names = await asyncio.to_thread(_list)
        refs: list[EvidenceRef] = []
        for name in names:
            try:
                refs.append(EvidenceRef.parse(f"{self._tenant_id}/{contract_id}/{name}"))
            except EvidenceError:  # pragma: no cover - foreign directory
                logger.debug("Skipping unrecognised evidence directory %s", name)
        refs.sort(key=lambda item: (item.version_n, item.revision))
        return refs

    async def resolve(self, citation: Citation, ref: EvidenceRef) -> EvidenceLookup:
        """Resolve one citation against a specific archived version.

        A citation resolves only when the version's archive exists, the
        cited node exists in it, the quote is nonempty and appears verbatim
        in that archived body, and the recorded page matches.

        Args:
            citation: The citation to check.
            ref: The archived version it claims to come from.

        Returns:
            An :class:`EvidenceLookup` with an explicit failure reason.
        """
        if citation.contract_id != ref.contract_id:
            return EvidenceLookup(reason="citation belongs to another contract")
        if citation.version_n != ref.version_n:
            return EvidenceLookup(reason="citation version does not match the archive")
        if citation.source_sha256 and ref.source_sha256:
            if not ref.source_sha256.startswith(citation.source_sha256[:16]):
                return EvidenceLookup(reason="citation source hash does not match")
        quote = normalize_quote(citation.quote)
        if not quote:
            return EvidenceLookup(reason="empty quotes never prove evidence")
        body = await self.load_body(ref, citation.node_id)
        if body is None:
            return EvidenceLookup(reason=f"node {citation.node_id!r} is not in this version")
        if quote not in normalize_quote(body):
            return EvidenceLookup(body=body, reason="quote is not verbatim in the archived body")
        page = None
        manifest = await self.manifest(ref)
        if manifest:
            page = manifest.get("pages", {}).get(citation.node_id)
        if citation.page is not None and page is not None and citation.page != page:
            return EvidenceLookup(body=body, page=page, reason="cited page does not match")
        return EvidenceLookup(found=True, body=body, page=page)

    @staticmethod
    def map_evidence(
        quotes: Mapping[str, str],
        new_bodies: Mapping[str, str],
    ) -> dict[str, Optional[str]]:
        """Rebind quotes to the node that now contains them.

        Only **nonempty exact** quotes can be rebound: an empty quote never
        proves that evidence is unchanged, so it maps to ``None`` and its
        field stays stale pending review. When the same quote appears in
        several nodes the lowest node id wins, deterministically.

        Args:
            quotes: ``field path -> previously verified quote``.
            new_bodies: ``node_id -> markdown`` of the refreshed tree.

        Returns:
            ``field path -> node id`` (or ``None`` when unmapped).
        """
        normalized = {node_id: normalize_quote(body) for node_id, body in new_bodies.items()}
        mapping: dict[str, Optional[str]] = {}
        for path, quote in quotes.items():
            needle = normalize_quote(quote)
            if not needle:
                mapping[path] = None
                continue
            matches = [node_id for node_id in sorted(normalized) if needle in normalized[node_id]]
            mapping[path] = matches[0] if matches else None
        return mapping
