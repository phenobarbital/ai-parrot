"""Python citations, scope attribution and freshness (FEAT-578 Module 3)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.evidence import (
    build_evidence,
    extract_python_citations,
    sha1_of_span,
    verify_freshness,
)
from parrot.knowledge.wiki.decisions.models import DecisionError, EvidenceRef
from parrot.knowledge.wiki.decisions.parser import parse_adr
from parrot.knowledge.wiki.symbols import sym_concept_id

SOURCE = '''\
# Module-level note: see ADR-42 for the storage choice.
import os


def alpha():
    """Docstring rationale, see ADR/007."""
    # inline comment, ADR 99
    label = "this string mentions ADR-13 but is executable data"
    return label


class Beta:
    def alpha(self):
        """Same method name as the module function — ADR-42 again."""
        return 1
'''


class TestPythonCitations:
    def test_comments_and_docstrings_are_found(self):
        cites, diags = extract_python_citations("pkg/mod.py", SOURCE)
        assert diags == []
        assert {c.alias for c in cites} == {"ADR-42", "ADR-7", "ADR-99"}

    def test_executable_string_is_not_rationale(self):
        """spec §2: a string literal in code is data, never a citation."""
        cites, _ = extract_python_citations("pkg/mod.py", SOURCE)
        assert "ADR-13" not in {c.alias for c in cites}

    def test_module_comment_is_file_scope(self):
        """A module-level comment attaches to the file, not to a symbol."""
        cites, _ = extract_python_citations("pkg/mod.py", SOURCE)
        module_note = next(c for c in cites if c.line == 1)
        assert module_note.qualname is None
        assert module_note.page_id == "file:pkg/mod.py"

    def test_nearest_enclosing_symbol_wins(self):
        """ADR-42 in Beta.alpha's docstring must not attach to module scope."""
        cites, _ = extract_python_citations("pkg/mod.py", SOURCE)
        beta_alpha_cite = next(c for c in cites if c.qualname == "Beta.alpha")
        assert beta_alpha_cite.alias == "ADR-42"
        assert beta_alpha_cite.page_id == sym_concept_id("pkg/mod.py", "Beta.alpha")

    def test_duplicate_symbol_names_stay_distinct(self):
        """Two `alpha`s in one file resolve to two different page_ids (AC2)."""
        cites, _ = extract_python_citations("pkg/mod.py", SOURCE)
        module_alpha = next(c for c in cites if c.qualname == "alpha")
        beta_alpha = next(c for c in cites if c.qualname == "Beta.alpha")
        assert module_alpha.page_id != beta_alpha.page_id

    def test_syntax_error_is_a_diagnostic_not_an_exception(self):
        cites, diags = extract_python_citations("pkg/bad.py", "def (:\n")
        assert cites == []
        assert diags and diags[0].code == "ADR_PARSE_FAILED"

    def test_no_reference_yields_nothing(self):
        assert extract_python_citations("pkg/x.py", "# plain comment\n") == ([], [])


class TestEvidence:
    def test_span_excerpt_and_hash_are_exact(self):
        ref = build_evidence("pkg/mod.py", SOURCE, "file:pkg/mod.py", 1, 1, "comment")
        assert ref.start_line == 1 and ref.end_line == 1
        assert ref.excerpt.startswith("# Module-level note")
        assert ref.source_sha1 == sha1_of_span(ref.excerpt)


class TestFreshness:
    async def test_no_root_is_unverified_never_current(self, tmp_path):
        """spec §2: absent a local root, freshness is unverified."""
        ref = build_evidence("m.py", "a\nb\n", "file:m.py", 1, 1, "code")
        assert (await verify_freshness(None, ref))[0] == "unverified"

    async def test_unchanged_source_is_current(self, tmp_path):
        content = "a\nb\nc\n"
        (tmp_path / "m.py").write_text(content, encoding="utf-8")
        ref = build_evidence("m.py", content, "file:m.py", 1, 2, "code")
        freshness, diagnostic = await verify_freshness(tmp_path, ref)
        assert freshness == "current"
        assert diagnostic is None

    async def test_changed_source_is_stale(self, tmp_path):
        content = "a\nb\nc\n"
        (tmp_path / "m.py").write_text(content, encoding="utf-8")
        ref = build_evidence("m.py", content, "file:m.py", 1, 2, "code")
        (tmp_path / "m.py").write_text("a\nCHANGED\nc\n", encoding="utf-8")
        freshness, diagnostic = await verify_freshness(tmp_path, ref)
        assert freshness == "stale"
        assert diagnostic is not None

    async def test_parsed_adr_sections_are_current_on_disk(self, tmp_path):
        """Every parsed ADR span must verify against the untouched file.

        The last section is the regression: a file ending in a newline used
        to yield an end_line one past the file, so its stored hash could
        never be reproduced and freshness read `stale` forever.
        """
        adr = (
            "---\nid: ADR-7\nstatus: accepted\n---\n\n# ADR-7: Keep it local\n\n"
            "## Context\nOne developer.\n\n## Decision\nUse one local file.\n\n"
            "## Consequences\nA busy timeout handles concurrency.\n"
        )
        (tmp_path / "0007-local.md").write_text(adr, encoding="utf-8")
        record, _ = parse_adr("0007-local.md", adr)
        assert record is not None and record.evidence
        for ref in record.evidence:
            freshness, diagnostic = await verify_freshness(tmp_path, ref)
            assert freshness == "current", f"{ref.start_line}-{ref.end_line}: {diagnostic}"

    async def test_deleted_source_is_missing(self, tmp_path):
        content = "a\nb\n"
        (tmp_path / "m.py").write_text(content, encoding="utf-8")
        ref = build_evidence("m.py", content, "file:m.py", 1, 2, "code")
        (tmp_path / "m.py").unlink()
        freshness, diagnostic = await verify_freshness(tmp_path, ref)
        assert freshness == "missing"
        assert diagnostic is not None

    @pytest.mark.parametrize("bad", ["../escape.py", "/etc/passwd"])
    async def test_path_escape_is_refused(self, tmp_path, bad):
        """Confined paths only (spec §2)."""
        ref = EvidenceRef.model_construct(
            page_id="file:x",
            rel_path=bad,
            start_line=1,
            end_line=1,
            source_sha1="deadbeef",
            excerpt="",
            kind="code",
        )
        with pytest.raises(DecisionError) as exc_info:
            await verify_freshness(tmp_path, ref)
        assert exc_info.value.code == "ADR_PATH_OUTSIDE_ROOT"

    async def test_verification_does_not_mutate(self, tmp_path):
        """Reads never rewrite review status or the record (spec §2)."""
        content = "a\nb\n"
        (tmp_path / "m.py").write_text(content, encoding="utf-8")
        ref = build_evidence("m.py", content, "file:m.py", 1, 2, "code")
        before = ref.model_dump()
        (tmp_path / "m.py").write_text("a\nCHANGED\n", encoding="utf-8")
        await verify_freshness(tmp_path, ref)
        assert ref.model_dump() == before
