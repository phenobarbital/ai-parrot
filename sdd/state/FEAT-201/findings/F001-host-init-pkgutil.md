---
id: F001
query_id: Q001
type: read
intent: Read the host parrot package __init__.py to determine PEP 420 feasibility.
executed_at: 2026-05-28T00:00:00Z
duration_ms: 50
parent_id: null
depth: 0
---

# F001 — Host `parrot/__init__.py` already does pkgutil namespace extension

## Summary

The host `parrot/__init__.py` is **not empty** (31 lines), but its first
meaningful line is `__path__ = extend_path(__path__, __name__)` — the
classic pkgutil-style namespace mechanism. The comment is explicit:
*"Allow other packages (e.g. parrot-formdesigner) to extend the parrot
namespace."* The codebase therefore already supports sibling distributions
contributing submodules under `parrot.*`. The mechanism is **pkgutil**,
not pure PEP 420, but the user-visible outcome (byte-identical imports
across distributions) is the same.

## Citations

- path: `packages/ai-parrot/src/parrot/__init__.py`
  lines: 1-31
  symbol: `parrot/__init__.py`
  excerpt: |
    """Navigator Parrot. Basic Chatbots for Navigator Services."""
    import os
    import logging
    from pathlib import Path
    from pkgutil import extend_path

    # Allow other packages (e.g. parrot-formdesigner) to extend the parrot namespace
    __path__ = extend_path(__path__, __name__)
    from .version import (
        __author__, __author_email__, __description__, __title__, __version__
    )

    os.environ["USER_AGENT"] = "Parrot.AI/1.0"
    os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "false"

    def get_project_root() -> Path:
        return Path(__file__).parent.parent
    ABS_PATH = get_project_root()
    __all__ = ["__version__"]

## Notes

- pkgutil's `extend_path(__path__, __name__)` only extends `parrot.__path__`
  (the top-level). To make sub-package modules from a satellite
  distribution discoverable (e.g. `parrot.embeddings.huggingface` shipped
  from `ai-parrot-embeddings`), the SAME extension must be applied to
  `parrot.embeddings.__init__.py`, `parrot.stores.__init__.py`, and
  `parrot.rerankers.__init__.py` — they do NOT currently call
  `extend_path`. This is a small, mechanical change in core that FEAT-201
  must include.
- The host already declares its intent to be namespace-extensible — there
  is no architectural friction with the user's chosen approach.
