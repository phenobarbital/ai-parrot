"""Executable FEAT-760 design checks; these do not validate production code."""

import logging
import re
from itertools import product

LOGGER = logging.getLogger(__name__)
OLD_WIKI = re.compile(r"\bADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
NEW_WIKI = re.compile(r"\b(?:(?!(?:ADR|RFC)\d{1,5}-)([A-Za-z][A-Za-z0-9]*)-)?ADR[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
OLD_GI = re.compile(r"\b(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
NEW_GI = re.compile(r"\b(?:(?!(?:ADR|RFC)\d{1,5}-)([A-Za-z][A-Za-z0-9]*)-)?(ADR|RFC)[\s\-/]?(\d{1,5})\b", re.IGNORECASE)
FILENAME_RE = re.compile(r"^(?:([A-Za-z][A-Za-z0-9]*)-)?0*(\d+)[-_]")
KNOWN = frozenset({"FS", "PARROT"})
CORPUS = [
    "ADR-42",
    "ADR/042",
    "ADR 42",
    "adr42",
    "FS-ADR-3",
    "parrot-ADR-7",
    "PARROT-adr/007",
    "ADR_42",
    "ADR--42",
    "ADR - 42",
    "see-ADR-3 for why",
    "RFC 4180",
    "FS-RFC-2119",
    'x = "see ADR-42"',
    "# ADR-1: why",
    "ADR-99999",
    "ADR-123456",
    "ADR1-ADR-2",
    "RFC1-ADR-2",
    "ADR1-RFC-2",
    "ADR1-RFC2",
    "FS-ADR1-ADR-2",
]


def canonical(prefix: str | None, kind: str, number: str, known: frozenset[str] | None) -> str:
    """Model the allowlist rule shared by both citation planes."""
    bare = f"{kind.upper()}-{int(number)}"
    if prefix and known and prefix.upper() in known and kind.upper() == "ADR":
        return f"{prefix.upper()}-{bare}"
    return bare


def filename_alias(name: str, known: frozenset[str] | None) -> str | None:
    """Model filename gating, deliberately distinct from prose degradation."""
    match = FILENAME_RE.match(name)
    if match is None:
        return None
    prefix, number = match.groups()
    if prefix and (not known or prefix.upper() not in known):
        return None
    return canonical(prefix, "ADR", number, known)


def lookup(
    alias: str, aliases: dict[str, str], ambiguous: set[str], local: str | None
) -> tuple[str | None, str | None]:
    """Model exact-first resolution with terminal ambiguity at each candidate."""
    candidates = [alias]
    if local and re.fullmatch(r"ADR-\d+", alias):
        candidates.append(f"{local}-{alias}")
    for candidate in candidates:
        if candidate in ambiguous:
            return None, "ADR_REFERENCE_AMBIGUOUS"
        if candidate in aliases:
            return aliases[candidate], None
    return None, "ADR_REFERENCE_MISSING"


def check_citations(text: str) -> None:
    """Assert all-match compatibility and cross-plane spans/labels."""
    wiki_matches = list(NEW_WIKI.finditer(text))
    graph_matches = list(NEW_GI.finditer(text))
    wiki_spans = [(m.span(), (m[1] or "").upper(), int(m[2])) for m in wiki_matches]
    graph_spans = [(m.span(), (m[1] or "").upper(), int(m[3])) for m in graph_matches if m[2].upper() == "ADR"]
    assert wiki_spans == graph_spans, (text, wiki_spans, graph_spans)
    old_graph = [f"{m[1].upper()}-{int(m[2])}" for m in OLD_GI.finditer(text)]
    old_wiki = [f"ADR-{int(m[1])}" for m in OLD_WIKI.finditer(text)]
    for known in (None, frozenset(), KNOWN):
        wiki = [canonical(m[1], "ADR", m[2], known) for m in wiki_matches]
        graph = [canonical(m[1], m[2], m[3], known) for m in graph_matches]
        graph_adr = [canonical(m[1], m[2], m[3], known) for m in graph_matches if m[2].upper() == "ADR"]
        assert wiki == graph_adr, (text, known, wiki, graph_adr)
        assert all(
            canonical(m[1], m[2], m[3], known) == f"RFC-{int(m[3])}" for m in graph_matches if m[2].upper() == "RFC"
        ), text
        if not known:
            assert graph == old_graph, (text, graph, old_graph)
            assert wiki == old_wiki, (text, wiki, old_wiki)


def main() -> None:
    """Fail on a design violation and log deterministic successful coverage."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    atoms = ["ADR1", "RFC1", "ADR-2", "RFC-2", "FS", "PARROT", "see", "ADR99999", "ADR123456"]
    cases = CORPUS + ["-".join(parts) for size in (2, 3) for parts in product(atoms, repeat=size)]
    for text in cases:
        check_citations(text)
    for known in (None, frozenset(), frozenset({"OTHER"})):
        assert filename_alias("fs-0042-topic.md", known) is None
        assert filename_alias("0042-topic.md", known) == "ADR-42"
    assert filename_alias("fs-0042-topic.md", KNOWN) == "FS-ADR-42"
    assert lookup("ADR-7", {}, {"FS-ADR-7"}, "FS") == (None, "ADR_REFERENCE_AMBIGUOUS")
    assert lookup("ADR-7", {"FS-ADR-7": "local"}, {"ADR-7"}, "FS") == (None, "ADR_REFERENCE_AMBIGUOUS")
    assert lookup("ADR-7", {"ADR-7": "bare"}, {"FS-ADR-7"}, "FS") == ("bare", None)
    assert lookup("ADR-7", {"FS-ADR-7": "local"}, set(), "FS") == ("local", None)
    assert lookup("FS-ADR-7", {"ADR-7": "bare"}, set(), "FS") == (None, "ADR_REFERENCE_MISSING")
    unknown = canonical("XX", "ADR", "3", KNOWN)
    assert lookup(unknown, {"ADR-3": "bare", "FS-ADR-3": "local"}, set(), "FS") == ("bare", None)
    assert lookup(unknown, {"FS-ADR-3": "local"}, set(), "FS") == ("local", None)
    reserved = re.compile(r"(?:ADR|RFC)[0-9]{1,5}", re.IGNORECASE)
    assert all(reserved.fullmatch(value) for value in ("ADR1", "adr00001", "RFC2119"))
    assert all(not reserved.fullmatch(value) for value in ("FS", "ADR123456"))
    LOGGER.info("PASS: %d citation cases; filename gating, lookup ambiguity and prefix reservation checks", len(cases))


if __name__ == "__main__":
    main()
