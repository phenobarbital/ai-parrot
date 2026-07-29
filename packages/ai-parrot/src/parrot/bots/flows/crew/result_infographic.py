"""Deterministic Tab-Assembly Helper for AgentCrew Infographic (FEAT-308).

Spec: ``sdd/specs/agentcrew-node-infographic.spec.md`` §3 Module 2.

Reads a crew's ``ExecutionMemory`` and builds the deterministic block list
for the ``crew_report`` infographic template: the Final-Result tab (Tab 2)
plus one tab per research agent (Tabs 3...N), excluding the ResultAgent's own
``node_id``. Large or non-text results are summarized (truncated with a
note) or linked out via an optional ``ArtifactStore``-like object, never
dumped raw into a tab. The LLM-authored Tab 1 (Executive Summary & Insights)
is merged in front by ``merge_tab1_blocks``.

Codebase Contract corrections (verified against
``parrot/models/infographic.py`` on 2026-07-14):
    - Block dicts are discriminated by the ``"type"`` key (e.g.
      ``{"type": "title", ...}``), NOT ``"block_type"`` as an earlier draft
      of this task's pseudo-code suggested. Verified via
      ``InfographicToolkit._validate_blocks`` (``block_raw.get("type")``,
      infographic_toolkit.py:981).
    - ``TitleBlock`` uses a ``title`` field, not ``content``
      (infographic.py:213-220).
    - ``TabPane`` requires an ``id`` field (unique slug), not just ``label``
      (infographic.py:196-206).
    - Per-tab content blocks use ``SummaryBlock`` (``type="summary"``,
      ``content: str``), which has its own hard ``max_length=2000``
      constraint (infographic.py:365-377) — independent of and much smaller
      than ``_INLINE_THRESHOLD`` (50_000, infographic_toolkit.py:49, which
      gates the *page-level* ``html_inline`` decision). Content is therefore
      always truncated to fit within ``SummaryBlock.content``'s limit, with
      an explicit truncation note appended whenever the underlying result
      exceeds ``_INLINE_THRESHOLD`` or the block's own max length.
    - ``ArtifactStore`` (``parrot/storage/artifacts.py``) requires
      ``user_id``/``agent_id``/``session_id`` plus initialised backends to
      call ``save_artifact()`` — none of which this pure(ish) helper has
      access to. ``artifact_store`` therefore accepts an optional duck-typed
      object exposing ``publish(key: str, content: str) -> Optional[str]``;
      when absent (the default), large results fall back to truncation +
      note. TODO: wire the real ``ArtifactStore`` once a session context is
      threaded through ``AgentCrew._finalize_infographic`` (TASK-1779).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from parrot.bots.flows.core.storage.memory import ExecutionMemory
from parrot.tools.infographic_toolkit import _INLINE_THRESHOLD

logger = logging.getLogger(__name__)

# SummaryBlock.content max_length (parrot/models/infographic.py:365-377).
_SUMMARY_BLOCK_MAX_LENGTH = 2000
# Leave headroom in the 2000-char budget for the truncation note itself.
_SAFE_CONTENT_LENGTH = 1800

_FINAL_RESULT_TAB_ID = "final-result"
_EXEC_SUMMARY_TAB_ID = "executive-summary"


def _summarize_content(
    node_id: str,
    text: str,
    artifact_store: Optional[Any] = None,
) -> str:
    """Return ``text`` unchanged, or a summarized/linked-out version.

    Triggers summarization when ``text`` exceeds ``_INLINE_THRESHOLD`` (the
    "large result" signal, per the spec) or exceeds ``SummaryBlock``'s own
    ``max_length`` (a hard rendering constraint). Never returns raw content
    longer than ``_SUMMARY_BLOCK_MAX_LENGTH``.

    Args:
        node_id: The node/agent id the result belongs to (used as the
            artifact key when linking out).
        text: The result's rendered text (e.g. via ``NodeResult.to_text()``).
        artifact_store: Optional object exposing
            ``publish(key: str, content: str) -> Optional[str]``.

    Returns:
        Content safe to embed in a ``SummaryBlock``.
    """
    is_large = len(text) > _INLINE_THRESHOLD
    fits_summary_block = len(text) <= _SUMMARY_BLOCK_MAX_LENGTH

    if not is_large and fits_summary_block:
        return text

    link_url: Optional[str] = None
    if artifact_store is not None:
        try:
            link_url = artifact_store.publish(node_id, text)
        except Exception:  # noqa: BLE001 — never let artifact publishing break tab assembly
            logger.warning(
                "ArtifactStore publish failed for node '%s'; falling back to "
                "truncation.",
                node_id,
                exc_info=True,
            )

    if link_url:
        content = f"Result too large to display inline. Full result: {link_url}"
    else:
        truncated = text[:_SAFE_CONTENT_LENGTH]
        content = (
            f"{truncated}\n\n"
            f"[...truncated — {len(text)} chars total, exceeding inline "
            f"display limits.]"
        )

    return content[:_SUMMARY_BLOCK_MAX_LENGTH]


def _summary_block(content: str, title: Optional[str] = None) -> Dict[str, Any]:
    """Build a ``SummaryBlock``-shaped dict."""
    block: Dict[str, Any] = {"type": "summary", "content": content}
    if title:
        block["title"] = title
    return block


def build_deterministic_tabs(
    execution_memory: ExecutionMemory,
    final_output: Any,
    exclude_node_id: Optional[str] = None,
    artifact_store: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Build the deterministic ``crew_report`` block list.

    Produces a ``[title, tab_view]`` block list where the ``tab_view``
    contains the Final-Result tab followed by one tab per research agent
    found in ``execution_memory.results`` — excluding ``exclude_node_id``
    (the ResultAgent's own node, to avoid self-reference). The LLM-authored
    Tab 1 (Executive Summary) is NOT included here; call
    :func:`merge_tab1_blocks` afterwards to insert it as the first tab.

    Args:
        execution_memory: The crew's ``ExecutionMemory`` for the current run.
        final_output: The crew's final result (``FlowResult.output``).
        exclude_node_id: Node id to exclude from the per-agent tabs (the
            ResultAgent's own id).
        artifact_store: Optional duck-typed artifact publisher; see
            :func:`_summarize_content`.

    Returns:
        A list with a ``title`` block followed by a ``tab_view`` block.
    """
    tabs: List[Dict[str, Any]] = [
        {
            "id": _FINAL_RESULT_TAB_ID,
            "label": "Final Result",
            "blocks": [
                _summary_block(
                    _summarize_content(
                        _FINAL_RESULT_TAB_ID, str(final_output), artifact_store,
                    )
                )
            ],
        }
    ]

    for node_id, node_result in execution_memory.results.items():
        if node_id == exclude_node_id:
            continue
        text = node_result.to_text()
        label = getattr(node_result, "node_name", node_id) or node_id
        tabs.append(
            {
                "id": f"agent-{node_id}",
                "label": label,
                "blocks": [
                    _summary_block(_summarize_content(node_id, text, artifact_store))
                ],
            }
        )

    return [
        {"type": "title", "title": "Crew Execution Report"},
        {"type": "tab_view", "tabs": tabs},
    ]


def merge_tab1_blocks(
    tab1_blocks: List[Dict[str, Any]],
    deterministic_blocks: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Insert the LLM-authored Tab 1 as the first tab in the ``tab_view``.

    Args:
        tab1_blocks: LLM-authored blocks (e.g. ``SummaryBlock`` dicts) for
            the Executive Summary & Insights tab.
        deterministic_blocks: The ``[title, tab_view]`` list produced by
            :func:`build_deterministic_tabs`.

    Returns:
        A new block list with Tab 1 inserted as the first tab of the
        ``tab_view`` block. Does not mutate ``deterministic_blocks``.
    """
    merged: List[Dict[str, Any]] = []
    tab1_pane = {
        "id": _EXEC_SUMMARY_TAB_ID,
        "label": "Executive Summary",
        "blocks": tab1_blocks,
    }
    for block in deterministic_blocks:
        if block.get("type") == "tab_view":
            new_block = dict(block)
            new_block["tabs"] = [tab1_pane, *block.get("tabs", [])]
            merged.append(new_block)
        else:
            merged.append(block)
    return merged
