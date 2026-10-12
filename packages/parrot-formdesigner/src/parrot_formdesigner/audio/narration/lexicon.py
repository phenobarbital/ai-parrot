"""Per-locale lexicon and transcript normalisation for voice forms (FEAT-649)."""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_LOCALE = "en"
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


class Lexicon(BaseModel):
    """Locale vocabulary used by the option matcher and command classifier."""

    locale: str
    ordinals: dict[str, int] = Field(default_factory=dict)
    cardinals: dict[str, int] = Field(default_factory=dict)
    yes: list[str] = Field(default_factory=list)
    no: list[str] = Field(default_factory=list)
    all: list[str] = Field(default_factory=list)
    none: list[str] = Field(default_factory=list)
    conjunctions: list[str] = Field(default_factory=list)
    fillers: list[str] = Field(default_factory=list)
    commands: dict[str, list[str]] = Field(default_factory=dict)
    review_confirm: list[str] = Field(default_factory=list)
    review_change: list[str] = Field(default_factory=list)


def locale_chain(locale: str) -> list[str]:
    """Fallback chain: ``es-MX`` → ``es`` → ``en`` (deduplicated, order kept)."""
    chain: list[str] = []
    for candidate in (locale, locale.replace("_", "-").split("-")[0], DEFAULT_LOCALE):
        if candidate and candidate not in chain:
            chain.append(candidate)
    return chain


def load_locale_document(locale: str, *, templates_dir: Path | None = None) -> tuple[str, dict[str, Any]]:
    """Load the first existing ``<dir>/<locale>/narration.yaml`` along the fallback chain.

    Args:
        locale: Requested locale (e.g. ``es-MX``).
        templates_dir: Override of the templates root (defaults to the packaged one).

    Returns:
        ``(resolved_locale, document)``.

    Raises:
        FileNotFoundError: when even ``en`` is missing.
    """
    base = templates_dir or TEMPLATES_DIR
    for candidate in locale_chain(locale):
        path = base / candidate / "narration.yaml"
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return candidate, yaml.safe_load(fh) or {}
    raise FileNotFoundError(f"No narration.yaml for {locale!r} under {base}")


def _strip_text(text: str) -> str:
    """NFKD → drop combining marks → casefold → strip punctuation → collapse spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    cleaned = _PUNCT_RE.sub(" ", no_marks.casefold())
    return _SPACE_RE.sub(" ", cleaned).strip()


def normalize(text: str, lexicon: Lexicon) -> str:
    """Normalise a transcript: accent/case/punctuation folding, then drop whole-word fillers.

    Multi-word fillers (e.g. ``por favor``) are removed as exact whole-word phrases.
    """
    stripped = f" {_strip_text(text)} "
    # Longest phrases first so a multi-word filler wins over its own sub-words.
    for filler in sorted(set(lexicon.fillers), key=len, reverse=True):
        if not filler:
            continue
        needle = f" {filler} "
        while needle in stripped:
            stripped = stripped.replace(needle, " ")
    return _SPACE_RE.sub(" ", stripped).strip()


@lru_cache(maxsize=16)
def load_lexicon(locale: str) -> Lexicon:
    """Return the lexicon for ``locale`` (with fallback), every phrase pre-normalised."""
    resolved, document = load_locale_document(locale)
    raw = document.get("lexicon") or {}

    def _list(key: str) -> list[str]:
        return [p for p in (_strip_text(str(v)) for v in (raw.get(key) or [])) if p]

    def _map(key: str) -> dict[str, int]:
        return {_strip_text(str(k)): int(v) for k, v in (raw.get(key) or {}).items()}

    commands = {
        str(name): [p for p in (_strip_text(str(v)) for v in (phrases or [])) if p]
        for name, phrases in (raw.get("commands") or {}).items()
    }
    return Lexicon(
        locale=resolved,
        ordinals=_map("ordinals"),
        cardinals=_map("cardinals"),
        yes=_list("yes"),
        no=_list("no"),
        all=_list("all"),
        none=_list("none"),
        conjunctions=_list("conjunctions"),
        fillers=_list("fillers"),
        commands=commands,
        review_confirm=_list("review_confirm"),
        review_change=_list("review_change"),
    )
