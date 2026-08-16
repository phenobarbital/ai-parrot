"""ObsidianGraphBridge — vault link graph → GraphIndex nodes/edges.

FEAT-392 Module 5. Pure transformation: takes parsed notes/canvases plus
the shared :class:`VaultIndex` (so link resolution is identical to the
toolkit and the wiki scanner) and emits ``UniversalNode``/``UniversalEdge``
lists ready for GraphIndex import.

Mapping (spec §5 — existing enum members only, Obsidian semantics carried
in ``domain_tags``):

* note → ``NodeKind.DOCUMENT``
* ``[[wikilink]]`` → ``EdgeKind.REFERENCES``
* ``![[embed]]`` → ``EdgeKind.REFERENCES`` + ``domain_tags={"embed": true}``
* ``#tag`` → ``NodeKind.CONCEPT`` + ``domain_tags={"obsidian_type": "tag"}``
* folder → ``NodeKind.DOCUMENT`` + ``{"obsidian_type": "folder"}`` and
  ``EdgeKind.CONTAINS`` edges for the hierarchy
* canvas → ``NodeKind.DOCUMENT`` + ``{"obsidian_type": "canvas"}``
* broken wikilink → placeholder node ``{"status": "unresolved"}``
"""
import logging
from pathlib import PurePosixPath

from parrot.interfaces.obsidian import (
    ObsidianCanvas,
    ObsidianNote,
    VaultIndex,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)

logger = logging.getLogger(__name__)


