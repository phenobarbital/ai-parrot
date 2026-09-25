"""Figure extraction, deterministic pairing, vision captioning and storage (FEAT-601 M6)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from pydantic import BaseModel

from parrot.knowledge.manuals.models import Callout, CalloutLink, CalloutMap, MediaLink, MediaRef, PartRef
from parrot.knowledge.pageindex.pdf_to_markdown import PageImage, extract_page_images

if TYPE_CHECKING:  # pragma: no cover
    from parrot.knowledge.manuals.carding import StepDraft

logger = logging.getLogger(__name__)

CAPTION_RE = re.compile(r"^\s*(?:Figure|Figura|Fig\.?)\s*([\dA-Z][\dA-Z\-\.]*)\s*[:.\-–]?\s*(.*)$", re.I | re.M)
CAPTION_PROMPT = "Describe this technical figure in one or two factual sentences. Context: {context}"


class CaptioningUnavailable(RuntimeError):
    """No vision-capable client is configured."""


class MediaUnavailable(RuntimeError):
    """A storage backend cannot produce an http(s) URL for a media key."""


class FigureCandidate(BaseModel):
    """One extracted image plus its (optional) printed caption."""

    image: PageImage
    label: str | None = None
    caption_text: str | None = None
    caption_distance: float | None = None
    vision_caption: str | None = None


def _normalize_label(text: str) -> str:
    """Normalize a figure label/citation to a bare, comparable key.

    Strips an optional ``Fig./Figure/Figura`` prefix (present on printed
    captions but not necessarily on step citations) and normalizes case and
    surrounding punctuation so both sides of the pairing use the same key.

    Args:
        text: A raw caption match (e.g. ``"1"``) or a raw citation (e.g.
            ``"Fig. 1"`` or ``"1"``).

    Returns:
        The normalized label key.
    """
    stripped = text.strip()
    match = CAPTION_RE.match(stripped)
    body = match.group(1) if match else stripped
    return body.strip().strip(".:-").upper()


def _media_id(image: PageImage) -> str:
    """Derive a stable media id shared by :func:`pair_figures` and :func:`upload_figures`.

    Args:
        image: The extracted page image.

    Returns:
        A 16-character hex id. Includes page/index alongside the image's
        own sha256 so two visually-identical images (same bytes) placed on
        different pages never collide on ``media_id``.
    """
    digest = hashlib.sha256(f"{image.sha256}:{image.page}:{image.index}".encode("utf-8")).hexdigest()
    return digest[:16]


def extract_figures(pdf_path: Path, work_dir: Path, *, page_texts: Mapping[int, str]) -> list[FigureCandidate]:
    """Extract page images and pair each with the caption printed directly below it.

    Pairing is deterministic and text-order based: on each page, the Nth
    extracted image is paired with the Nth ``CAPTION_RE`` match found in
    that page's text (both already in document/reading order). A page with
    fewer captions than images leaves the surplus images uncaptioned
    (``label=None``) rather than guessing.

    Args:
        pdf_path: Source PDF.
        work_dir: Directory extracted PNGs are written to.
        page_texts: Physical page number (1-based) to page text/markdown.

    Returns:
        One :class:`FigureCandidate` per extracted image, in (page, index)
        order.
    """
    images = extract_page_images(pdf_path, work_dir)
    per_page_matches: dict[int, list[re.Match[str]]] = {}
    for image in images:
        if image.page in per_page_matches:
            continue
        text = page_texts.get(image.page, "") or ""
        per_page_matches[image.page] = list(CAPTION_RE.finditer(text))

    consumed: dict[int, int] = {}
    candidates: list[FigureCandidate] = []
    for image in images:
        matches = per_page_matches.get(image.page, [])
        offset = consumed.get(image.page, 0)
        label: str | None = None
        caption_text: str | None = None
        if offset < len(matches):
            match = matches[offset]
            consumed[image.page] = offset + 1
            label = _normalize_label(match.group(1))
            caption_text = match.group(2).strip() or None
        candidates.append(FigureCandidate(image=image, label=label, caption_text=caption_text))
    return candidates


def pair_figures(
    steps: Sequence["StepDraft"],
    figures: Sequence[FigureCandidate],
    *,
    page_of_step: Mapping[int, int],
) -> list[tuple[int, MediaLink]]:
    """Pair steps with figures: label ⇒ primary/1.0; uncaptioned same-page closest ⇒ secondary (scaled).

    Rules (G1 / spec M6):
        1. A step citing a label that matches a captioned figure gets a
           ``primary`` link at ``confidence=1.0``.
        2. An uncaptioned figure is paired to the closest step on the same
           page (by within-page ordinal distance, since only page-level
           position is known), with ``role="secondary"`` and confidence
           scaled into ``(0, 0.9]`` — never a nearest-*page* guess promoted
           to ``primary``.
        3. A step citing a label that no figure carries yields **no**
           link — it is reported by :func:`unpaired_references` instead.
        4. A captioned figure that no step cites is never force-linked.

    Args:
        steps: Ordered step drafts, each exposing ``.figure_refs``.
        figures: Extracted figure candidates.
        page_of_step: Step index (0-based, matching ``steps``) to physical
            page number.

    Returns:
        ``(step_index, MediaLink)`` pairs, in no particular order.
    """
    labelled: dict[str, FigureCandidate] = {}
    for fig in figures:
        if fig.label:
            labelled.setdefault(_normalize_label(fig.label), fig)

    links: list[tuple[int, MediaLink]] = []
    claimed: set[str] = set()
    for step_index, step in enumerate(steps):
        for ref in getattr(step, "figure_refs", None) or []:
            key = _normalize_label(ref)
            fig = labelled.get(key)
            if fig is None:
                continue
            claimed.add(key)
            links.append(
                (step_index, MediaLink(media_id=_media_id(fig.image), role="primary", confidence=1.0, origin="manual"))
            )

    # Within-page ordinal of each step, in document order (only reliable
    # position signal available for steps: page_of_step carries no
    # sub-page coordinate).
    page_counts: dict[int, int] = {}
    step_ordinal: dict[int, int] = {}
    for step_index in range(len(steps)):
        page = page_of_step.get(step_index)
        if page is None:
            continue
        ordinal = page_counts.get(page, 0)
        step_ordinal[step_index] = ordinal
        page_counts[page] = ordinal + 1

    for fig in figures:
        if fig.label:
            # Captioned figures are only linked when a step cites them (above).
            continue
        same_page_steps = [
            step_index
            for step_index, page in page_of_step.items()
            if page == fig.image.page and step_index < len(steps)
        ]
        if not same_page_steps:
            continue
        best_step = min(same_page_steps, key=lambda idx: abs(step_ordinal.get(idx, 0) - fig.image.index))
        distance = abs(step_ordinal.get(best_step, 0) - fig.image.index)
        confidence = round(0.9 / (1 + distance), 4)
        links.append(
            (
                best_step,
                MediaLink(media_id=_media_id(fig.image), role="secondary", confidence=confidence, origin="manual"),
            )
        )
    return links


def unpaired_references(steps: Sequence["StepDraft"], figures: Sequence[FigureCandidate]) -> list[str]:
    """Figure labels cited by steps that no extracted figure carries (verification-queue items).

    Args:
        steps: Ordered step drafts, each exposing ``.figure_refs``.
        figures: Extracted figure candidates.

    Returns:
        Sorted, normalized labels cited by at least one step but not
        matched by any figure's own label.
    """
    known_labels = {_normalize_label(fig.label) for fig in figures if fig.label}
    cited: set[str] = set()
    for step in steps:
        for ref in getattr(step, "figure_refs", None) or []:
            cited.add(_normalize_label(ref))
    return sorted(cited - known_labels)


class VisionCaptioner(Protocol):
    """Anything that can caption one image file."""

    async def caption(self, image: Path, *, context: str) -> str: ...


class _AskToImageCaptioner:
    """Adapter over a provider client's ``ask_to_image`` (Path input only)."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def caption(self, image: Path, *, context: str) -> str:
        try:
            msg = await self._client.ask_to_image(CAPTION_PROMPT.format(context=context), image)
        except NotImplementedError as exc:
            raise CaptioningUnavailable(str(exc)) from exc
        text = getattr(msg, "response", None)
        if not text:
            text = getattr(msg, "output", None)
        return str(text or "").strip()


