"""Roblox platform integration for wikitoolkit (FEAT-532).

This package hosts two independent tracks described by
``sdd/specs/wikitoolkit-luau-roblox.spec.md``:

- Local project mapping (``project.py``, module 2): resolves Roblox
  ``require`` calls through ``sourcemap.json``/``default.project.json``.
- API plane acquisition/publication (``acquire.py``, ``render.py``,
  ``ingest.py``, modules 3-4): builds an independently generated,
  federated Roblox API wiki plane from the official API dump and
  creator-docs, with no LLM calls.

Deliberately minimal: importing this package must never perform network
I/O, construct an HTTP client, load a tree-sitter grammar, or touch the
filesystem. ``models.py`` (this task, TASK-2897) defines the typed
contracts shared by both tracks so they can be implemented independently
without editing each other's files.
"""

from __future__ import annotations
