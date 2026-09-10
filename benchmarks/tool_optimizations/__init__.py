"""Reproducible benchmarks for the FEAT-543 tool optimizations.

The harness measures primary-model tokens, delegate tokens, latency and
correctness **separately**, and claims no savings percentage: fewer primary
tokens is not the same as fewer total tokens, and this package exists to
keep those two numbers visibly distinct.

Run offline (the default, free) with::

    python -m benchmarks.tool_optimizations --scenario all --runs 1
"""

__all__ = ()
