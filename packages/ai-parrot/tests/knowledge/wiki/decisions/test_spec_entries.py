"""FEAT-784 M2 — spec Decisions block parser."""

from __future__ import annotations

import pytest

from parrot.knowledge.wiki.decisions.models import (
    SPEC_BLOCK_INVALID_YAML,
    SPEC_BLOCK_MISSING,
    SPEC_DANGLING_REF,
    SPEC_DUPLICATE_ENTRY_ID,
    SPEC_EMPTY_ABOUT,
    SPEC_EMPTY_TARGETS,
    SPEC_INVALID_ID,
    SPEC_UNKNOWN_FIELD,
)
from parrot.knowledge.wiki.decisions.spec_entries import (
    SEED_HEADING,
    canonical_block_bytes,
    entries_to_records,
    extract_block,
    parse_spec_decisions,
)

FENCE = "`" * 3
GOOD = f'''# Spec

## Decisions

{FENCE}yaml
schema_version: 1
document_id: feat-784
entries:
  - id: one
    statement: Clients never persist history.
    relation: forbids
    about: [clients, memory]
    targets: [dir:packages/ai-parrot/src/parrot/clients]
  - id: two
    statement: Bots own history.
    relation: requires
    about: [memory]
    targets: [file:packages/ai-parrot/src/parrot/bots/abstract.py]
    contradicts: [{{decision_id: "adr:spec:feat-784#one", revision: 1}}]
{FENCE}
'''


def test_parse_spec_block_happy() -> None:
    """A complete block parses without diagnostics."""
    block, waivers, diagnostics = parse_spec_decisions(GOOD, source_path="sdd/specs/x.spec.md")
    assert diagnostics == []
    assert waivers == []
    assert block is not None
    assert [entry.id for entry in block.entries] == ["one", "two"]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda text: text.replace("## Decisions", "## Other"), SPEC_BLOCK_MISSING),
        (lambda text: text.replace("schema_version: 1", "schema_version: ["), SPEC_BLOCK_INVALID_YAML),
        (lambda text: text.replace("- id: two", "- id: one"), SPEC_DUPLICATE_ENTRY_ID),
        (lambda text: text.replace("document_id: feat-784", "document_id: bad/id"), SPEC_INVALID_ID),
        (lambda text: text.replace("relation: forbids", "relation: forbids\n    unexpected: value"), SPEC_UNKNOWN_FIELD),
        (lambda text: text.replace("#one", "#missing"), SPEC_DANGLING_REF),
        (lambda text: text.replace("about: [clients, memory]", "about: []"), SPEC_EMPTY_ABOUT),
        (lambda text: text.replace("targets: [dir:packages/ai-parrot/src/parrot/clients]", "targets: []"), SPEC_EMPTY_TARGETS),
    ],
)
def test_parse_spec_block_errors(mutation: object, code: str) -> None:
    """Every parser error condition reports its stable code rather than raising."""
    block, _, diagnostics = parse_spec_decisions(mutation(GOOD), source_path="x")  # type: ignore[operator]
    assert block is None
    assert code in {diagnostic.code for diagnostic in diagnostics}


def test_canonical_block_bytes_stable() -> None:
    """Equivalent YAML mappings have identical canonical JSON bytes."""
    reordered = GOOD.replace(
        "  - id: one\n    statement: Clients never persist history.\n    relation: forbids",
        "  - relation: forbids\n    statement: Clients never persist history.\n    id: one",
    )
    block, _, diagnostics = parse_spec_decisions(GOOD, source_path="x")
    reordered_block, _, reordered_diagnostics = parse_spec_decisions(reordered, source_path="x")
    assert diagnostics == [] and reordered_diagnostics == []
    assert block is not None and reordered_block is not None
    assert canonical_block_bytes(block) == canonical_block_bytes(reordered_block)


def test_entries_to_records_ids_and_fields() -> None:
    """Entries map to schema-2 records with typed targets and the caller batch."""
    block, _, diagnostics = parse_spec_decisions(GOOD, source_path="x")
    assert diagnostics == [] and block is not None
    records = entries_to_records(block, source_path="sdd/specs/x.spec.md", batch_id="batch-1")
    assert [record.decision_id for record in records] == ["adr:spec:feat-784#one", "adr:spec:feat-784#two"]
    assert [record.schema_version for record in records] == [2, 2]
    assert [record.targets[0].kind for record in records] == ["dir", "file"]
    assert [record.batch_id for record in records] == ["batch-1", "batch-1"]


def test_seed_heading_reuses_grammar() -> None:
    """Seed ADR metadata uses the identical structured grammar."""
    block, _, diagnostics = parse_spec_decisions(
        GOOD.replace("## Decisions", SEED_HEADING), source_path="docs/decisions/x.md", heading=SEED_HEADING
    )
    assert diagnostics == []
    assert block is not None


def test_extract_block_line_numbers() -> None:
    """Reported bounds point to body lines, excluding the fences."""
    source, start_line, end_line = extract_block(GOOD, "## Decisions")
    assert source is not None and source.startswith("schema_version: 1")
    assert (start_line, end_line) == (6, 19)
