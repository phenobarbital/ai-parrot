"""One wiring for every decision-audit surface: MCP, CLI and gate script (FEAT-784 M9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from parrot.knowledge.wiki.decisions.models import ADR_SOURCE_UNAVAILABLE, DecisionError

TAXONOMY_REL = "sdd/taxonomy/subsystems.yaml"
APPROVALS_REL = "sdd/decisions/approvals.jsonl"


def taxonomy_path(root: Path) -> Path:
    """Return the subsystem taxonomy path under ``root``.

    Args:
        root: Repository root.

    Returns:
        ``<root>/sdd/taxonomy/subsystems.yaml``.
    """
    return root / TAXONOMY_REL


def approvals_path(root: Path) -> Path:
    """Return the approvals manifest path under ``root``.

    Args:
        root: Repository root.

    Returns:
        ``<root>/sdd/decisions/approvals.jsonl``.
    """
    return root / APPROVALS_REL


def is_configured(root: Path) -> bool:
    """Configured when the taxonomy OR the approvals manifest exists (spec §2 portability). No store access.

    Args:
        root: Repository root.

    Returns:
        True when the decision audit is configured for this repository.
    """
    return taxonomy_path(root).is_file() or approvals_path(root).is_file()


def open_consequence_service(root: Path, *, store: Any = None, config: Any = None, base_branch: str = "dev") -> Any:
    """Build a ``ConsequenceService`` with a non-repairing structural plane (spec S6).

    Args:
        root: Repository root.
        store: Already-open wiki store (MCP); resolved from ``root`` when omitted.
        config: ``WikiProjectConfig`` (MCP); resolved from ``root`` when omitted.
        base_branch: Branch the approval adapter verifies commits against.

    Returns:
        A ``ConsequenceService``.

    Raises:
        DecisionError: ``ADR_SOURCE_UNAVAILABLE`` when the wiki plane was never built.
    """
    import click

    from parrot.knowledge.wiki.decisions.approvals import GitCommitApprovalAdapter
    from parrot.knowledge.wiki.decisions.consequences import ConsequenceService
    from parrot.knowledge.wiki.structural.service import StructuralService

    if store is None or config is None:
        from parrot.knowledge.wiki.cli import _require_built, _resolve_project

        try:
            root, config = _resolve_project(str(root))
            store = _require_built(root, config)
        except click.ClickException as exc:
            raise DecisionError(ADR_SOURCE_UNAVAILABLE, exc.format_message()) from exc
    structural = StructuralService(store, root, config, read_repair=False)
    return ConsequenceService(
        store,
        root,
        config.decisions,
        structural,
        taxonomy_path=taxonomy_path(root),
        approvals_path=approvals_path(root),
        adapter=GitCommitApprovalAdapter(root, base_branch),
    )
