---
type: Wiki Summary
title: parrot._imports
id: mod:parrot._imports
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Lazy Import Utility for AI-Parrot.
relates_to:
- concept: func:parrot._imports.lazy_import
  rel: defines
- concept: func:parrot._imports.require_extra
  rel: defines
---

# `parrot._imports`

Lazy Import Utility for AI-Parrot.

This module provides a canonical pattern for lazily importing optional
dependencies across the codebase. It replaces the ad-hoc try/except patterns
previously scattered across 40+ files.

Usage::

    from parrot._imports import lazy_import, require_extra

    # Import a module lazily — raises clear error if not installed
    weasyprint = lazy_import("weasyprint", extra="pdf")

    # Verify all modules for an extra are available
    require_extra("db", "querysource", "psycopg2")

This module uses only Python stdlib — no external dependencies.

## Functions

- `def lazy_import(module_path: str, package_name: str | None=None, extra: str | None=None) -> ModuleType` — Import a module lazily, raising a clear error if not installed.
- `def require_extra(extra: str, *modules: str) -> None` — Verify that all required modules for an extras group are importable.