class ObsidianGraphBridge:
    """Convert an Obsidian vault's structure into GraphIndex form."""

    def __init__(
        self,
        notes: list[ObsidianNote],
        canvases: list[ObsidianCanvas],
        index: VaultIndex,
        vault_name: str = "vault",
    ) -> None:
        """Initialize the bridge.

        Args:
            notes: All parsed markdown notes.
            canvases: All parsed ``.canvas`` files.
            index: Shared vault index (single source of link resolution).
            vault_name: Vault name used in the deterministic node IDs.
        """
        self.notes = notes
        self.canvases = canvases
        self.index = index
        self.vault_name = vault_name
        self.logger = logger

    # ------------------------------------------------------------------ #
    # Node-ID convention (spec §7)
    # ------------------------------------------------------------------ #
    def note_id(self, path: str) -> str:
        """``obsidian::<vault>::<path-without-.md>``."""
        return f"obsidian::{self.vault_name}::{path}"

    def tag_id(self, tag: str) -> str:
        return f"obsidian::{self.vault_name}::tag::{tag}"

    def folder_id(self, folder: str) -> str:
        return f"obsidian::{self.vault_name}::folder::{folder}"

    def canvas_id(self, path: str) -> str:
        stem = path[:-len(".canvas")] if path.endswith(".canvas") else path
        return f"obsidian::{self.vault_name}::canvas::{stem}"

    def _uri(self, rel_path: str) -> str:
        return f"obsidian://{self.vault_name}/{rel_path}"

    # ------------------------------------------------------------------ #
    # Build
    # ------------------------------------------------------------------ #
    def build_graph(self) -> tuple[list[UniversalNode], list[UniversalEdge]]:
        """Convert vault structure into GraphIndex-compatible nodes/edges.

        Returns:
            ``(nodes, edges)`` — deduplicated, deterministic IDs, ready
            for GraphIndex import.
        """
        nodes: dict[str, UniversalNode] = {}
        edges: dict[tuple[str, str, str], UniversalEdge] = {}

        def add_node(node: UniversalNode) -> None:
            nodes.setdefault(node.node_id, node)

        def add_edge(
            source_id: str,
            target_id: str,
            kind: EdgeKind,
            domain_note: dict | None = None,
        ) -> None:
            key = (source_id, target_id, kind.value)
            if key not in edges:
                edges[key] = UniversalEdge(
                    source_id=source_id,
                    target_id=target_id,
                    kind=kind,
                    domain_tags=domain_note or {},
                )

        # --- Notes -----------------------------------------------------
        for note in self.notes:
            rel = note.path.as_posix()
            norm = rel[:-3] if rel.lower().endswith(".md") else rel
            domain_tags: dict = {"obsidian_type": "note"}
            if note.aliases:
                domain_tags["aliases"] = list(note.aliases)
            add_node(
                UniversalNode(
                    node_id=self.note_id(norm),
                    kind=NodeKind.DOCUMENT,
                    title=note.title,
                    source_uri=self._uri(rel),
                    summary=None,
                    domain_tags=domain_tags,
                )
            )

        # --- Folder hierarchy → CONTAINS -------------------------------
        for note in self.notes:
            norm = note.path.as_posix()
            norm = norm[:-3] if norm.lower().endswith(".md") else norm
            parts = PurePosixPath(norm).parts
            parent_id: str | None = None
            prefix = ""
            for folder in parts[:-1]:
                prefix = f"{prefix}/{folder}" if prefix else folder
                fid = self.folder_id(prefix)
                add_node(
                    UniversalNode(
                        node_id=fid,
                        kind=NodeKind.DOCUMENT,
                        title=folder,
                        source_uri=self._uri(prefix),
                        domain_tags={"obsidian_type": "folder"},
                    )
                )
                if parent_id:
                    add_edge(parent_id, fid, EdgeKind.CONTAINS)
                parent_id = fid
            if parent_id:
                add_edge(parent_id, self.note_id(norm), EdgeKind.CONTAINS)

        # --- Wikilinks and embeds → REFERENCES --------------------------
        for note in self.notes:
            norm = note.path.as_posix()
            norm = norm[:-3] if norm.lower().endswith(".md") else norm
            source_id = self.note_id(norm)
            for link in note.links:
                resolved = self.index.resolve(link.target, from_path=norm)
                if resolved is None:
                    # Placeholder node for a broken link (spec §5).
                    target_id = self.note_id(link.target)
                    add_node(
                        UniversalNode(
                            node_id=target_id,
                            kind=NodeKind.DOCUMENT,
                            title=link.target,
                            source_uri=self._uri(link.target),
                            domain_tags={
                                "obsidian_type": "note",
                                "status": "unresolved",
                            },
                        )
                    )
                else:
                    target_id = self.note_id(resolved)
                add_edge(
                    source_id,
                    target_id,
                    EdgeKind.REFERENCES,
                    domain_note={"embed": True} if link.is_embed else None,
                )

        # --- Tags → CONCEPT + REFERENCES --------------------------------
        for note in self.notes:
            norm = note.path.as_posix()
            norm = norm[:-3] if norm.lower().endswith(".md") else norm
            for tag in sorted(note.tags):
                tid = self.tag_id(tag)
                add_node(
                    UniversalNode(
                        node_id=tid,
                        kind=NodeKind.CONCEPT,
                        title=f"#{tag}",
                        source_uri=self._uri(f"tag/{tag}"),
                        domain_tags={"obsidian_type": "tag"},
                    )
                )
                add_edge(
                    self.note_id(norm),
                    tid,
                    EdgeKind.REFERENCES,
                    domain_note={"obsidian_type": "tag_link"},
                )

        # --- Canvas files ------------------------------------------------
        for canvas in self.canvases:
            rel = canvas.path.as_posix()
            cid = self.canvas_id(rel)
            add_node(
                UniversalNode(
                    node_id=cid,
                    kind=NodeKind.DOCUMENT,
                    title=canvas.title,
                    source_uri=self._uri(rel),
                    domain_tags={"obsidian_type": "canvas"},
                )
            )
            for card in canvas.cards:
                if card.card_type == "file" and card.file_path:
                    resolved = self.index.resolve(card.file_path)
                    if resolved is not None:
                        add_edge(cid, self.note_id(resolved), EdgeKind.REFERENCES)

        self.logger.debug(
            "ObsidianGraphBridge: %d nodes, %d edges from %d notes / %d canvases",
            len(nodes), len(edges), len(self.notes), len(self.canvases),
        )
        return list(nodes.values()), list(edges.values())
