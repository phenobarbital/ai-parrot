"""Request/response models and dataset decoding for the deterministic
infographic render endpoint (FEAT-327, Module 2).

``InfographicTalk`` (``handlers/infographic.py``, TASK-1890) dispatches the
bot-less ``POST /api/v1/agents/infographic/render`` branch through the
helpers defined here:

- :class:`InlineDataset` / :class:`RenderRequest` / :class:`RenderResponse` /
  :class:`RenderJob` — the Pydantic models carried over the wire (spec §2
  Data Models). ``RenderRequest.descriptor`` embeds the FEAT-326
  :class:`~parrot.tools.infographic_sections.SectionDescriptor` by import —
  it is never redefined here.
- :func:`decode_inline_datasets` — decodes ``records``/``split`` inline
  payloads (plain JSON request) into ``{name: DataFrame}``.
- :func:`parse_multipart_render_request` — decodes a multipart body (one
  ``request`` JSON part + ``dataset:<name>`` parquet/CSV parts) into a
  ``RenderRequest`` plus ``{name: DataFrame}``, enforcing a running total
  body-size cap BEFORE any oversized part is fully buffered.

Malformed input raises :class:`RenderPayloadError` (maps to ``400`` in the
route, naming the offending part); exceeding the size cap raises
:class:`RenderBodyTooLargeError` (maps to ``413``). Both mappings happen in
the route (TASK-1890) — this module only decodes and raises.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

import pandas as pd
import pyarrow  # noqa: F401  (declared dependency — TASK-1892; required by pd.read_parquet)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parrot.tools import AdhocDatasetAdapter, SectionDescriptor
from parrot.tools.infographic_sections import (
    validate_descriptor_datasets,
    validate_payload_shape,
)
from parrot.tools.infographic_toolkit import (
    InfographicToolkit,
    InfographicValidationError,
    _json_safe_default,
)
from parrot.storage.artifacts import ArtifactStore
from parrot.storage.models import Artifact, ArtifactCreator, ArtifactType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Default total body-size cap (bytes) for the render endpoint. Mirrors the
#: module-constant convention used by ``handlers/datasets.py`` (``MAX_FILE_SIZE``).
#: The route (TASK-1890) may override this per-call; it is NOT wired to
#: ``parrot.conf`` in this task (out of this task's file scope).
DEFAULT_MAX_BODY_SIZE = 50 * 1024 * 1024  # 50 MB

#: Multipart part-name prefix identifying a dataset part, e.g. ``dataset:revenue``.
_DATASET_PART_PREFIX = "dataset:"

#: Name of the single JSON part carrying the ``RenderRequest`` body.
_REQUEST_PART_NAME = "request"

_MULTIPART_CHUNK_SIZE = 65536


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class RenderPayloadError(Exception):
    """A request part is malformed — the route maps this to HTTP 400.

    Attributes:
        part_name: The offending part's name (``"request"`` or
            ``"dataset:<name>"``), surfaced in the 400 response.
    """

    def __init__(self, part_name: str, message: str) -> None:
        self.part_name = part_name
        super().__init__(f"{part_name}: {message}")


class RenderBodyTooLargeError(Exception):
    """The running total body size exceeded the configured cap.

    The route maps this to HTTP 413. Raised BEFORE the offending chunk is
    appended to the in-memory buffer — the cap is enforced pre-buffering.
    """


# ---------------------------------------------------------------------------
# Data models (spec §2 Data Models)
# ---------------------------------------------------------------------------

class InlineDataset(BaseModel):
    """One dataset transported inline in the JSON body.

    Attributes:
        orient: ``"records"`` (list of row dicts) or ``"split"``
            (``{"columns": [...], "data": [...], "index": [...]}``, pandas
            ``split`` orientation; ``index`` optional).
        data: The inline payload, shaped per ``orient``.
    """

    model_config = ConfigDict(extra="forbid")

    orient: Literal["records", "split"]
    data: Any


class RenderRequest(BaseModel):
    """Body of ``POST /render`` (JSON body, or the ``request`` multipart part).

    Attributes:
        datasets: alias -> :class:`InlineDataset`, or ``None`` when the
            dataset is instead hydrated from a multipart part named
            ``dataset:<alias>``.
        template: Pre-registered template name ONLY (no inline template HTML).
        descriptor: The FEAT-326 :class:`SectionDescriptor` — imported, never
            redefined.
        theme: Optional registered theme name.
        marker_id: Data-splice marker ``id`` (ignored for jinja mode).
        agent_id: Attribution; system default applied when absent.
        session_id: Attribution; system default applied when absent.
        persist: Whether to persist the render as an artifact (awaited).
        public: When ``True``, also publish under ``STATIC_DIR`` (two-behavior
            URL rule; resolved in spec §2).
        async_: ``async`` in the wire payload (Python keyword-safe alias).
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    datasets: Dict[str, Optional[InlineDataset]]
    template: str
    descriptor: SectionDescriptor
    theme: Optional[str] = None
    marker_id: str = "report-data"
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    persist: bool = True
    public: bool = False
    async_: bool = Field(default=False, alias="async")


