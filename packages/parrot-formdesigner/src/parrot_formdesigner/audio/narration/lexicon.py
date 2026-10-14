"""Per-locale lexicon and transcript normalisation for voice forms (FEAT-649)."""

from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_LOCALE = "en"
_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
# Shape whitelist for locale tags used as path components (CWE-22 barrier):
# 2-3 letter primary subtag, then `-`/`_`-separated alphanumeric subtags of 1-8 chars.
_LOCALE_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{1,8})*$")


class SpokenLexicon(BaseModel):
    """Spoken-token tables for typed post-processors (FEAT-653). Keys are pre-folded with ``_strip_text``."""

    units: dict[str, int] = Field(default_factory=dict)
    tens: dict[str, int] = Field(default_factory=dict)
    scales: dict[str, int] = Field(default_factory=dict)
    number_joiners: list[str] = Field(default_factory=list)
    decimal_words: list[str] = Field(default_factory=list)
    minus_words: list[str] = Field(default_factory=list)
    decimal_separator: str = "."
    digit_aliases: dict[str, str] = Field(default_factory=dict)
    repeat_words: dict[str, int] = Field(default_factory=dict)
    plus_words: list[str] = Field(default_factory=list)
    email_symbols: dict[str, str] = Field(default_factory=dict)
    months: dict[str, int] = Field(default_factory=dict)
    weekdays: dict[str, int] = Field(default_factory=dict)
    relative_days: dict[str, int] = Field(default_factory=dict)
    this_words: list[str] = Field(default_factory=list)
    next_words: list[str] = Field(default_factory=list)
    last_words: list[str] = Field(default_factory=list)
    am_words: list[str] = Field(default_factory=list)
    pm_words: list[str] = Field(default_factory=list)
    noon_words: list[str] = Field(default_factory=list)
    midnight_words: list[str] = Field(default_factory=list)
    half_words: list[str] = Field(default_factory=list)
    date_order: Literal["MDY", "DMY"] = "MDY"


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
    spoken: SpokenLexicon = Field(default_factory=SpokenLexicon)


def locale_chain(locale: str) -> list[str]:
    """Fallback chain: ``es-MX`` → ``es`` → ``en`` (deduplicated, order kept).

    Candidates that do not match ``_LOCALE_RE`` are dropped — the chain feeds
    filesystem paths (``<templates>/<candidate>/narration.yaml``), so this is
    the path-injection barrier for every consumer. ``DEFAULT_LOCALE`` is always
    present: a malformed locale yields ``["en"]``.
    """
    chain: list[str] = []
    for candidate in (locale, locale.replace("_", "-").split("-")[0], DEFAULT_LOCALE):
        if candidate and candidate not in chain and _LOCALE_RE.fullmatch(candidate):
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
    base = (templates_dir or TEMPLATES_DIR).resolve()
    for candidate in locale_chain(locale):
        path = (base / candidate / "narration.yaml").resolve()
        if not path.is_relative_to(base):
            raise ValueError(f"Locale {locale!r} resolves outside templates directory")
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

    def _spoken(block: dict[str, Any]) -> SpokenLexicon:
        def words(key: str) -> list[str]:
            return [p for p in (_strip_text(str(v)) for v in (block.get(key) or [])) if p]

        def ints(key: str) -> dict[str, int]:
            return {_strip_text(str(k)): int(v) for k, v in (block.get(key) or {}).items()}

        def strs(key: str) -> dict[str, str]:
            return {_strip_text(str(k)): str(v) for k, v in (block.get(key) or {}).items()}

        return SpokenLexicon(
            units=ints("units"),
            tens=ints("tens"),
            scales=ints("scales"),
            number_joiners=words("number_joiners"),
            decimal_words=words("decimal_words"),
            minus_words=words("minus_words"),
            decimal_separator=str(block.get("decimal_separator") or "."),
            digit_aliases=strs("digit_aliases"),
            repeat_words=ints("repeat_words"),
            plus_words=words("plus_words"),
            email_symbols=strs("email_symbols"),
            months=ints("months"),
            weekdays=ints("weekdays"),
            relative_days=ints("relative_days"),
            this_words=words("this_words"),
            next_words=words("next_words"),
            last_words=words("last_words"),
            am_words=words("am_words"),
            pm_words=words("pm_words"),
            noon_words=words("noon_words"),
            midnight_words=words("midnight_words"),
            half_words=words("half_words"),
            date_order="DMY" if str(block.get("date_order") or "MDY").upper() == "DMY" else "MDY",
        )

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
        spoken=_spoken(raw.get("spoken") or {}),
    )
