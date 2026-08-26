"""
Web Browsing subsystem — catalogued, deterministic site automation.

Builds on the WebScrapingToolkit DSL (``parrot_tools.scraping.models``)
to provide a per-site **action catalog**: named, parameterized scripts
("guiones") stored on disk (one folder per site, one JSON file per
action) that an agent can look up from a natural-language request and
execute deterministically against a persistent browser session.

Public surface:

- :class:`~parrot_tools.browsing.toolkit.WebBrowsingToolkit` — the
  agent-facing toolkit (extends ``WebScrapingToolkit``).
- :class:`~parrot_tools.browsing.catalog.ActionCatalog` — disk-backed
  site/action store.
- :class:`~parrot_tools.browsing.models.SiteAction` /
  :class:`~parrot_tools.browsing.models.SiteInfo` — catalog models.
"""
from .catalog import ActionCatalog
from .composer import ResolvedAction, expand_action, expand_sequence
from .models import (
    ActionParam,
    ActionRunSummary,
    ComposedRef,
    SequenceRunResult,
    SiteAction,
    SiteInfo,
)
from .templating import render_steps, validate_loop_bounds
from .toolkit import WebBrowsingToolkit

__all__ = (
    "ActionCatalog",
    "ActionParam",
    "ActionRunSummary",
    "ComposedRef",
    "ResolvedAction",
    "SequenceRunResult",
    "SiteAction",
    "SiteInfo",
    "WebBrowsingToolkit",
    "expand_action",
    "expand_sequence",
    "render_steps",
    "validate_loop_bounds",
)