class RenderResponse(BaseModel):
    """``application/json`` response for a completed render.

    Attributes:
        artifact_id: Identifier of the persisted artifact.
        url: Resolved URL per the two-behavior rule, or ``None`` when neither
            ``public`` publication nor S3 presigning applies (retrieval then
            goes through the artifacts handler).
        template: The template name used.
        sections_validated: Number of descriptor sections that passed the gate.
        persisted: Whether persistence succeeded.
        timings: Named stage timings, in seconds.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    url: Optional[str]
    template: str
    sections_validated: int
    persisted: bool
    timings: Dict[str, float]


class RenderJob(BaseModel):
    """Redis-stored job record (1-day TTL on terminal states; TASK-1891).

    Attributes:
        job_id: ``uuid4`` job identifier.
        status: Current job status.
        result: Populated when ``status == "done"``.
        error: Populated when ``status == "failed"``.
        created_at: ISO-8601 creation timestamp.
        deadline: ISO-8601 max-runtime watchdog deadline.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["pending", "running", "done", "failed"]
    result: Optional[RenderResponse] = None
    error: Optional[dict] = None
    created_at: str
    deadline: str


# ---------------------------------------------------------------------------
# Inline (JSON) dataset decoding
# ---------------------------------------------------------------------------

def decode_inline_datasets(request: RenderRequest) -> Dict[str, pd.DataFrame]:
    """Decode every inline dataset declared on ``request`` into a DataFrame.

    Entries whose value is ``None`` are skipped — they are expected to be
    hydrated from a multipart ``dataset:<name>`` part instead (see
    :func:`parse_multipart_render_request`).

    Args:
        request: The parsed ``RenderRequest``.

    Returns:
        A ``{name: DataFrame}`` mapping for every non-``None`` entry.

    Raises:
        RenderPayloadError: A dataset's inline payload does not match its
            declared ``orient``.
    """
    frames: Dict[str, pd.DataFrame] = {}
    for name, dataset in request.datasets.items():
        if dataset is None:
            continue
        frames[name] = _decode_inline_dataset(name, dataset)
    return frames


