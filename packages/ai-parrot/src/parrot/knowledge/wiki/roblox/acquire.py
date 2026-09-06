"""Explicit async Roblox API acquisition (FEAT-532 TASK-2900).

Owns every network call the Roblox API plane makes — and only those
calls; no local build ever imports this module implicitly. Per the
spec's final §8 owner decisions:

- The official API dump: resolve the current Studio version from
  ``https://setup.rbxcdn.com/versionQTStudio``, then fetch
  ``https://setup.rbxcdn.com/<version>-API-Dump.json``.
- creator-docs prose: resolve the ``Roblox/creator-docs`` ``main`` branch
  commit SHA via one GitHub API call, then fetch **one** SHA-pinned
  ``codeload.github.com`` tarball and extract class YAML files **in
  memory** (``io.BytesIO`` + ``tarfile``, never written to disk). This
  replaced a previously-accepted 625-raw-file-fetch design after
  measurement showed the tarball is both fewer requests (2 vs. 625) and
  a smaller total download (compressed YAML beats 625 separate
  responses) — see ``sdd/specs/wikitoolkit-luau-roblox.spec.md`` §8.

No retries, no backoff, no per-file cache: a transport failure, timeout,
non-2xx status, or malformed identity fails the whole acquisition once
(spec: "Honor section 8: no raw-file fan-out, per-file cache, automatic
retries or backoff"). Publication is TASK-2902's responsibility — nothing
here writes to ``PARROT_HOME`` or any SQLite generation.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import tarfile
from typing import Any

import aiohttp
import yaml
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

STUDIO_VERSION_URL = "https://setup.rbxcdn.com/versionQTStudio"
API_DUMP_URL_TEMPLATE = "https://setup.rbxcdn.com/{version}-API-Dump.json"
CREATOR_DOCS_COMMIT_URL = "https://api.github.com/repos/Roblox/creator-docs/commits/main"
CREATOR_DOCS_TARBALL_URL_TEMPLATE = "https://codeload.github.com/Roblox/creator-docs/tar.gz/{sha}"

#: Bounded response sizes (spec: "bounded response sizes ... request
#: timeouts and limited retries" — retries are zero per §8, but the size
#: and timeout bounds still apply).
MAX_STUDIO_VERSION_BYTES = 256
MAX_DUMP_BYTES = 32 * 1024 * 1024
MAX_TARBALL_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_TARBALL_MEMBERS = 5_000
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0

_STUDIO_VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.\-]{0,63}$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CLASS_YAML_MEMBER_RE = re.compile(r"/content/en-us/reference/engine/classes/([A-Za-z_][A-Za-z0-9_]*)\.yaml$")


class RobloxApiAcquisitionError(Exception):
    """Raised on any acquisition failure: transport, identity, or content."""


class AcquiredApiPayloads(BaseModel):
    """Raw, validated acquisition inputs for one API generation.

    Immutable-generation inputs handed to TASK-2901's renderer; this type
    carries no rendering decisions of its own (join logic, sorting,
    structural-only detection are the renderer's job).

    Attributes:
        studio_version: The resolved Studio version string.
        api_dump: The parsed API dump JSON (``dict``), validated only for
            basic structural sanity (a ``"Classes"`` list is present).
        creator_docs_commit: SHA-pinned commit of ``Roblox/creator-docs``.
        class_docs: Class name -> parsed YAML content, for every dump
            class whose YAML file was present and valid in the tarball.
            A class absent from this mapping is a structural-only class
            (spec: "A missing YAML file for a class is a supported
            structural-only page").
        source_hashes: ``{"api_dump": sha256hex, "creator_docs_tarball":
            sha256hex}`` — content identity for ``--refresh`` comparison.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    studio_version: str
    api_dump: dict[str, Any]
    creator_docs_commit: str
    class_docs: dict[str, Any] = Field(default_factory=dict)
    source_hashes: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Identity resolution
# ---------------------------------------------------------------------------


async def resolve_studio_version(session: aiohttp.ClientSession, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS) -> str:
    """Resolve the current Studio version string.

    Raises:
        RobloxApiAcquisitionError: On any transport failure, non-2xx
            status, oversize response, or a value that fails identity
            validation (never used unvalidated in a subsequent URL).
    """
    text = await _fetch_text(session, STUDIO_VERSION_URL, MAX_STUDIO_VERSION_BYTES, timeout)
    version = text.strip()
    if not _STUDIO_VERSION_RE.match(version):
        raise RobloxApiAcquisitionError(f"invalid Studio version identity: {version!r}")
    return version


async def resolve_creator_docs_commit(
    session: aiohttp.ClientSession, timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS
) -> str:
    """Resolve the ``Roblox/creator-docs`` ``main`` branch commit SHA.

    The single GitHub API call this module makes; its only purpose is to
    pin a version, never used for anything else (spec §8), so it does not
    consume the API's 60 req/h unauthenticated quota beyond this one call.

    Raises:
        RobloxApiAcquisitionError: On failure or an invalid SHA shape.
    """
    payload = await _fetch_json(session, CREATOR_DOCS_COMMIT_URL, MAX_DUMP_BYTES, timeout)
    sha = payload.get("sha") if isinstance(payload, dict) else None
    if not isinstance(sha, str) or not _COMMIT_SHA_RE.match(sha):
        raise RobloxApiAcquisitionError(f"invalid creator-docs commit SHA: {sha!r}")
    return sha


# ---------------------------------------------------------------------------
# API dump
# ---------------------------------------------------------------------------


async def fetch_api_dump(
    session: aiohttp.ClientSession,
    studio_version: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], str]:
    """Fetch and minimally validate the API dump for ``studio_version``.

    Args:
        studio_version: Must already be validated by
            :func:`resolve_studio_version` — re-validated here defensively
            before URL construction.

    Returns:
        ``(dump, sha256_hex)`` — the parsed dump and its raw-bytes content hash.

    Raises:
        RobloxApiAcquisitionError: On invalid identity, transport
            failure, or a dump missing a ``"Classes"`` list.
    """
    if not _STUDIO_VERSION_RE.match(studio_version):
        raise RobloxApiAcquisitionError(f"refusing to build a URL from invalid version: {studio_version!r}")
    url = API_DUMP_URL_TEMPLATE.format(version=studio_version)
    raw = await _fetch_bytes(session, url, MAX_DUMP_BYTES, timeout)
    try:
        import json

        dump = json.loads(raw)
    except ValueError as exc:
        raise RobloxApiAcquisitionError(f"{url}: invalid JSON dump ({exc})") from exc
    if not isinstance(dump, dict) or not isinstance(dump.get("Classes"), list):
        raise RobloxApiAcquisitionError(f"{url}: dump missing a 'Classes' list")
    return dump, hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# creator-docs: SHA-pinned tarball, extracted entirely in memory
# ---------------------------------------------------------------------------


async def fetch_creator_docs_tarball(
    session: aiohttp.ClientSession,
    commit_sha: str,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> tuple[bytes, str]:
    """Fetch the SHA-pinned ``creator-docs`` tarball.

    Args:
        commit_sha: Must already be validated by
            :func:`resolve_creator_docs_commit` — re-validated here
            defensively before URL construction.

    Returns:
        ``(raw_tarball_bytes, sha256_hex)``.

    Raises:
        RobloxApiAcquisitionError: On invalid identity or transport failure.
    """
    if not _COMMIT_SHA_RE.match(commit_sha):
        raise RobloxApiAcquisitionError(f"refusing to build a URL from invalid SHA: {commit_sha!r}")
    url = CREATOR_DOCS_TARBALL_URL_TEMPLATE.format(sha=commit_sha)
    raw = await _fetch_bytes(session, url, MAX_TARBALL_BYTES, timeout)
    return raw, hashlib.sha256(raw).hexdigest()


def extract_class_docs(tarball_bytes: bytes, class_names: set[str]) -> tuple[dict[str, Any], list[str]]:
    """Extract class YAML docs from the tarball, entirely in memory.

    Reads only regular-file members matching
    ``*/content/en-us/reference/engine/classes/<Name>.yaml`` via
    ``TarFile.extractfile`` — never ``extractall``, never writes to disk,
    never follows a symlink/hardlink member (rejected outright), and
    never reads a member whose declared size exceeds
    :data:`MAX_MEMBER_BYTES`. Filters to ``class_names`` (the dump's own
    class set) so documentation for classes the dump does not know about
    is never used to fabricate a page (spec: "Do not generate classes
    solely because documentation mentions them").

    Args:
        tarball_bytes: Raw gzip tarball bytes.
        class_names: Class names the API dump declares — the only names
            this function will ever return docs for.

    Returns:
        ``(class_name -> parsed YAML dict, diagnostics)``. Never raises
        for a per-member problem (unsafe/oversize/malformed member) —
        each is skipped with a diagnostic; only a tarball that cannot be
        opened at all raises.

    Raises:
        RobloxApiAcquisitionError: If the tarball itself cannot be opened
            (corrupt archive, not a gzip tarball, or an archive
            declaring more than :data:`MAX_TARBALL_MEMBERS` members —
            treated as a transport/content failure, not a per-file skip).
    """
    diagnostics: list[str] = []
    docs: dict[str, Any] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tar:
            members = tar.getmembers()
            if len(members) > MAX_TARBALL_MEMBERS:
                raise RobloxApiAcquisitionError(
                    f"tarball declares {len(members)} members, exceeds {MAX_TARBALL_MEMBERS} limit"
                )
            for member in members:
                if not member.isfile():
                    continue  # symlink/hardlink/dir/device — never followed
                if ".." in member.name.split("/"):
                    diagnostics.append(f"{member.name}: path-traversal-shaped member skipped")
                    continue
                match = _CLASS_YAML_MEMBER_RE.search(member.name)
                if match is None:
                    continue
                class_name = match.group(1)
                if class_name not in class_names:
                    continue
                if member.size > MAX_MEMBER_BYTES:
                    diagnostics.append(f"{class_name}.yaml: {member.size} bytes exceeds member limit, skipped")
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    diagnostics.append(f"{class_name}.yaml: could not read member, skipped")
                    continue
                raw = extracted.read(MAX_MEMBER_BYTES + 1)
                if len(raw) > MAX_MEMBER_BYTES:
                    diagnostics.append(f"{class_name}.yaml: actual size exceeds member limit, skipped")
                    continue
                try:
                    parsed = yaml.safe_load(raw)
                except yaml.YAMLError as exc:
                    diagnostics.append(f"{class_name}.yaml: invalid YAML ({exc})")
                    continue
                if parsed is not None:
                    docs[class_name] = parsed
    except tarfile.TarError as exc:
        raise RobloxApiAcquisitionError(f"invalid creator-docs tarball: {exc}") from exc
    return docs, diagnostics


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def acquire_roblox_api_payloads(
    *,
    reuse: AcquiredApiPayloads | None = None,
    http_timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
    session: aiohttp.ClientSession | None = None,
) -> tuple[AcquiredApiPayloads, bool]:
    """Acquire (or reuse) one API generation's inputs.

    Resolves both identities first (Studio version, creator-docs commit —
    2 cheap requests), then compares against ``reuse`` (a previously
    acquired generation's payloads): when both identities are unchanged,
    the expensive dump/tarball fetches are skipped entirely and
    ``reuse`` is returned as-is — "compare is not invalidate; nothing
    caches on a TTL" (spec §8). Otherwise fetches the dump (1 request)
    and the tarball (1 request), for up to 4 total requests on a full
    acquisition.

    Args:
        reuse: A previously acquired generation's payloads, or ``None``
            for a first/forced acquisition.
        http_timeout: Per-request timeout in seconds.
        session: An existing session to use, or ``None`` to create one
            for the duration of this call.

    Returns:
        ``(payloads, reused)`` — ``reused=True`` when the identity
        comparison found nothing changed and made zero additional
        requests beyond the two identity checks.

    Raises:
        RobloxApiAcquisitionError: On any failure. Never partially
            returns — either a complete, validated result or an
            exception; publication (TASK-2902) decides what happens to
            the last good generation on failure, not this function.
    """
    owns_session = session is None
    if owns_session:
        session = aiohttp.ClientSession()
    try:
        studio_version = await resolve_studio_version(session, http_timeout)
        creator_docs_commit = await resolve_creator_docs_commit(session, http_timeout)

        if (
            reuse is not None
            and reuse.studio_version == studio_version
            and reuse.creator_docs_commit == creator_docs_commit
        ):
            logger.info(
                "Roblox API identities unchanged (studio=%s, docs=%s); reusing generation",
                studio_version,
                creator_docs_commit,
            )
            return reuse, True

        api_dump, dump_hash = await fetch_api_dump(session, studio_version, http_timeout)
        class_names = {
            c["Name"] for c in api_dump.get("Classes", []) if isinstance(c, dict) and isinstance(c.get("Name"), str)
        }

        tarball_bytes, tarball_hash = await fetch_creator_docs_tarball(session, creator_docs_commit, http_timeout)
        class_docs, diagnostics = extract_class_docs(tarball_bytes, class_names)
        for diag in diagnostics:
            logger.debug("Roblox API acquisition: %s", diag)

        payloads = AcquiredApiPayloads(
            studio_version=studio_version,
            api_dump=api_dump,
            creator_docs_commit=creator_docs_commit,
            class_docs=class_docs,
            source_hashes={"api_dump": dump_hash, "creator_docs_tarball": tarball_hash},
        )
        return payloads, False
    finally:
        if owns_session:
            await session.close()


# ---------------------------------------------------------------------------
# Bounded HTTP helpers
# ---------------------------------------------------------------------------


async def _fetch_bytes(session: aiohttp.ClientSession, url: str, max_bytes: int, timeout_seconds: float) -> bytes:
    """Stream ``url`` into memory, capped at ``max_bytes``. No retries."""
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with session.get(url, timeout=timeout) as resp:
            if not (200 <= resp.status < 300):
                raise RobloxApiAcquisitionError(f"{url}: HTTP {resp.status}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.content.iter_chunked(65536):
                total += len(chunk)
                if total > max_bytes:
                    raise RobloxApiAcquisitionError(f"{url}: response exceeded {max_bytes} byte limit")
                chunks.append(chunk)
            return b"".join(chunks)
    except (aiohttp.ClientError, TimeoutError) as exc:
        raise RobloxApiAcquisitionError(f"{url}: request failed: {exc}") from exc


async def _fetch_text(session: aiohttp.ClientSession, url: str, max_bytes: int, timeout_seconds: float) -> str:
    raw = await _fetch_bytes(session, url, max_bytes, timeout_seconds)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RobloxApiAcquisitionError(f"{url}: response was not valid UTF-8: {exc}") from exc


async def _fetch_json(session: aiohttp.ClientSession, url: str, max_bytes: int, timeout_seconds: float) -> Any:
    import json

    raw = await _fetch_bytes(session, url, max_bytes, timeout_seconds)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise RobloxApiAcquisitionError(f"{url}: invalid JSON response ({exc})") from exc
