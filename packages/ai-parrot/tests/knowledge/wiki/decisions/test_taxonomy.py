"""FEAT-784 M3 — subsystem taxonomy."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from parrot.knowledge.wiki.decisions.models import DecisionError
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy

VALID = """schema_version: 1
subsystems:
  - {id: memory, title: Memory, description: Stores turns, projects: [ai-parrot]}
  - {id: clients, title: Clients, projects: [ai-parrot]}
  - {id: server, title: Server, projects: [ai-parrot-server]}
  - {id: memory-compaction, title: Compaction, parent: memory, projects: [ai-parrot]}
mapping: {memory: memory, mcp: server}
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "subsystems.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_taxonomy_load_and_ids(tmp_path: Path) -> None:
    """Load the documented format and expose all ids."""
    assert Taxonomy.load(_write(tmp_path, VALID)).ids() >= {"memory", "clients"}


@pytest.mark.parametrize(
    "bad",
    [
        """schema_version: 1
subsystems:
  - {id: child, title: Child, parent: absent, projects: [ai-parrot]}
""",
        """schema_version: 1
subsystems:
  - {id: memory, title: Memory, projects: [no-such-pkg]}
""",
        """schema_version: 1
subsystems:
  - {id: memory, title: Memory, projects: [ai-parrot]}
  - {id: memory, title: Again, projects: [ai-parrot]}
""",
        """schema_version: 1
subsystems:
  - {id: first, title: First, parent: second, projects: [ai-parrot]}
  - {id: second, title: Second, parent: first, projects: [ai-parrot]}
""",
        """schema_version: 1
subsystems:
  - {id: memory, title: Memory, projects: [ai-parrot]}
mapping: {memory: absent}
""",
        "schema_version: [\n",
        """schema_version: 1
subsystems:
  - {id: memory, title: Memory, projects: [ai-parrot], unexpected: true}
""",
    ],
)
def test_taxonomy_rejects(tmp_path: Path, bad: str) -> None:
    """Reject every malformed or structurally invalid taxonomy."""
    with pytest.raises(DecisionError) as exc:
        Taxonomy.load(_write(tmp_path, bad))
    assert exc.value.code == "TAXONOMY_INVALID"


def test_closest_suggests_without_correcting(tmp_path: Path) -> None:
    """Suggest a close id without changing taxonomy membership."""
    taxonomy = Taxonomy.load(_write(tmp_path, VALID))
    original_ids = taxonomy.ids()

    assert taxonomy.closest("memroy")[0] == "memory"
    assert taxonomy.ids() == original_ids
    assert "memroy" not in taxonomy.ids()


def test_map_projects_and_unmapped(tmp_path: Path) -> None:
    """Combine deterministic project/tag mappings and report unknown tags."""
    taxonomy = Taxonomy.load(_write(tmp_path, VALID))

    assert taxonomy.map_projects(["ai-parrot-server"], ["mcp", "weird"]) == ["server"]
    assert taxonomy.map_projects(["ai-parrot"], ["mcp", "memory"]) == [
        "clients",
        "memory",
        "memory-compaction",
        "server",
    ]
    assert taxonomy.unmapped(["weird", "mcp", "weird"]) == ["weird"]


def test_digest_stable_and_sensitive(tmp_path: Path) -> None:
    """Hash validated content deterministically and include content changes."""
    first = Taxonomy.load(_write(tmp_path, VALID)).digest()
    second = Taxonomy.load(_write(tmp_path, VALID)).digest()
    changed = Taxonomy.load(_write(tmp_path, VALID.replace("title: Memory", "title: Conversation Memory"))).digest()

    assert first == second
    assert first != changed


def test_project_pages(tmp_path: Path) -> None:
    """Project sorted authored concept pages with description hashes."""
    pages = Taxonomy.load(_write(tmp_path, VALID)).project_pages()

    assert [page.concept_id for page in pages] == [
        "concept:clients",
        "concept:memory",
        "concept:memory-compaction",
        "concept:server",
    ]
    memory_page = next(page for page in pages if page.concept_id == "concept:memory")
    assert memory_page.node_id == "concept:memory"
    assert memory_page.category == "concept"
    assert memory_page.summary == "Stores turns"
    assert memory_page.body == "Stores turns"
    assert memory_page.origin == "authored"
    assert memory_page.content_hash == hashlib.sha1(b"Stores turns").hexdigest()
