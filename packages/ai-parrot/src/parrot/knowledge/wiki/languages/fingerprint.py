"""Extractor fingerprint: which tier + rule file produced a plane's symbols (FEAT-609 M2).

A plane stores this under the meta key ``extractor_fingerprint``. When a language's
entry changes — ast-grep installed or removed, a rule file edited — ``build`` re-ingests
that language's files once, instead of trusting per-file staleness, which cannot see a
change in the extractor.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from parrot.knowledge.wiki.languages import all_scanners
from parrot.knowledge.wiki.store import BaseWikiStore

logger = logging.getLogger(__name__)

META_KEY = "extractor_fingerprint"
_RULES_DIR = Path(__file__).parent / "rules"
_RULE_FILES: dict[str, str | None] = {
    "javascript": "typescript.yaml",
    "php": "php.yaml",
    "rust": "rust.yaml",
    "perl": "perl.yaml",
    "python": "python.yaml",
    "luau": None,
}
_NON_STRUCTURAL = frozenset({"python", "luau"})


class ExtractorFingerprint(BaseModel):
    """Per-language identity of what produced a plane's symbols.

    Attributes:
        schema_version: Layout version of this payload.
        languages: Scanner name -> ``"<mode>:<sha1(rule file)|none>"``.
    """

    schema_version: int = 1
    languages: dict[str, str] = Field(default_factory=dict)


def _rule_hash(scanner_name: str) -> str:
    """SHA-1 of the scanner's rule file, or ``"none"`` when it has none."""
    rule_file = _RULE_FILES.get(scanner_name)
    if rule_file is None:
        return "none"
    path = _RULES_DIR / rule_file
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return "none"


def current_fingerprint() -> ExtractorFingerprint:
    """Fingerprint of the scanners as installed in this process."""
    return ExtractorFingerprint(
        languages={name: f"{scanner.mode}:{_rule_hash(name)}" for name, scanner in all_scanners().items()}
    )


def changed_languages(old: ExtractorFingerprint | None, new: ExtractorFingerprint) -> set[str]:
    """Scanner names whose entry differs; every structural-capable one when ``old`` is None."""
    if old is None:
        return {name for name in new.languages if name not in _NON_STRUCTURAL}
    return {name for name, entry in new.languages.items() if old.languages.get(name) != entry}


async def load_fingerprint(store: BaseWikiStore) -> ExtractorFingerprint | None:
    """Stored fingerprint, or ``None`` when absent/unparseable/unsupported. Never raises."""
    try:
        raw = await store.get_meta(META_KEY)
    except NotImplementedError:
        return None
    except Exception as exc:  # noqa: BLE001 - an unreadable fingerprint means "unknown"
        logger.debug("load_fingerprint failed: %s", exc)
        return None
    if not raw:
        return None
    try:
        return ExtractorFingerprint.model_validate_json(raw)
    except ValidationError:
        return None


async def save_fingerprint(store: BaseWikiStore, fp: ExtractorFingerprint) -> None:
    """Persist ``fp``; a backend without meta support is skipped, not an error."""
    try:
        await store.set_meta(META_KEY, fp.model_dump_json())
    except NotImplementedError:
        logger.debug("%s has no meta support; extractor fingerprint not saved", type(store).__name__)
