"""Tier-2 knowledge: workspace and tenant files (FEAT-778 M5)."""

from __future__ import annotations

from pathlib import Path

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind, KnowledgeSourceSpec
from parrot.memory.compaction.tokens import TokenCounter


class WorkspaceSource:
    """Produce optional shared and tenant-owned Tier-2 inline layers."""

    kind = KnowledgeSourceKind.WORKSPACE

    def __init__(self, shared_dir: Path | None = None) -> None:
        """Initialize the optional directory of shared Tier-2 files.

        Args:
            shared_dir: Directory whose Markdown files form shared Tier-2 knowledge.
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
        """Return deterministic shared and eligible tenant Tier-2 layers.

        Args:
            spec: Declared workspace source specification.
            bundle: Expert bundle supplying the tenant context.
            workspace: Unused optional workspace root, required by the source protocol.
            counter: Token counter for emitted text.

        Returns:
            Shared layers followed by tenant layers when the bundle allows them.
        """
        layers: list[KnowledgeLayer] = []
        if self.shared_dir is not None and self.shared_dir.is_dir():
            layers.extend(self._file_layers(self.shared_dir, "tier2_shared", counter))

        if bundle.tenant and not bundle.manifest.global_only:
            tenant_dir = bundle.root / "tenants" / bundle.tenant / "knowledge"
            if tenant_dir.is_dir():
                layers.extend(self._file_layers(tenant_dir, "tier2_expert", counter, bundle.root))
        return layers

    @staticmethod
    def _file_layers(
        directory: Path,
        layer: str,
        counter: TokenCounter,
        relative_root: Path | None = None,
    ) -> list[KnowledgeLayer]:
        """Build layers for sorted Markdown files directly inside a directory."""
        root = relative_root or directory
        return [
            WorkspaceSource._layer_from_file(path, root, layer, counter)
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
