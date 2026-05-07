"""Verify importing ``parrot_formdesigner.ui`` does NOT pull ``parrot_formdesigner.api``."""

from __future__ import annotations

import importlib
import sys


def test_importing_ui_does_not_pull_api():
    """``import parrot_formdesigner.ui`` must NOT trigger
    ``parrot_formdesigner.api`` import.

    This is the inverse of the metadata-only init test for the top-level
    package — ``ui/`` is independently mountable from ``api/``.
    """
    # Drop both subpackages to force a fresh import.
    for k in list(sys.modules):
        if k.startswith("parrot_formdesigner.ui") or k.startswith(
            "parrot_formdesigner.api"
        ):
            sys.modules.pop(k, None)

    importlib.import_module("parrot_formdesigner.ui")

    api_loaded = any(
        k.startswith("parrot_formdesigner.api") for k in sys.modules
    )
    assert not api_loaded, (
        "parrot_formdesigner.ui transitively imported parrot_formdesigner.api"
    )


def test_ui_setup_form_ui_exported():
    from parrot_formdesigner.ui import setup_form_ui

    assert callable(setup_form_ui)
