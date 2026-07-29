"""Re-export shim for the dev-loop LLM backend catalog (FEAT-388).

The catalog itself moved to :mod:`parrot.flows.dev_loop.catalog` (Module 1
of FEAT-388) so both the demo server and the ``parrot devloop`` CLI share
one source of truth. This module exists only so
``examples/dev_loop/server.py`` (``import llm_catalog``, module-attribute
access) keeps working unchanged.

Do not add logic here — every public name below must stay identical
(``is``, not just ``==``) to its counterpart on
:mod:`parrot.flows.dev_loop.catalog`. See
``packages/ai-parrot/tests/flows/dev_loop/test_catalog.py`` for the
shim-integrity guard.
"""

from __future__ import annotations

from parrot.flows.dev_loop.catalog import (
    ADVERSARIAL_BACKEND,
    BACKENDS,
    JUDGE_BACKENDS,
    PRIMARY_REVIEW_BACKENDS,
    BackendInfo,
    backends_for_role,
    catalog_payload,
    default_judge_panel_payload,
    effective_default_model,
    get_backend,
)

__all__ = [
    "ADVERSARIAL_BACKEND",
    "BACKENDS",
    "JUDGE_BACKENDS",
    "PRIMARY_REVIEW_BACKENDS",
    "BackendInfo",
    "backends_for_role",
    "catalog_payload",
    "default_judge_panel_payload",
    "effective_default_model",
    "get_backend",
]
