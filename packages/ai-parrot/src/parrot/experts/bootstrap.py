"""Load domain experts into an AgentRegistry from any host (FEAT-778 M14)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.conf import AGENTS_DIR
from parrot.experts.registry import ExpertRegistry

_LOGGER = logging.getLogger(__name__)
EXPERTS_WIKI_DIRNAME = ".experts_wiki"


def _default_wiki_toolkit(agents_dir: Path) -> Any:
    """Build a lightweight sqlite-backed toolkit for expert namespaces.

    Args:
        agents_dir: The agent configuration root that owns expert wiki data.

    Returns:
        A wiki toolkit backed by ``agents_dir/.experts_wiki``.
    """
    from parrot.knowledge.wiki.models import WikiConfig  # noqa: PLC0415
    from parrot.knowledge.wiki.store import create_wiki_store  # noqa: PLC0415
    from parrot_tools.wiki.toolkit import LLMWikiToolkit  # noqa: PLC0415

    storage = agents_dir / EXPERTS_WIKI_DIRNAME
    storage.mkdir(parents=True, exist_ok=True)
    config = WikiConfig(wiki_name="experts", storage_dir=storage, storage_backend="sqlite", sync_graph=False)
    store = create_wiki_store(storage, wiki_name="experts", backend="sqlite")
    return LLMWikiToolkit(None, None, None, config, agent_id="experts", store=store)


async def load_experts(
    agent_registry: Any,
    *,
    agents_dir: Path | None = None,
    workspace: Path | None = None,
    wiki_toolkit: Any = None,
    bookstore: Any = None,
    enabled: bool = True,
) -> ExpertRegistry | None:
    """Discover, seed, and register experts without preventing host startup.

    Args:
        agent_registry: Registry receiving the loaded expert instances.
        agents_dir: Optional root containing user-supplied agent bundles.
        workspace: Optional workspace supplied to expert agents.
        wiki_toolkit: Optional host-provided wiki toolkit.
        bookstore: Optional host-provided bookstore dependency.
        enabled: Whether expert discovery is enabled for this host.

    Returns:
        The populated registry, or ``None`` when disabled or loading fails.
    """
    if not enabled:
        return None
    root = Path(agents_dir or AGENTS_DIR)
    registry: ExpertRegistry | None = None
    try:
        registry = ExpertRegistry(
            agent_registry=agent_registry,
            agents_dir=root,
            workspace=workspace,
            wiki_toolkit=wiki_toolkit or _default_wiki_toolkit(root),
            bookstore=bookstore,
        )
        count = await registry.load()
        report = registry.report()
        _LOGGER.info(
            "experts: %d loaded, %d skipped, %d seeded, shadowing=%s",
            count,
            len(report["skipped"]),
            len(report["seeded"]),
            report["shadowing"],
        )
        agent_registry.experts = registry
        return registry
    except Exception:  # pylint: disable=broad-except
        _LOGGER.exception("experts: loading failed; report so far=%s", registry.report() if registry else None)
        return None
