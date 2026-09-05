"""Shared LLM resolution for the bookstore CLI and MCP server.

The model is configured via environment variables (or an explicit CLI
flag) as an ``LLMFactory`` spec string:

- ``PARROT_BOOKSTORE_LLM`` — heavy model, e.g. ``"google:gemini-2.5-flash"``
  or ``"anthropic:claude-sonnet-5"``.
- ``PARROT_BOOKSTORE_LLM_LIGHT`` — optional cheap model **id** for
  PageIndex helper calls. Must belong to the same provider as the heavy
  model: ``PageIndexToolkit`` pairs the heavy adapter's client with this
  id (see ``wiki/cli.py:_build_adapters`` for the same constraint).

When nothing is configured the bookstore runs degraded (BM25/catalog
only) — that is a supported mode, not an error.

Heavy parrot imports happen lazily inside the functions, under a
stdout→stderr redirect, so this module is safe to import from the MCP
server (stdout purity) and keeps fast CLI commands fast.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from typing import Any, Optional

ENV_LLM = "PARROT_BOOKSTORE_LLM"
ENV_LLM_LIGHT = "PARROT_BOOKSTORE_LLM_LIGHT"

logger = logging.getLogger(__name__)


def resolve_adapter(
    llm_spec: Optional[str] = None,
    lightweight_model: Optional[str] = None,
) -> tuple[Optional[Any], Optional[str], Optional[Any]]:
    """Build the PageIndex adapter from a spec or the environment.

    Args:
        llm_spec: Explicit ``provider:model`` spec; falls back to
            ``PARROT_BOOKSTORE_LLM``.
        lightweight_model: Explicit light model id; falls back to
            ``PARROT_BOOKSTORE_LLM_LIGHT``.

    Returns:
        ``(adapter, lightweight_model, client)`` — all ``None`` when no
        model is configured or the provider cannot be constructed (a
        warning is logged; the caller runs degraded).
    """
    spec = llm_spec or os.environ.get(ENV_LLM)
    light = lightweight_model or os.environ.get(ENV_LLM_LIGHT)
    if not spec:
        logger.warning(
            "No LLM configured (%s unset) — bookstore runs BM25/catalog only",
            ENV_LLM,
        )
        return None, None, None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.clients.factory import LLMFactory
            from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter

            _, model_id = LLMFactory.parse_llm_string(spec)
            client = LLMFactory.create(spec)
            adapter = PageIndexLLMAdapter(client, model=model_id)
    except Exception as exc:  # noqa: BLE001 — degrade, never crash startup
        logger.warning(
            "Could not build LLM client for %r (%s) — running degraded",
            spec,
            exc,
        )
        return None, None, None
    return adapter, light, client
