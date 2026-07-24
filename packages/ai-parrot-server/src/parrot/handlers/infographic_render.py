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
from io import BytesIO
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

import pandas as pd
import pyarrow  # noqa: F401  (declared dependency — TASK-1892; required by pd.read_parquet)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from parrot.tools import SectionDescriptor

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
)