def resolve_captioner(client: Any) -> VisionCaptioner:
    """Resolve a captioner by capability (Q3); raise CaptioningUnavailable when absent.

    Checks the most definitive signal first: ``ClaudeAgentClient`` *does*
    define an ``ask_to_image`` method, but it unconditionally raises
    ``NotImplementedError`` (``claude_agent.py:1036-1040``) — a plain
    ``hasattr`` check would wrongly treat it as capable. Only once that
    definitive exclusion is ruled out do we fall back to generic duck
    typing for every other client shape.

    Args:
        client: Candidate LLM client.

    Returns:
        A :class:`VisionCaptioner` wrapping ``client``.

    Raises:
        CaptioningUnavailable: ``client`` is ``None``, is a
            ``ClaudeAgentClient``, or has no ``ask_to_image`` method.
    """
    if client is None:
        raise CaptioningUnavailable("no vision client configured")
    if type(client).__name__ == "ClaudeAgentClient":
        raise CaptioningUnavailable("ClaudeAgentClient does not implement ask_to_image")
    if not callable(getattr(client, "ask_to_image", None)):
        raise CaptioningUnavailable(f"{type(client).__name__} has no ask_to_image capability")
    return _AskToImageCaptioner(client)


async def caption_figures(
    figures: Sequence[FigureCandidate], captioner: VisionCaptioner, *, concurrency: int = 4
) -> list[FigureCandidate]:
    """Caption every figure once, bounded by a semaphore; failures leave vision_caption None.

    Args:
        figures: Figures to caption.
        captioner: Resolved vision captioner.
        concurrency: Maximum number of concurrent captioning calls.

    Returns:
        A new list of :class:`FigureCandidate`, each with ``vision_caption``
        set on success. On a per-figure error the original candidate is
        kept unchanged (``vision_caption=None``) and the failure is logged.

    Raises:
        CaptioningUnavailable: Propagated (not swallowed) since it signals
            the captioner itself is unusable, not a one-off figure issue.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _caption_one(fig: FigureCandidate) -> FigureCandidate:
        context = fig.caption_text or fig.label or ""
        async with sem:
            try:
                caption = await captioner.caption(fig.image.path, context=context)
            except CaptioningUnavailable:
                raise
            except Exception as exc:  # noqa: BLE001 - best-effort per-figure captioning
                logger.warning("Captioning failed for figure on page %s: %s", fig.image.page, exc)
                return fig
        return fig.model_copy(update={"vision_caption": caption or None})

    return list(await asyncio.gather(*(_caption_one(fig) for fig in figures)))


async def upload_figures(figures: Sequence[FigureCandidate], fm: Any, *, prefix: str) -> list[MediaRef]:
    """Upload each figure through FileManagerInterface.upload_file and return MediaRefs keyed by storage key.

    Args:
        figures: Figures to upload (already captioned, if desired).
        fm: A ``FileManagerInterface``-shaped file manager.
        prefix: Destination key prefix (e.g. ``"manuals/<manual_id>"``).

    Returns:
        One :class:`MediaRef` per figure. ``storage_key`` is always set and
        is never an http(s) URL (AC13/G4) — presigning happens separately
        via :func:`presign`.
    """
    refs: list[MediaRef] = []
    for fig in figures:
        destination = f"{prefix}/{fig.image.sha256}.png"
        await fm.upload_file(fig.image.path, destination)
        refs.append(
            MediaRef(
                media_id=_media_id(fig.image),
                kind="figure",
                storage_key=destination,
                page=fig.image.page,
                bbox=fig.image.bbox,
                sha256=fig.image.sha256,
                caption=fig.vision_caption or fig.caption_text,
                label=fig.label,
            )
        )
    return refs


async def presign(fm: Any, storage_key: str, *, expiry: int = 900) -> str:
    """Mint a short-lived URL; raise MediaUnavailable unless it is http(s).

    Args:
        fm: A ``FileManagerInterface``-shaped file manager.
        storage_key: The stored object's key (as persisted on ``MediaRef``).
        expiry: Seconds the presigned URL should remain valid.

    Returns:
        The http(s) presigned URL.

    Raises:
        MediaUnavailable: The backend returned anything other than an
            http(s) URL (e.g. ``LocalFileManager``'s ``file://``).
    """
    url = await fm.get_file_url(storage_key, expiry=expiry)
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise MediaUnavailable(f"storage backend returned a non-http URL for {storage_key!r}")
    return url


CALLOUTS_ENABLED_ENV = "PARROT_MANUALS_CALLOUTS"
CALLOUT_PROMPT = (
    "This is an exploded-view technical figure. List every numbered callout: its label exactly as printed, "
    "a short description of the part it points to, and the part number if printed. Context: {context}"
)
CALLOUT_TOKEN_RE = re.compile(r"\d+")
PART_SIMILARITY_THRESHOLD = 0.85


def callouts_enabled() -> bool:
    """Whether the callout pass is switched on (flipped once spike 1 passes — AC21).

    Returns:
        True when ``PARROT_MANUALS_CALLOUTS`` is set to a truthy value.
    """
    return os.environ.get(CALLOUTS_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes"}


def _similarity(left: str, right: str) -> float:
    """Normalized fuzzy similarity in ``[0, 1]`` (copy of contracts/carding.py:812-836).

    ``manuals`` must not import ``contracts`` (M1 boundary), so the body is
    duplicated here rather than imported.

    Args:
        left: First string.
        right: Second string.

    Returns:
        ``rapidfuzz.fuzz.token_sort_ratio`` divided by 100. Identical
        normalized strings score exactly ``1.0``; empty input scores ``0.0``.

    Raises:
        RuntimeError: When the approved ``rapidfuzz`` extra is missing.
    """
    if not (left or "").strip() or not (right or "").strip():
        return 0.0
    if left == right:
        return 1.0
    try:
        from rapidfuzz import fuzz  # noqa: PLC0415 - optional dependency
    except ImportError as exc:  # pragma: no cover - depends on install extras
        raise RuntimeError(
            "Contract parent resolution requires rapidfuzz. Install it with " "`pip install 'ai-parrot[graphindex]'`."
        ) from exc
    return float(fuzz.token_sort_ratio(left, right)) / 100.0


class CalloutMapper(Protocol):
    """Anything that can map the callouts of one exploded view."""

    async def map_callouts(self, image: Path, *, context: str) -> CalloutMap: ...


class _AskToImageCalloutMapper:
    """Adapter over a provider client's ``ask_to_image`` structured-output path."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def map_callouts(self, image: Path, *, context: str) -> CalloutMap:
        try:
            msg = await self._client.ask_to_image(
                CALLOUT_PROMPT.format(context=context), image, structured_output=CalloutMap
            )
        except NotImplementedError as exc:
            raise CaptioningUnavailable(str(exc)) from exc
        parsed = getattr(msg, "structured_output", None)
        if isinstance(parsed, CalloutMap):
            return parsed
        if isinstance(parsed, dict):
            try:
                return CalloutMap.model_validate(parsed)
            except Exception:  # noqa: BLE001 - malformed structured output falls back to empty
                logger.warning("map_callouts: could not parse structured output %r", parsed)
                return CalloutMap(callouts=[])
        return CalloutMap(callouts=[])


def resolve_callout_mapper(client: Any) -> CalloutMapper:
    """Capability-resolved callout mapper; same rule as :func:`resolve_captioner`.

    Reuses :func:`resolve_captioner`'s capability checks (definitive
    ``ClaudeAgentClient`` exclusion before generic duck typing) so both
    passes agree on what counts as a vision-capable client.

    Args:
        client: Candidate LLM client.

    Returns:
        A :class:`CalloutMapper` wrapping ``client``.

    Raises:
        CaptioningUnavailable: ``client`` is not vision-capable (same
            conditions as :func:`resolve_captioner`).
    """
    resolve_captioner(client)
    return _AskToImageCalloutMapper(client)


def is_exploded_view(figure: FigureCandidate, steps: Sequence["StepDraft"]) -> bool:
    """True when caption text or citing-step evidence mentions >= 2 callout numbers.

    Args:
        figure: The candidate figure.
        steps: Ordered step drafts, each exposing ``.figure_refs`` and,
            optionally, ``.callout_mentions``.

    Returns:
        True when at least 2 distinct callout numbers are attested by the
        figure's own caption or by a step that cites this figure's label.
    """
    tokens: set[str] = set(CALLOUT_TOKEN_RE.findall(figure.caption_text or ""))
    if figure.label:
        key = _normalize_label(figure.label)
        for step in steps:
            refs = getattr(step, "figure_refs", None) or []
            if not any(_normalize_label(ref) == key for ref in refs):
                continue
            mentions = getattr(step, "callout_mentions", None) or []
            tokens.update(str(mention) for mention in mentions)
    return len(tokens) >= 2


def _resolve_part(callout: Callout, parts: Sequence[PartRef]) -> tuple[str, float] | None:
    """Resolve one callout to a part: exact part number, else best-name similarity.

    Args:
        callout: The vision-proposed callout.
        parts: Candidate parts.

    Returns:
        ``(part_id, confidence)`` when resolved, else ``None``.
    """
    if callout.part_number:
        target = callout.part_number.strip().casefold()
        for part in parts:
            if part.part_number and part.part_number.strip().casefold() == target:
                return part.part_id, 1.0
    best_part_id: str | None = None
    best_score = 0.0
    for part in parts:
        name = part.name.value or ""
        score = _similarity(callout.description, name)
        if score > best_score:
            best_score = score
            best_part_id = part.part_id
    if best_part_id is not None and best_score >= PART_SIMILARITY_THRESHOLD:
        return best_part_id, best_score
    return None


async def map_callouts(
    figures: Sequence[FigureCandidate],
    mapper: CalloutMapper,
    *,
    parts: Sequence[PartRef],
    steps: Sequence["StepDraft"],
    media_ids: Mapping[str, str] | None = None,
    enabled: bool | None = None,
) -> tuple[list[CalloutLink], list[Callout]]:
    """One structured call per exploded view; resolve label -> Part; return (links, unresolved).

    Args:
        figures: Extracted figure candidates.
        mapper: Resolved callout mapper (see :func:`resolve_callout_mapper`).
        parts: Candidate parts a callout label may resolve to.
        steps: Ordered step drafts, used by :func:`is_exploded_view`.
        media_ids: Optional explicit ``sha256 -> media_id`` mapping; falls
            back to the image's own truncated sha256 when absent.
        enabled: Explicit override for :func:`callouts_enabled` (tests/spikes).

    Returns:
        ``(links, unresolved)``: resolved :class:`CalloutLink` entries and
        the :class:`Callout` entries that could not be resolved to a part
        (never guessed into a link — AC21).
    """
    if not (callouts_enabled() if enabled is None else enabled):
        logger.debug("map_callouts: disabled (set %s once spike 1 passes)", CALLOUTS_ENABLED_ENV)
        return [], []
    links: list[CalloutLink] = []
    unresolved: list[Callout] = []
    for fig in figures:
        if not is_exploded_view(fig, steps):
            continue
        media_id = (media_ids or {}).get(fig.image.sha256) or fig.image.sha256[:16]
        context = fig.caption_text or fig.label or ""
        callout_map = await mapper.map_callouts(fig.image.path, context=context)
        for callout in callout_map.callouts:
            resolved = _resolve_part(callout, parts)
            if resolved is None:
                unresolved.append(callout)
                continue
            part_id, confidence = resolved
            links.append(
                CalloutLink(
                    media_id=media_id,
                    part_id=part_id,
                    callout=callout.label,
                    confidence=confidence,
                    origin="vision",
                )
            )
    return links, unresolved
