"""Contextual embedding header helper.

Builds a deterministic, LLM-free contextual header from a Document's
``metadata['document_meta']`` sub-dict and prepends it to the chunk text
*for embedding only*.  No I/O, no ML dependencies — stdlib + Pydantic.

Spec: FEAT-127 — Metadata-Driven Contextual Embedding Headers.
"""
from __future__ import annotations

from typing import Callable, Union

from parrot.stores.models import Document  # noqa: TCH001

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE: str = (
    "Title: {title} | Section: {section} | Category: {category}\n\n{content}"
)
"""Default template shipped with the feature.

Empty / None fields are collapsed (no orphan pipes).  Override at the store
level via ``contextual_template=`` kwarg.
"""

DEFAULT_MAX_HEADER_TOKENS: int = 100
"""Safety cap: whitespace-tokenised header words, not sub-word tokens."""

KNOWN_PLACEHOLDERS = frozenset({
    "title", "section", "category", "page", "language", "source", "content",
})
"""Recognised template placeholders (informational — not enforced at runtime)."""

ContextualTemplate = Union[str, Callable[[dict], str]]
"""A template is either a ``str`` (format-map style) or a ``Callable`` that
receives the raw ``document_meta`` dict and returns the full embedded text."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _DefaultEmpty(dict):
    """dict that returns ``""`` for any missing key (safe for format_map)."""

    def __missing__(self, key: str) -> str:  # noqa: D105
        return ""


def _sanitise_meta(meta: dict) -> dict:
    """Return a sanitised copy of *meta*.

    Rules:
    - Drop ``None`` values.
    - Drop values that are empty strings after ``str()`` + ``.strip()``.
    - Escape ``{`` → ``{{`` and ``}`` → ``}}`` so metadata values cannot
      break ``str.format_map`` or re-expand template placeholders.
    """
    out: dict[str, str] = {}
    for k, v in meta.items():
        if v is None:
            continue
        try:
            sv = str(v).strip()
        except Exception:  # noqa: BLE001 — defensive; skip uncoerceable values
            continue
        if not sv:
            continue
        out[k] = sv.replace("{", "{{").replace("}", "}}")
    return out


def _collapse_pipes(header: str) -> str:
    """Remove pipe-separated segments whose value is empty.

    Designed for the default ``"Label: {value} | Label: {value}"`` pattern.
    Segments without a ``": "`` separator are kept when non-empty.

    Example::

        _collapse_pipes("Title: A | Section:  | Category: B")
        # → "Title: A | Category: B"
    """
    segments = header.split(" | ")
    non_empty: list[str] = []
    for seg in segments:
        seg_stripped = seg.strip()
        if not seg_stripped:
            continue
        if ": " in seg_stripped:
            _label, _sep, value = seg_stripped.partition(": ")
            if value.strip():
                non_empty.append(seg_stripped)
            # else: empty value — drop
        elif seg_stripped.endswith(":"):
            # "Label:" with no value — drop
            pass
        else:
            # Non-label segment (e.g., custom template fragment) — keep
            if seg_stripped:
                non_empty.append(seg_stripped)
    return " | ".join(non_empty)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_contextual_text(
    document: Document,
    template: ContextualTemplate = DEFAULT_TEMPLATE,
    max_header_tokens: int = DEFAULT_MAX_HEADER_TOKENS,
) -> tuple[str, str]:
    """Build the text that will be embedded plus the header used.

    Reads ``document.metadata['document_meta']`` (canonical, from
    metadata-standardisation).  Renders the template, dropping empty fields
    and collapsing the resulting separators.  Caps the header at
    ``max_header_tokens`` (whitespace-tokenised approximation — no real
    tokeniser dependency; the cap is a safety belt, not an exact limit).

    This function is a pure function: no I/O, no logging, no side-effects.

    Args:
        document: The ``Document`` whose ``page_content`` will be embedded.
        template: A format-map style string (placeholders: title, section,
            category, page, language, source, content) *or* a callable that
            receives the raw ``document_meta`` dict and returns the full text
            to embed.  When using a callable, split the result on the first
            ``"\\n\\n"`` to extract the header.
        max_header_tokens: Approximate upper bound on header length measured
            in whitespace-tokenised words.  Prevents header blow-up for
            documents with extremely long titles.

    Returns:
        A ``(text_to_embed, header)`` tuple where:

        - ``text_to_embed`` is the string to pass to the embedding model.
        - ``header`` is the rendered + cleaned header that was prepended
          (empty string if no usable metadata was found).

    Note:
        ``document.page_content`` is **never mutated**.  Setting
        ``metadata['contextual_header']`` is the caller's responsibility
        (done by ``AbstractStore._apply_contextual_augmentation``).
    """
    # ----------------------------------------------------------------
    # 1. Extract document_meta safely
    # ----------------------------------------------------------------
    meta: dict = {}
    if document.metadata:
        raw = document.metadata.get("document_meta", {})
        if isinstance(raw, dict):
            meta = raw

    content = document.page_content

    # ----------------------------------------------------------------
    # 2. Callable template path
    # ----------------------------------------------------------------
    if callable(template):
        full_text = template(meta)
        if not isinstance(full_text, str):
            full_text = str(full_text)
        if "\n\n" in full_text:
            header, _rest = full_text.split("\n\n", 1)
        else:
            header = full_text
        # Cap header tokens
        header_words = header.split()
        if len(header_words) > max_header_tokens:
            header = " ".join(header_words[:max_header_tokens])
        if not header.strip():
            return (content, "")
        return (full_text, header)

    # ----------------------------------------------------------------
    # 3. String template path
    # ----------------------------------------------------------------
    # Sanitise: drop None/empty, escape braces in values.
    sanitised = _sanitise_meta(meta)
    if not sanitised:
        # No usable metadata fields — pass through unchanged.
        return (content, "")

    # Render the template with content="" to isolate the header portion.
    header_ctx: _DefaultEmpty = _DefaultEmpty(sanitised)
    header_ctx["content"] = ""
    try:
        header_raw = template.format_map(header_ctx)
    except (KeyError, ValueError):
        return (content, "")

    # Strip trailing newlines / whitespace left by the empty {content}.
    header_raw = header_raw.rstrip("\n").strip()

    # Collapse orphan pipe separators.
    header = _collapse_pipes(header_raw).strip()

    # Cap header tokens.
    if header:
        header_words = header.split()
        if len(header_words) > max_header_tokens:
            header = " ".join(header_words[:max_header_tokens])

    if not header:
        return (content, "")

    # ----------------------------------------------------------------
    # 4. Build the text to embed
    # ----------------------------------------------------------------
    # If the template places {content} after a double-newline, reconstruct
    # with the collapsed header so orphan pipes are not embedded.
    # Otherwise use the full rendered template (custom inline layout).
    if "\n\n{content}" in template:
        text_to_embed = header + "\n\n" + content
    else:
        full_ctx: _DefaultEmpty = _DefaultEmpty(sanitised)
        full_ctx["content"] = content
        try:
            text_to_embed = template.format_map(full_ctx)
        except (KeyError, ValueError):
            text_to_embed = header + "\n\n" + content

    return (text_to_embed, header)
