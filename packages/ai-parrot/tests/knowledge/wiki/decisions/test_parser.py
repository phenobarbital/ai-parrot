"""ADR parser fixture matrix (FEAT-578 Module 3, AC1)."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.parser import normalize_adr_alias, parse_adr, resolve_status, split_sections

ACCEPTED = """\
---
id: ADR-42
title: Use pgvector
status: Accepted
---

# ADR-42: Use pgvector

## Context
Postgres is already deployed.

## Decision
Use pgvector as the primary vector store.

## Consequences
One less service to run.
"""


class TestSections:
    def test_adr_sections_and_status(self):
        """A well-formed ADR yields every section with a 1-based span."""
        record, diags = parse_adr("docs/adr/0042-pgvector.md", ACCEPTED)
        assert record is not None and diags == []
        assert record.origin == "documented"
        assert record.source_status == "accepted"
        assert record.external_id == "ADR-42"
        assert "pgvector as the primary" in record.decision
        decision_refs = [ref for ref in record.evidence if ref.excerpt.startswith("Use pgvector")]
        assert len(decision_refs) == 1
        assert decision_refs[0].start_line == 13
        assert decision_refs[0].end_line == 14

    def test_fenced_headings_are_not_sections(self):
        """A fenced example must not fabricate a Decision (spec §2)."""
        text = ACCEPTED.replace("## Decision\n", "```md\n## Decision\nfake\n```\n\n## Decision\n")
        record, diags = parse_adr("docs/adr/0042-pgvector.md", text)
        assert record is not None
        assert "fake" not in record.decision
        assert "pgvector as the primary" in record.decision

    def test_missing_decision_is_an_ordinary_document(self):
        """No Decision section -> (None, diagnostic), never a fabricated ADR."""
        record, diags = parse_adr("docs/adr/notes.md", "# Notes\n\n## Context\nhi\n")
        assert record is None
        assert diags and diags[0].code == "ADR_PARSE_FAILED"

    def test_crlf_input_keeps_correct_spans(self):
        """Windows line endings must not shift the reported lines."""
        lf_record, _ = parse_adr("docs/adr/0042-pgvector.md", ACCEPTED)
        crlf_record, _ = parse_adr("docs/adr/0042-pgvector.md", ACCEPTED.replace("\n", "\r\n"))
        assert crlf_record is not None and lf_record is not None
        lf_decision = next(ref for ref in lf_record.evidence if ref.excerpt.startswith("Use pgvector"))
        crlf_decision = next(ref for ref in crlf_record.evidence if ref.excerpt.startswith("Use pgvector"))
        assert (crlf_decision.start_line, crlf_decision.end_line) == (lf_decision.start_line, lf_decision.end_line)
        assert crlf_record.decision == lf_record.decision


class TestStatus:
    @pytest.mark.parametrize(
        "fm,section,expected",
        [
            ("Accepted", "", "accepted"),
            ("", "Superseded by ADR-50", "superseded"),
            ("Proposed", "", "proposed"),
            ("", "Draft-ish", "unknown"),
        ],
    )
    def test_recognised_and_unknown_statuses(self, fm, section, expected):
        status, raw, diags = resolve_status(fm, section)
        assert status == expected
        assert not diags

    def test_conflicting_status_is_unknown_with_a_diagnostic(self):
        """Disagreement is reported, never resolved by precedence (spec §2)."""
        status, raw, diags = resolve_status("Accepted", "Rejected")
        assert status == "unknown"
        assert [d.code for d in diags] == ["ADR_STATUS_CONFLICT"]

    def test_unknown_status_preserves_raw_text(self):
        """AC3: unknown is displayed, not elevated."""
        text = "---\nid: ADR-3\nstatus: Needs review\n---\n\n## Decision\nDo it.\n"
        record, diags = parse_adr("docs/adr/0003-thing.md", text)
        assert record is not None
        assert record.source_status == "unknown"
        assert record.source_status_raw == "Needs review"


class TestIdentity:
    @pytest.mark.parametrize("text", ["ADR-42", "ADR/042", "ADR 42", "adr42"])
    def test_alias_normalization(self, text):
        """Consistent with GraphIndex's normalization (spec §2)."""
        assert normalize_adr_alias(text) == "ADR-42"

    @pytest.mark.parametrize("text", ["ADR_42", "ADR--42", "ADR - 42"])
    def test_separators_graphindex_rejects_are_not_references(self, text):
        """The two planes must agree on what counts as a citation (spec §2).

        GraphIndex allows exactly one optional separator from ``[\\s\\-/]``
        (graphindex/extractors/code.py:35); widening it here would make the
        wiki resolve references GraphIndex never saw.
        """
        assert normalize_adr_alias(text) is None

    def test_filename_supplies_the_alias_when_absent(self):
        """`0042-*.md` normalizes to ADR-42."""
        text = "# My Decision\n\n## Decision\nDo the thing.\n"
        record, diags = parse_adr("docs/adr/0042-thing.md", text)
        assert record is not None
        assert record.external_id == "ADR-42"
        assert not any(d.code == "ADR_PARSE_FAILED" and "conflicting" in d.message for d in diags)

    def test_conflicting_ids_produce_a_diagnostic(self):
        """frontmatter id vs filename disagreement is reported (spec §2)."""
        text = "---\nid: ADR-7\n---\n\n# Something\n\n## Decision\nDo it.\n"
        record, diags = parse_adr("docs/adr/0042-x.md", text)
        assert record is not None
        assert any(d.code == "ADR_PARSE_FAILED" and "conflicting" in d.message.lower() for d in diags)


class TestBoundedParsing:
    def test_long_adr_not_body_truncated(self):
        """AC1: a Decision past 16000 chars is still extracted with real spans."""
        filler = "\n".join(f"padding line {i}" for i in range(3000))
        text = f"# ADR-9\n\n## Context\n{filler}\n\n## Decision\nUse the bounded parser.\n"
        record, _ = parse_adr("docs/adr/0009-long.md", text)
        assert record is not None
        assert record.decision.strip() == "Use the bounded parser."
        decision_ref = next(ref for ref in record.evidence if ref.kind == "adr" and "bounded parser" in ref.excerpt)
        assert decision_ref.start_line > 3000

    def test_malformed_frontmatter_is_survivable(self):
        """A bad header yields a diagnostic, not a dropped ADR."""
        text = (
            "---\n"
            "id: ADR-15\n"
            "nested:\n"
            "  sub: oops\n"
            "status: Accepted\n"
            "---\n"
            "\n"
            "## Decision\n"
            "Ship it.\n"
        )
        record, diags = parse_adr("docs/adr/0015-thing.md", text)
        assert record is not None
        assert record.decision.strip() == "Ship it."
        assert any(d.code == "ADR_PARSE_FAILED" for d in diags)

    def test_nested_yaml_is_not_evaluated(self):
        """Only flat scalars are read (spec §2)."""
        text = (
            "---\n"
            "id: ADR-16\n"
            "meta: !!python/object:os.system\n"
            "nested:\n"
            "  key: value\n"
            "status: Accepted\n"
            "---\n"
            "\n"
            "## Decision\n"
            "Do it.\n"
        )
        record, diags = parse_adr("docs/adr/0016-thing.md", text)
        assert record is not None
        dumped = record.model_dump_json()
        assert "python/object" not in dumped
        assert "os.system" not in dumped
