"""pytest conftest for the benchmarks package.

Benchmarks are skipped in normal test runs.  Pass ``--benchmark-only`` (or
``--benchmark-enable``) to activate them::

    pytest --benchmark-only packages/ai-parrot/tests/benchmarks/ -v
"""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config, items):
    """Skip all benchmark-marked tests unless ``--benchmark-only`` is set."""
    # pytest-benchmark sets config.option.benchmark_only when --benchmark-only
    # is passed.  Fall back to False if the attribute is absent (pytest-benchmark
    # not installed).
    benchmark_only = getattr(config.option, "benchmark_only", False)
    benchmark_enable = getattr(config.option, "benchmark_enable", False)
    if benchmark_only or benchmark_enable:
        return
    skip_marker = pytest.mark.skip(
        reason="Benchmarks are skipped in normal runs. "
               "Use --benchmark-only to run them."
    )
    for item in items:
        if "benchmark" in item.keywords:
            item.add_marker(skip_marker)
