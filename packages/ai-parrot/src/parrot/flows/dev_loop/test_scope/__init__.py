"""Deterministic test-scope kernel for the SDD cycle (FEAT-563).

Stdlib-only: importable as ``parrot.flows.dev_loop.test_scope`` and, by path, as top-level
``test_scope`` from the system-python native hook. Never import ``models`` (Pydantic) here.
"""

from .contract import VALIDATION_HEADING, is_broad_pytest, is_pytest_invocation, parse_validation_commands
from .datatypes import AttemptContext, CoreHit, LedgerEntry, PytestInvocation, ScopePlan, TestTarget
from .mirror import deepest_existing_dir, distribution_of, prune_nested, pytest_target_for, pytest_targets
from .select import changed_files, plan_tests

__all__ = [
    "AttemptContext",
    "CoreHit",
    "LedgerEntry",
    "PytestInvocation",
    "ScopePlan",
    "TestTarget",
    "VALIDATION_HEADING",
    "changed_files",
    "deepest_existing_dir",
    "distribution_of",
    "is_broad_pytest",
    "is_pytest_invocation",
    "parse_validation_commands",
    "plan_tests",
    "prune_nested",
    "pytest_target_for",
    "pytest_targets",
]
