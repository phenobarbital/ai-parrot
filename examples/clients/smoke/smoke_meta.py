"""FEAT-526 smoke script — Meta Model API (MetaClient, Muse Spark family).

Exercises ask() / ask()+tool / invoke() against Meta's Muse Spark model on
the Responses API path (``use_responses=True``, the default).

.. warning::
    Uses ``muse-spark-1.3-contributor`` — the Contributor tier, which
    grants Meta permission to **train on prompts and completions**. This
    is intentional for a synthetic smoke-test prompt only; never adopt
    this model id as a library default or for real user content. The
    Standard-tier default is ``muse-spark-1.3``.

Usage:
    python examples/clients/smoke/smoke_meta.py

Environment Variables:
    META_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="meta",
        model="muse-spark-1.3-contributor",
        env_vars=["META_API_KEY"],
    )
