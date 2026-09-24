"""Capture this process's real launch-time working directory.

Import this FIRST in any pilot seat entry point, before anything that
imports ``parrot`` -- ``navconfig``'s initialization, triggered as a side
effect of ``import parrot`` (e.g. ``from parrot.bots.agent import
Agent``), silently calls ``os.chdir()`` to the main ai-parrot checkout
root. Without capturing the true cwd before that import runs, a seat
launched by ``benchmarks.sdd_lsp.runner`` via
``asyncio.create_subprocess_exec(cwd=attempt_dir)`` would silently lose
its intended working directory and operate against the wrong tree
entirely -- found via TASK-3514's own live smoke test (2026-09-20): the
seat's tools wandered the whole ai-parrot checkout instead of its tiny
attempt fixture, guessing absolute host paths, because ``Path.cwd()``
called after ``import parrot`` had already resolved to the checkout root.

This module does nothing else and imports nothing beyond ``os``, so
importing it first is always safe regardless of import order elsewhere.
"""

from __future__ import annotations

import os

LAUNCH_CWD: str = os.getcwd()

__all__ = ("LAUNCH_CWD",)
