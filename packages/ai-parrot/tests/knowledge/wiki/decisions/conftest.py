"""Synthetic ADR repository fixtures (FEAT-578 Modules 3 and 7).

Shared with the integration suite. The matrix mirrors spec §4 "Test Data /
Fixtures" exactly — change it there first.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionConfig

_ACCEPTED_ADR = """\
# Use pgvector for embeddings

## Context
We need a vector store for embeddings.

## Decision
Use pgvector as the primary vector store.

## Consequences
Postgres becomes a hard dependency.
"""

_SUPERSEDED_ADR = """\
# Legacy in-memory index

## Status
superseded

## Context
An early, since-replaced choice.

## Decision
Use an in-memory FAISS index.

## Consequences
Replaced once pgvector landed.
"""

_PROPOSED_ADR = """\
# Add a caching layer

## Status
proposed

## Context
Repeated queries are expensive.

## Decision
Add a caching layer in front of retrieval.

## Consequences
Adds an invalidation concern.
"""

_UNKNOWN_STATUS_ADR = """\
# Some undecided choice

## Status
percolating

## Context
Still discussing.

## Decision
Not yet finalized, tracked here anyway.

## Consequences
None decided yet.
"""

_DUP_ALIAS_TEMPLATE = """\
# Duplicate alias claim {label}

## Context
Both this and its sibling claim the same numeric id via their filename.

## Decision
Claim number 42, decision {label}.

## Consequences
Ambiguous by construction.
"""

_MALFORMED_FRONTMATTER_ADR = """\
---
id: ADR-7
nested:
  sub: value
---
# Malformed frontmatter ADR

## Context
The frontmatter above has an invalid nested block.

## Decision
Still a valid ADR despite the frontmatter defect.

## Consequences
A diagnostic is reported, not a fatal error.
"""


def _long_adr_text() -> str:
    padding = "Filler paragraph to push the Decision section past the ordinary body head.\n" * 400
    return (
        "# A very long ADR\n\n"
        "## Context\n"
        f"{padding}\n"
        "## Decision\n"
        "Decide this, past the 16000-character mark.\n\n"
        "## Consequences\n"
        "Still extracted correctly.\n"
    )


_CITING_MODULE = '''\
"""Module cited by ADR-1 (module-scope comment) and by ClassA.run (docstring)."""

# see ADR-1 for the pgvector rationale

MESSAGE = "not a real citation: ADR-1 appears only inside this string literal"


class ClassA:
    def run(self):
        """Implements the pgvector-backed path (see ADR-1)."""
        return "a"


class ClassB:
    def run(self):
        # An undocumented sibling: same method name, no citation at all.
        return "b"
'''

_LINKING_DOC = """\
# Notes

See `sym:src/citing_module.py#ClassA.run` for the pgvector-backed implementation.
"""


@pytest.fixture
def adr_repo(tmp_path: Path) -> Path:
    """A synthetic repository covering the full spec §4 fixture matrix.

    Contains: accepted / superseded / proposed / unknown-status ADRs, two
    files both claiming ``ADR-42``, malformed frontmatter, a long ADR whose
    Decision sits past 16000 characters, a Python module with two same-named
    symbols, a module-level comment citation, an executable string holding a
    false citation, one undocumented symbol, and a Markdown document linking
    an exact ``sym:`` id.
    """
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-use-pgvector.md").write_text(_ACCEPTED_ADR, encoding="utf-8")
    (adr_dir / "0002-legacy-index.md").write_text(_SUPERSEDED_ADR, encoding="utf-8")
    (adr_dir / "0003-add-caching.md").write_text(_PROPOSED_ADR, encoding="utf-8")
    (adr_dir / "0004-undecided.md").write_text(_UNKNOWN_STATUS_ADR, encoding="utf-8")
    (adr_dir / "0042-dup-a.md").write_text(_DUP_ALIAS_TEMPLATE.format(label="A"), encoding="utf-8")
    (adr_dir / "0042-dup-b.md").write_text(_DUP_ALIAS_TEMPLATE.format(label="B"), encoding="utf-8")
    (adr_dir / "0007-malformed-frontmatter.md").write_text(_MALFORMED_FRONTMATTER_ADR, encoding="utf-8")
    (adr_dir / "0008-long-adr.md").write_text(_long_adr_text(), encoding="utf-8")

    # A matching glob inside a directory the scanner always excludes.
    excluded_dir = adr_dir / "node_modules"
    excluded_dir.mkdir()
    (excluded_dir / "0099-excluded.md").write_text(_ACCEPTED_ADR, encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "citing_module.py").write_text(_CITING_MODULE, encoding="utf-8")

    (tmp_path / "docs" / "note-linking-symbol.md").write_text(_LINKING_DOC, encoding="utf-8")

    return tmp_path


@pytest.fixture
def adr_config() -> DecisionConfig:
    """Default config with generation disabled (the shipped default)."""
    return DecisionConfig()


@pytest.fixture
async def adr_store(tmp_path):
    """A file-backed wiki plane for ADR round-trips."""
    from parrot.knowledge.wiki.file_store import InMemoryWikiStore

    return InMemoryWikiStore(tmp_path / "wiki-pages", wiki_name="adr-test")