def _decode_inline_dataset(name: str, dataset: InlineDataset) -> pd.DataFrame:
    """Decode a single inline dataset, raising :class:`RenderPayloadError` on shape mismatches."""
    try:
        if dataset.orient == "records":
            if not isinstance(dataset.data, list):
                raise ValueError("'records' orientation requires a list of row objects")
            return pd.DataFrame.from_records(dataset.data)

        # orient == "split"
        if not isinstance(dataset.data, Mapping):
            raise ValueError(
                "'split' orientation requires a mapping with 'columns' and 'data'"
            )
        columns = dataset.data.get("columns")
        rows = dataset.data.get("data")
        if columns is None or rows is None:
            raise ValueError("'split' orientation requires 'columns' and 'data' keys")
        df = pd.DataFrame(data=rows, columns=columns)
        index = dataset.data.get("index")
        if index is not None:
            df.index = index
        return df
    except RenderPayloadError:
        raise
    except Exception as exc:
        raise RenderPayloadError(
            name, f"malformed '{dataset.orient}' dataset: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Multipart decoding (parquet / CSV parts), with pre-buffering size cap
# ---------------------------------------------------------------------------

async def parse_multipart_render_request(
    reader: Any,
    *,
    max_body_size: int = DEFAULT_MAX_BODY_SIZE,
) -> Tuple[RenderRequest, Dict[str, pd.DataFrame]]:
    """Parse a multipart render body into a ``RenderRequest`` + decoded frames.

    Expects exactly one JSON part named ``"request"`` and zero-or-more
    dataset parts named ``"dataset:<name>"`` (parquet, dtype-preserving via
    ``pyarrow``, or CSV — selected by ``Content-Type``/filename). Enforces
    ``max_body_size`` as a running total across every part read from the
    stream: a part that would push the total over the cap is aborted
    mid-read (never fully buffered) and raises :class:`RenderBodyTooLargeError`.

    Args:
        reader: An aiohttp multipart reader (``await request.multipart()``),
            yielding ``BodyPartReader`` parts.
        max_body_size: Cap, in bytes, on the summed size of every part read.

    Returns:
        The parsed ``RenderRequest`` and a ``{name: DataFrame}`` mapping
        decoded from the ``dataset:<name>`` parts (inline-only datasets are
        NOT decoded here — call :func:`decode_inline_datasets` for those).

    Raises:
        RenderPayloadError: The ``request`` part is missing/malformed, a
            dataset part fails to decode, or a dataset declared with
            ``data: null`` in the JSON has no matching multipart part.
        RenderBodyTooLargeError: The running total exceeds ``max_body_size``.
    """
    request_model: Optional[RenderRequest] = None
    frames: Dict[str, pd.DataFrame] = {}
    consumed = 0

    async for field in reader:
        name = field.name or ""
        data, consumed = await _read_capped_field(field, max_body_size, consumed)

        if name == _REQUEST_PART_NAME:
            request_model = _decode_request_part(data)
        elif name.startswith(_DATASET_PART_PREFIX):
            dataset_name = name[len(_DATASET_PART_PREFIX):]
            content_type = field.headers.get("Content-Type") if field.headers else None
            frames[dataset_name] = await _decode_dataset_part(
                dataset_name, data, content_type=content_type, filename=field.filename
            )
        else:
            logger.debug("Ignoring unrecognised multipart part: %r", name)

    if request_model is None:
        raise RenderPayloadError(_REQUEST_PART_NAME, "missing 'request' JSON part")

    _verify_declared_parts_present(request_model, frames)
    return request_model, frames


async def _read_capped_field(
    field: Any,
    max_body_size: int,
    consumed_so_far: int,
    *,
    chunk_size: int = _MULTIPART_CHUNK_SIZE,
) -> Tuple[bytes, int]:
    """Read one multipart field's full content, enforcing the running cap.

    Reads in ``chunk_size`` increments via ``field.read_chunk()`` and stops
    (raising) as soon as the running total would exceed ``max_body_size`` —
    the offending chunk is never appended, so the buffer never grows past
    the cap.

    Args:
        field: A ``BodyPartReader`` (aiohttp multipart part).
        max_body_size: Cap, in bytes, on the summed size of every part.
        consumed_so_far: Bytes already consumed by prior parts.

    Returns:
        A tuple of ``(field_bytes, new_consumed_total)``.

    Raises:
        RenderBodyTooLargeError: The running total would exceed ``max_body_size``.
    """
    buf = bytearray()
    total = consumed_so_far
    while True:
        chunk = await field.read_chunk(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_body_size:
            raise RenderBodyTooLargeError(
                f"request body exceeds the {max_body_size} byte cap"
            )
        buf.extend(chunk)
    return bytes(buf), total


def _decode_request_part(data: bytes) -> RenderRequest:
    """Decode+validate the ``request`` multipart part's JSON body."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RenderPayloadError(_REQUEST_PART_NAME, f"invalid JSON: {exc}") from exc
    try:
        return RenderRequest.model_validate(payload)
    except ValidationError as exc:
        raise RenderPayloadError(_REQUEST_PART_NAME, str(exc)) from exc


def _looks_like_parquet(content_type: Optional[str], filename: Optional[str]) -> bool:
    """Return True when a dataset part should be decoded as Parquet."""
    if content_type and "parquet" in content_type.lower():
        return True
    if filename and filename.lower().endswith(".parquet"):
        return True
    return False


def _decode_parquet_bytes(data: bytes) -> pd.DataFrame:
    """Decode Parquet bytes into a DataFrame (dtype-preserving via ``pyarrow``)."""
    return pd.read_parquet(BytesIO(data), engine="pyarrow")


def _decode_csv_bytes(data: bytes) -> pd.DataFrame:
    """Decode CSV bytes into a DataFrame."""
    return pd.read_csv(BytesIO(data))


async def _decode_dataset_part(
    name: str,
    data: bytes,
    *,
    content_type: Optional[str],
    filename: Optional[str],
) -> pd.DataFrame:
    """Decode one ``dataset:<name>`` multipart part off the event loop.

    Parquet/CSV decoding is CPU-bound blocking work — it runs via
    ``loop.run_in_executor`` so it never blocks the aiohttp worker.

    Args:
        name: The dataset alias (part name with the ``dataset:`` prefix stripped).
        data: The part's raw bytes.
        content_type: The part's ``Content-Type`` header value, if any.
        filename: The part's filename, if any.

    Returns:
        The decoded DataFrame.

    Raises:
        RenderPayloadError: The part's content cannot be decoded.
    """
    loop = asyncio.get_running_loop()
    part_label = f"{_DATASET_PART_PREFIX}{name}"
    try:
        if _looks_like_parquet(content_type, filename):
            return await loop.run_in_executor(None, _decode_parquet_bytes, data)
        return await loop.run_in_executor(None, _decode_csv_bytes, data)
    except Exception as exc:
        raise RenderPayloadError(part_label, f"malformed part: {exc}") from exc


def _verify_declared_parts_present(
    request: RenderRequest, frames: Mapping[str, pd.DataFrame]
) -> None:
    """Ensure every ``datasets`` entry declared as ``None`` has a matching part.

    A dataset alias that is neither inline nor backed by ANY dataset at all
    (inline or multipart) is a downstream FEAT-326 validation-gate concern
    (422) — but a declared ``None`` entry with NO matching multipart part is
    a transport-level error (400) raised here.

    Args:
        request: The parsed ``RenderRequest``.
        frames: The dataset parts successfully decoded from the multipart body.

    Raises:
        RenderPayloadError: A ``None``-valued dataset entry has no matching
            ``dataset:<name>`` part.
    """
    missing: List[str] = [
        name
        for name, dataset in request.datasets.items()
        if dataset is None and name not in frames
    ]
    for name in missing:
        raise RenderPayloadError(
            f"{_DATASET_PART_PREFIX}{name}",
            "declared dataset part not found in multipart body",
        )


# ---------------------------------------------------------------------------
# Payload assembly + URL two-behavior rule (FEAT-327, Module 3)
# ---------------------------------------------------------------------------

def assemble_section_payload(
    descriptor: SectionDescriptor, frames: Mapping[str, pd.DataFrame]
) -> Dict[str, Any]:
    """Assemble a data-splice/jinja payload dict from validated section datasets.

    For each section with a non-empty ``datasets`` list, builds the
    ``target``'s value from its dataset — restricted to ``columns[alias]``
    when given (else every column) — shaped per ``section.shape``:

    - ``"records"``: list of row dicts (``DataFrame.to_dict("records")``).
    - ``"table"``: list of row lists (``DataFrame.values.tolist()``).
    - ``"mapping"``: the first row as a ``{column: value}`` dict.
    - ``"scalar"``: the first row's first column value.

    Sections with an empty ``datasets`` list are skipped (their value is
    expected to come from ``descriptor.params`` or caller-side composition
    upstream — nothing to assemble here).

    **v1 scope note**: a section naming MORE THAN ONE dataset alias needs a
    bespoke transformer (how to combine them is not generically defined) —
    the generic assembler here supports exactly one dataset per section and
    raises :class:`RenderPayloadError` naming the section otherwise, rather
    than guessing a combination strategy.

    Args:
        descriptor: The section descriptor driving assembly.
        frames: ``{name: DataFrame}`` — every alias referenced by a
            single-dataset section MUST already be present (the FEAT-326
            validation gate is expected to have run first).

    Returns:
        The assembled payload dict, keyed per each section's ``target``.

    Raises:
        RenderPayloadError: A section names more than one dataset, or has
            no rows available for a ``"mapping"``/``"scalar"`` shape.
    """
    payload: Dict[str, Any] = {}
    for section in descriptor.sections:
        if not section.datasets:
            continue
        if len(section.datasets) > 1:
            raise RenderPayloadError(
                section.name,
                "sections referencing more than one dataset require a "
                "custom transformer; the generic v1 assembler supports "
                "exactly one dataset per section",
            )
        alias = section.datasets[0]
        df = frames[alias]
        columns = section.columns.get(alias) or list(df.columns)
        value = _shape_dataframe(df[columns], section.shape, section_name=section.name)
        _assign_target(payload, section.target, value)
    return payload


def _shape_dataframe(view: pd.DataFrame, shape: str, *, section_name: str) -> Any:
    """Shape a column-restricted DataFrame view per a section's declared ``shape``."""
    if shape == "records":
        return view.to_dict(orient="records")
    if shape == "table":
        return view.values.tolist()
    if shape == "mapping":
        if view.empty:
            raise RenderPayloadError(
                section_name, "no rows available to assemble a 'mapping' section"
            )
        return view.iloc[0].to_dict()
    if shape == "scalar":
        if view.empty or view.shape[1] == 0:
            raise RenderPayloadError(
                section_name, "no value available to assemble a 'scalar' section"
            )
        cell = view.iloc[0, 0]
        return cell.item() if hasattr(cell, "item") else cell
    raise RenderPayloadError(section_name, f"unsupported shape '{shape}'")


def _assign_target(payload: Dict[str, Any], target: str, value: Any) -> None:
    """Assign ``value`` at ``target`` (JSON pointer or plain key) within ``payload``.

    Mirrors :func:`parrot.tools.infographic_sections._resolve_target`'s
    pointer syntax, but WRITES rather than reads.
    """
    if target.startswith("/"):
        tokens = [
            tok.replace("~1", "/").replace("~0", "~")
            for tok in target.lstrip("/").split("/")
        ]
        node = payload
        for tok in tokens[:-1]:
            node = node.setdefault(tok, {})
        node[tokens[-1]] = value
    else:
        payload[target] = value


async def publish_to_static_dir(html: str, artifact_id: str) -> str:
    """Write ``html`` under ``STATIC_DIR`` and return its ``/static/`` URL.

    The filename is server-generated from ``artifact_id`` (never a
    caller-controlled path segment) — sanitisation is inherent since
    ``artifact_id`` is always produced by :func:`uuid.uuid4`. The write runs
    via ``loop.run_in_executor`` (blocking file I/O off the event loop).

    Args:
        html: The rendered HTML to publish.
        artifact_id: The artifact identifier backing the filename.

    Returns:
        The relative ``/static/<filename>`` URL (served by the app's
        ``add_static("/static/", ...)`` route — ``navigator``'s
        ``AppHandler`` with ``staticdir=STATIC_DIR``).
    """
    from parrot.conf import STATIC_DIR  # local import: keep module import-light

    filename = f"infographic-{artifact_id}.html"
    path = STATIC_DIR / filename

    def _write() -> None:
        STATIC_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write)
    return f"/static/{filename}"


async def resolve_response_url(
    *,
    html: str,
    public: bool,
    artifact_store: Optional[ArtifactStore],
    user_id: str,
    agent_id: str,
    session_id: str,
    artifact_id: str,
) -> Optional[str]:
    """Resolve the response ``url`` per the two-behavior rule (spec §2 Overview).

    - ``public=True`` → publish ``html`` under ``STATIC_DIR`` and return the
      static URL (irreversible-ish: the file remains until cleaned up).
    - ``public=False`` → try :meth:`ArtifactStore.get_public_url` (S3
      presigned, ALWAYS — infographics are never hosted on public S3); on
      ``KeyError``/``ValueError`` (inline artifact, local backend, or the
      artifact was never persisted), return ``None`` — retrieval then goes
      through the artifacts handler.

    Args:
        html: The rendered HTML (needed only for the ``public=True`` branch).
        public: The request's ``public`` flag.
        artifact_store: The configured store, or ``None`` when the artifact
            was not persisted (``persist=False``) — the presigned branch is
            skipped in that case (nothing to presign).
        user_id: Owning user (storage scope).
        agent_id: Producing agent (storage scope).
        session_id: Owning session (storage scope).
        artifact_id: The artifact identifier.

    Returns:
        The resolved URL, or ``None``.
    """
    if public:
        return await publish_to_static_dir(html, artifact_id)
    if artifact_store is None:
        return None
    try:
        return await artifact_store.get_public_url(user_id, agent_id, session_id, artifact_id)
    except (KeyError, ValueError):
        return None


@dataclass
class RenderOutcome:
    """Result of :func:`render_deterministic` — everything the route needs.

    Attributes:
        html: The rendered HTML (spliced or Jinja-rendered).
        artifact_id: Server-generated artifact identifier (always present,
            even when ``persisted=False`` — nothing is stored under it then).
        url: Resolved per the two-behavior rule; ``None`` when neither
            applies (local, non-public, or not persisted).
        persisted: Whether the artifact was actually saved.
        sections_validated: Number of descriptor sections that passed the gate.
        timings: Named stage timings, in seconds.
    """

    html: str
    artifact_id: str
    url: Optional[str]
    persisted: bool
    sections_validated: int
    timings: Dict[str, float] = dataclass_field(default_factory=dict)


async def render_deterministic(
    parsed: RenderRequest,
    frames: Mapping[str, pd.DataFrame],
    *,
    toolkit: InfographicToolkit,
    artifact_store: Optional[ArtifactStore],
    user_id: str,
    agent_id: str,
    session_id: str,
) -> RenderOutcome:
    """Validate, render, and (conditionally) persist a ``RenderRequest``.

    Runs the FEAT-326 gate (via :class:`AdhocDatasetAdapter`) BEFORE any
    render/persist step, assembles the section payload, renders through the
    ``toolkit``'s low-level primitives (bypassing
    ``render_data_template``/``render_template``'s UNCONDITIONAL internal
    persistence — see the module docstring note below) so that ``persist``
    and the caller's own ``user_id``/``agent_id``/``session_id`` attribution
    are both honored exactly, then resolves the response URL.

    Deliberately bypasses ``InfographicToolkit.render_data_template`` /
    ``render_template``: both persist unconditionally under a `_bot`-scope-
    derived (or ``"_anon"``, when bot-less) identity, with no ``persist``
    switch — incompatible with this endpoint's caller-supplied attribution
    and optional persistence. Instead this function uses the toolkit's own
    lower-level, persist-free primitives (``_template_engine`` +
    ``InfographicToolkit._splice_payload`` for data-splice mode;
    ``_template_engine.render`` for jinja mode — the exact same calls
    ``render_data_template``/``render_template`` make internally, per the
    spec's own §6 Codebase Contract, which explicitly lists
    ``_splice_payload`` as a verified signature) and persists directly via
    ``ArtifactStore.save_artifact`` with this call's own scope.

    Args:
        parsed: The parsed ``RenderRequest``.
        frames: ``{name: DataFrame}`` — every dataset referenced by the
            descriptor (inline + multipart, already decoded).
        toolkit: The server-owned ``InfographicToolkit`` instance.
        artifact_store: The configured store, or ``None`` (persistence is
            then skipped regardless of ``parsed.persist``).
        user_id: Attribution — from the authenticated session.
        agent_id: Attribution — from the request body, or a system default.
        session_id: Attribution — from the request body, or a system default.

    Returns:
        The :class:`RenderOutcome`.

    Raises:
        InfographicValidationError: Aggregated dataset/shape deficits
            (``sections_unmet`` / ``payload_shape_mismatch``), or
            ``TEMPLATE_UNKNOWN``/``TEMPLATE_ENGINE_UNSET`` when the toolkit's
            OWN template registry does not know ``parsed.template`` (a
            registry-configuration gap — see module docstring).
        RenderPayloadError: The section assembler could not build the payload.
    """
    timings: Dict[str, float] = {}
    loop = asyncio.get_running_loop()

    t0 = loop.time()
    adapter = AdhocDatasetAdapter(frames=frames)
    validate_descriptor_datasets(parsed.descriptor, adapter)
    timings["validate_datasets"] = loop.time() - t0

    t1 = loop.time()
    payload = assemble_section_payload(parsed.descriptor, frames)
    validate_payload_shape(parsed.descriptor, payload)
    timings["assemble_and_validate_shape"] = loop.time() - t1

    t2 = loop.time()
    if parsed.descriptor.mode == "data-splice":
        html = await _splice_html(toolkit, parsed, payload)
    else:
        html = await _jinja_html(toolkit, parsed, payload)
    timings["render"] = loop.time() - t2

    artifact_id = f"infographic-{uuid.uuid4().hex[:12]}"
    t3 = loop.time()
    persisted = False
    if parsed.persist and artifact_store is not None:
        await _persist_render(
            artifact_store,
            artifact_id=artifact_id,
            html=html,
            template_name=parsed.template,
            theme=parsed.theme,
            user_id=user_id,
            agent_id=agent_id,
            session_id=session_id,
        )
        persisted = True
    timings["persist"] = loop.time() - t3

    t4 = loop.time()
    url = await resolve_response_url(
        html=html,
        public=parsed.public,
        artifact_store=artifact_store if persisted else None,
        user_id=user_id,
        agent_id=agent_id,
        session_id=session_id,
        artifact_id=artifact_id,
    )
    timings["resolve_url"] = loop.time() - t4

    return RenderOutcome(
        html=html,
        artifact_id=artifact_id,
        url=url,
        persisted=persisted,
        sections_validated=len(parsed.descriptor.sections),
        timings=timings,
    )


async def _splice_html(
    toolkit: InfographicToolkit, parsed: RenderRequest, payload: Dict[str, Any]
) -> str:
    """Render data-splice HTML via the toolkit's low-level splice primitive.

    Mirrors ``InfographicToolkit.render_data_template``'s own internals
    (template-source load + ``_splice_payload``) WITHOUT its unconditional
    auto-persist.

    Raises:
        InfographicValidationError: ``TEMPLATE_ENGINE_UNSET`` /
            ``TEMPLATE_UNKNOWN`` when the toolkit's Jinja env has no source
            for ``parsed.template``.
    """
    engine = toolkit._template_engine  # noqa: SLF001 — documented in spec §6 Codebase Contract
    if engine is None:
        raise InfographicValidationError(
            "TEMPLATE_ENGINE_UNSET",
            {"detail": "No HTML templates configured on the server-owned toolkit."},
        )
    try:
        source, _, _ = engine.env.loader.get_source(engine.env, parsed.template)
    except Exception as exc:  # noqa: BLE001 — TemplateNotFound and friends
        raise InfographicValidationError(
            "TEMPLATE_UNKNOWN", {"template_name": parsed.template}
        ) from exc

    try:
        payload_json = json.dumps(
            payload, allow_nan=False, default=_json_safe_default
        )
    except (ValueError, TypeError) as exc:
        raise InfographicValidationError(
            "PAYLOAD_NOT_SERIALIZABLE", {"error": str(exc)}
        ) from exc
    payload_json = (
        payload_json.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    # RenderRequest.descriptor is REQUIRED (unlike the tool-level API's
    # Optional[SectionDescriptor]) — its splice_marker_id ALWAYS governs,
    # exactly mirroring render_data_template's own documented behavior.
    marker_id = parsed.descriptor.splice_marker_id
    return InfographicToolkit._splice_payload(source, payload_json, marker_id)  # noqa: SLF001


async def _jinja_html(
    toolkit: InfographicToolkit, parsed: RenderRequest, payload: Dict[str, Any]
) -> str:
    """Render Jinja HTML via the toolkit's template engine, without auto-persist.

    Raises:
        InfographicValidationError: ``TEMPLATE_ENGINE_UNSET`` /
            ``TEMPLATE_UNKNOWN`` when no source is configured, or
            ``TEMPLATE_RENDER_ERROR`` on a Jinja render failure.
    """
    engine = toolkit._template_engine  # noqa: SLF001 — documented in spec §6 Codebase Contract
    if engine is None:
        raise InfographicValidationError(
            "TEMPLATE_ENGINE_UNSET",
            {"detail": "No HTML templates configured on the server-owned toolkit."},
        )
    try:
        engine.get_template(parsed.template)
    except FileNotFoundError as exc:
        raise InfographicValidationError(
            "TEMPLATE_UNKNOWN", {"template_name": parsed.template}
        ) from exc

    context = {
        "data": payload,
        "message": {},
        "meta": {},
        "theme": parsed.theme,
        "title": None,
        "now": datetime.now(timezone.utc),
    }
    try:
        return await engine.render(parsed.template, context)
    except (ValueError, RuntimeError) as exc:
        raise InfographicValidationError(
            "TEMPLATE_RENDER_ERROR", {"template_name": parsed.template, "error": str(exc)}
        ) from exc


async def _persist_render(
    artifact_store: ArtifactStore,
    *,
    artifact_id: str,
    html: str,
    template_name: str,
    theme: Optional[str],
    user_id: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Persist a rendered infographic, mirroring ``InfographicToolkit._persist_template``'s
    artifact shape (same ``definition`` keys) but with THIS call's own attribution."""
    now = datetime.now(timezone.utc)
    artifact = Artifact(
        artifact_id=artifact_id,
        artifact_type=ArtifactType.INFOGRAPHIC,
        title=f"Infographic — {template_name}",
        created_at=now,
        updated_at=now,
        created_by=ArtifactCreator.AGENT,
        definition={
            "html": html,
            "template": template_name,
            "theme": theme,
            "js_bundles": [],
        },
    )
    await artifact_store.save_artifact(user_id, agent_id, session_id, artifact)


__all__ = (
    "DEFAULT_MAX_BODY_SIZE",
    "RenderPayloadError",
    "RenderBodyTooLargeError",
    "InlineDataset",
    "RenderRequest",
    "RenderResponse",
    "RenderJob",
    "decode_inline_datasets",
    "parse_multipart_render_request",
    "assemble_section_payload",
    "publish_to_static_dir",
    "resolve_response_url",
    "RenderOutcome",
    "render_deterministic",
)
