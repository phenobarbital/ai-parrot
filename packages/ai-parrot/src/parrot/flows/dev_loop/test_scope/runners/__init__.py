"""Test runner adapters for the test-scope kernel (FEAT-709). Stdlib only."""

from .base import EXCERPT_MAX_LINES, RunnerAdapter, normalize_launcher_argv
from .registry import CONFIG_PATH, RunnerRegistry, load_registry

__all__ = [
    "CONFIG_PATH",
    "EXCERPT_MAX_LINES",
    "RunnerAdapter",
    "RunnerRegistry",
    "load_registry",
    "normalize_launcher_argv",
]
