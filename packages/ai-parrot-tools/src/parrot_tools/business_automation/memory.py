"""gestoria wiki plane + Obsidian mirror (FEAT-453, Module 10, Goal G8).

Instantiates FEAT-452's domain-plane recipe (already proven in-repo by
TASK-2379's ``notes`` plane, see ``agents/fireflies_wiki.py::_build_notes_wiki_toolkit``)
for a dedicated ``gestoria`` wiki: its own ``LLMWikiToolkit`` instance, own
storage root, own PageIndex authoring plane, and own GraphIndex tenant
(``tenant_id="gestoria"``). This is **not** a parameter passed to an
existing wiki — ``LLMWikiToolkit._config_for()`` resolves a *registered
namespace* name to the SAME config (a namespace *query* concern, per the
FEAT-450 merge), it does not give a namespace its own storage plane. A
second toolkit instance is mandatory for a genuinely separate plane.

Namespace **registration** (``wikitoolkit ns add``) is an explicit
operator runbook step (see ``docs/business-automation-runbook.md``), never
agent code (FEAT-452 TASK-2382 non-scope) — an unregistered plane silently
accumulates knowledge nobody can retrieve via ``wikitoolkit query``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from navconfig import config

if TYPE_CHECKING:
    from parrot.knowledge.wiki.toolkit import LLMWikiToolkit
    from parrot.tools.obsidian import ObsidianToolkit

logger = logging.getLogger(__name__)

#: Fallback LLM for the gestoria wiki's PageIndex authoring plane — mirrors
#: the existing FEAT-452 recipe's fallback pattern.
_DEFAULT_LLM = "anthropic:claude-haiku-4-5"

#: Config keys mirror the existing wiki_name/wiki_storage_dir convention
#: (agents/fireflies_wiki.py's FIREFLIES_WIKI_* / AUDIO_NOTES_WIKI_* keys).
GESTORIA_WIKI_NAME: str = config.get("GESTORIA_WIKI_NAME", fallback="gestoria")
GESTORIA_WIKI_STORAGE_DIR: Path = Path(
    config.get(
        "GESTORIA_WIKI_STORAGE_DIR",
        fallback=str(Path.home() / ".parrot" / "wikis" / "gestoria"),
    )
).expanduser()
GESTORIA_FOLDER: str = config.get("GESTORIA_FOLDER", fallback="gestoria")
_GESTORIA_LLM: str = config.get("GESTORIA_WIKI_LLM", fallback=_DEFAULT_LLM)


def _build_pageindex_toolkit(storage: Path) -> Optional[Any]:
    """Build the PageIndex authoring plane for the gestoria wiki.

    A near-copy of the FEAT-452 recipe's ``_build_pageindex_toolkit()``.
    Best-effort: any failure logs a warning and returns ``None`` — the wiki
    still functions as a retrieval-only plane without an authoring plane.
    """
    model_spec = config.get("WIKI_MODEL") or _GESTORIA_LLM
    try:
        from parrot.clients.factory import LLMFactory
        from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter
        from parrot.knowledge.pageindex.toolkit import PageIndexToolkit

        _, model_id = LLMFactory.parse_llm_string(model_spec)
        adapter = PageIndexLLMAdapter(LLMFactory.create(model_spec), model=model_id)
        pageindex_dir = storage / "pageindex"
        pageindex_dir.mkdir(parents=True, exist_ok=True)
        return PageIndexToolkit(adapter, storage_dir=pageindex_dir)
    except Exception:
        logger.warning(
            "PageIndexToolkit unavailable for the gestoria wiki; pages will " "be written to the retrieval plane only.",
            exc_info=True,
        )
        return None


async def build_gestoria_wiki(
    *,
    storage_dir: Optional[Path] = None,
    wiki_name: str = GESTORIA_WIKI_NAME,
    agent_id: str = "gestoria",
) -> Optional["LLMWikiToolkit"]:
    """Construct the dedicated ``gestoria`` ``LLMWikiToolkit``.

    Bootstraps the layout with an idempotent ``create_wiki()`` call so
    repeat calls (e.g. process restarts) never error. Best-effort
    throughout: any failure logs a warning naming ``"gestoria"`` and
    returns ``None`` so the calling agent still boots.

    Args:
        storage_dir: Storage root override (default:
            ``GESTORIA_WIKI_STORAGE_DIR``, expanded from
            ``$GESTORIA_WIKI_STORAGE_DIR`` or ``~/.parrot/wikis/gestoria``).
        wiki_name: Wiki name override (default: ``GESTORIA_WIKI_NAME``).
        agent_id: Identity stamped onto pages this plane authors.

    Returns:
        A wired ``LLMWikiToolkit`` for the gestoria plane, or ``None`` when
        construction fails.
    """
    storage = Path(storage_dir).expanduser() if storage_dir is not None else GESTORIA_WIKI_STORAGE_DIR

    try:
        storage.mkdir(parents=True, exist_ok=True)

        from parrot.knowledge.graphindex.factory import build_graph_memory_toolkit
        from parrot.knowledge.wiki.models import WikiConfig
        from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

        pageindex_toolkit = _build_pageindex_toolkit(storage)
        graph_toolkit = await build_graph_memory_toolkit(
            storage / "graph",
            tenant_id=wiki_name,
            agent_id=agent_id,
        )

        wiki_config = WikiConfig(
            wiki_name=wiki_name,
            storage_dir=storage,
            sync_graph=True,
        )
        toolkit = LLMWikiToolkit(
            pageindex_toolkit,
            graph_toolkit,
            None,
            wiki_config,
            agent_id=agent_id,
        )
    except Exception:
        logger.warning("gestoria LLMWikiToolkit unavailable", exc_info=True)
        return None

    try:
        await toolkit.create_wiki(wiki_name)
    except Exception:
        logger.warning(
            "create_wiki(%r) failed for the gestoria plane; continuing with " "the existing layout.",
            wiki_name,
            exc_info=True,
        )

    logger.info(
        "gestoria LLMWikiToolkit ready (wiki=%s, storage=%s, pageindex=%s)",
        wiki_name,
        storage,
        "on" if pageindex_toolkit is not None else "off",
    )
    return toolkit


def _params_digest(params: Dict[str, Any]) -> str:
    """Stable digest of *params* — never the raw values (client names,
    amounts) in a page title/frontmatter that gets mirrored/ingested."""
    canonical = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def record_operation_page(
    *,
    wiki: Optional["LLMWikiToolkit"],
    obsidian: Optional["ObsidianToolkit"],
    operation: str,
    params: Dict[str, Any],
    gate_decision: str,
    outcome: str,
    run_id: str,
    wiki_name: str = GESTORIA_WIKI_NAME,
    folder: str = GESTORIA_FOLDER,
) -> Dict[str, Any]:
    """Record one completed business operation as a page, mirrored to Obsidian.

    Records: what ran (*operation*), a stable digest of its parameters
    (never the raw values), the confirmation-gate decision, and the
    outcome. Both the wiki write and the Obsidian mirror are best-effort —
    a failure in either is logged and does not raise, since this is an
    audit/knowledge side effect, not the operation's own result.

    Args:
        wiki: The gestoria :class:`LLMWikiToolkit` (from
            :func:`build_gestoria_wiki`); ``None`` skips the wiki write.
        obsidian: An :class:`ObsidianToolkit` mirroring into the vault;
            ``None`` skips the Obsidian mirror.
        operation: The :class:`~parrot_tools.business_automation.models.BusinessOperation`
            name that ran.
        params: The parameters it ran with (digested, never stored raw).
        gate_decision: The :class:`~parrot.auth.confirmation.ConfirmationDecision`
            status (e.g. ``"confirmed"``, ``"not_required"``, ``"cancelled"``).
        outcome: The run's final status (e.g. ``"done"``, ``"failed"``).
        run_id: The `BusinessAutomationToolkit` run id.
        wiki_name: Wiki name to create the page in.
        folder: Obsidian vault subfolder for the mirror.

    Returns:
        ``{"wiki": <create_page result or None>, "obsidian": <create_note result or None>}``.
    """
    digest = _params_digest(params)
    timestamp = datetime.now(timezone.utc).isoformat()
    title = f"{operation} — {run_id}"
    body = (
        f"- **Operation**: {operation}\n"
        f"- **Params digest**: {digest}\n"
        f"- **Gate decision**: {gate_decision}\n"
        f"- **Outcome**: {outcome}\n"
        f"- **Recorded at**: {timestamp}\n"
    )

    wiki_result: Optional[Dict[str, Any]] = None
    if wiki is not None:
        try:
            wiki_result = await wiki.create_page(wiki_name, title, body, category="summary")
        except Exception:
            logger.warning(
                "Failed to record operation %r (run_id=%s) to the gestoria " "wiki plane",
                operation,
                run_id,
                exc_info=True,
            )

    obsidian_result: Optional[Dict[str, Any]] = None
    if obsidian is not None:
        note_path = f"{folder}/{operation}-{run_id}.md"
        try:
            obsidian_result = await obsidian.create_note(
                note_path,
                f"# {title}\n\n{body}",
                frontmatter={
                    "operation": operation,
                    "run_id": run_id,
                    "gate_decision": gate_decision,
                    "outcome": outcome,
                    "params_digest": digest,
                },
            )
        except Exception:
            logger.warning(
                "Failed to mirror operation %r (run_id=%s) to the Obsidian vault",
                operation,
                run_id,
                exc_info=True,
            )

    return {"wiki": wiki_result, "obsidian": obsidian_result}
