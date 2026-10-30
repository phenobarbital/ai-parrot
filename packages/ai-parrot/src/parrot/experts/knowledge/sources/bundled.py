"""Tier-1 knowledge: files shipped with the bundle (FEAT-778 M5)."""

from __future__ import annotations

from pathlib import Path

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.memory.compaction.tokens import TokenCounter


class BundledSource:
    """Produce optional shared and bundle-owned Tier-1 inline layers."""

    kind = KnowledgeSourceKind.BUNDLED

    def __init__(self, shared_dir: Path | None = None) -> None:
        """Initialize the optional directory of shared Tier-1 files.

        Args:
            shared_dir: Directory whose Markdown files form shared Tier-1 knowledge.
        """
        self.shared_dir = shared_dir

    async def layers(
        self,
        spec: KnowledgeSourceSpec,
        bundle: ExpertBundle,
        *,
        workspace: Path | None,
        counter: TokenCounter,
    ) -> list[KnowledgeLayer]:
        """Return deterministic Tier-1 layers, excluding tenant-shadowed bundle files.

        Args:
            spec: Declared bundled source specification.
            bundle: Expert bundle supplying the Tier-1 files.
            workspace: Unused optional workspace root, required by the source protocol.
            counter: Token counter for emitted text.

        Returns:
            Shared layers followed by non-shadowed expert layers.
        """
        shadowed: set[str] = set()
        if bundle.tenant and not bundle.manifest.global_only:
            tenant_dir = bundle.root / "tenants" / bundle.tenant / "knowledge"
            shadowed = {path.name for path in tenant_dir.glob("*.md") if path.is_file()} if tenant_dir.is_dir() else set()

        layers: list[KnowledgeLayer] = []
        if self.shared_dir is not None and self.shared_dir.is_dir():
            layers.extend(self._file_layers(self.shared_dir, "tier1_shared", counter))

        for path in sorted(bundle.knowledge_files, key=lambda item: item.name):
            if path.name not in shadowed:
                layers.append(self._layer_from_file(path, bundle.root, "tier1_expert", counter))
        return layers

    @staticmethod
    def _file_layers(directory: Path, layer: str, counter: TokenCounter) -> list[KnowledgeLayer]:
        """Build layers for sorted Markdown files directly inside a directory."""
        return [
            BundledSource._layer_from_file(path, directory, layer, counter)
            for path in sorted(directory.glob("*.md"), key=lambda item: item.name)
            if path.is_file()
        ]

    @staticmethod
    def _layer_from_file(path: Path, root: Path, layer: str, counter: TokenCounter) -> KnowledgeLayer:
        """Build one revisioned inline layer from a Markdown file."""
        data = path.read_bytes()
        content = data.decode()
        return KnowledgeLayer(
            layer=layer,
            source=path.relative_to(root).as_posix(),
            mode=KnowledgeMode.INLINE,
            revision=sha256_revision(data),
            tokens=counter.count(content),
            content=content,
        )
