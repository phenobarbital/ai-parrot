"""FEAT-438 (OpenAI-Compatible Client Base) live smoke scripts.

See ``_runner.py`` for the shared helper each ``smoke_<provider>.py``
script uses. Run any script directly, e.g.::

    python examples/clients/smoke/smoke_openai.py

Each script is credential-gated (skip-if-no-key) and safe to run
repeatedly — no state, tiny ``max_tokens``, cheap models.
"""
