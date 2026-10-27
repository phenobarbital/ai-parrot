"""Cross-plane ADR lexical parity and configured-label compatibility."""
from __future__ import annotations

import pytest

from parrot.knowledge.graphindex.extractors.code import _CITATION_RE, CodeExtractor
from parrot.knowledge.wiki.decisions.parser import ADR_REFERENCE_RE, normalize_adr_alias


def test_lexical_parity_wiki_vs_graphindex(parity_corpus: list[str]) -> None:
    """Compare all ADR match spans and extracted prefix/number pairs."""
    for text in parity_corpus:
        wiki_matches = [
            (match.span(), (match.group(1).upper() if match.group(1) else None, int(match.group(2))))
            for match in ADR_REFERENCE_RE.finditer(text)
        ]
        graphindex_matches = [
            (match.span(), (match.group(1).upper() if match.group(1) else None, int(match.group(3))))
            for match in _CITATION_RE.finditer(text)
            if match.group(2).upper() == "ADR"
        ]

        assert graphindex_matches == wiki_matches, text


@pytest.mark.asyncio
async def test_graphindex_allowlist_matches_wiki_labels(parity_corpus: list[str]) -> None:
    """Configured extraction agrees with wiki labels without losing RFCs."""
    compact_references = {
        "ADR1-ADR-2": {"ADR-1", "ADR-2"},
        "RFC1-ADR-2": {"RFC-1", "ADR-2"},
        "ADR1-RFC-2": {"ADR-1", "RFC-2"},
        "ADR1-RFC2": {"ADR-1", "RFC-2"},
        "FS-ADR1-ADR-2": {"ADR-1", "ADR-2"},
    }
    allowlists = (None, frozenset(), frozenset({"FS"}), frozenset({"FS", "PARROT"}))

    for known_prefixes in allowlists:
        extractor = CodeExtractor(known_prefixes=known_prefixes)
        for index, text in enumerate(parity_corpus):
            source = f'# {text}\ndef parity_case_{index}():\n    """{text}"""\n    pass\n'
            nodes, _ = await extractor.extract("parity.py", source)
            citations = [node for node in nodes if node.domain_tags.get("tag") == "CITATION"]
            actual_adr_labels = {
                node.title for node in citations if node.domain_tags.get("citation_kind") == "ADR"
            }
            expected_adr_labels = {
                normalize_adr_alias(match.group(0), known_prefixes)
                for match in ADR_REFERENCE_RE.finditer(text)
            }
            actual_rfc_labels = {
                node.title for node in citations if node.domain_tags.get("citation_kind") == "RFC"
            }
            expected_rfc_labels = {
                f"RFC-{int(match.group(3))}"
                for match in _CITATION_RE.finditer(text)
                if match.group(2).upper() == "RFC"
            }

            assert actual_adr_labels == expected_adr_labels, (known_prefixes, text)
            assert actual_rfc_labels == expected_rfc_labels, (known_prefixes, text)
            if known_prefixes is None and text in compact_references:
                assert actual_adr_labels | actual_rfc_labels == compact_references[text]

    nodes, _ = await CodeExtractor(known_prefixes=frozenset({"FS", "PARROT"})).extract(
        "literal.py", 'VALUE = "see ADR-42"\n'
    )
    assert not [node for node in nodes if node.domain_tags.get("tag") == "CITATION"]
