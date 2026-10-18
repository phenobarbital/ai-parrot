"""Deterministic test-scope kernel for the SDD cycle (FEAT-563).

Stdlib-only: importable as ``parrot.flows.dev_loop.test_scope`` and, by path, as top-level
``test_scope`` from the system-python native hook. Never import ``models`` (Pydantic) here.
"""

from .contract import (
    VALIDATION_HEADING,
    contract_from_index_header,
    is_broad_pytest,
    is_pytest_invocation,
    parse_spec_contract,
    parse_validation_commands,
)
from .datatypes import (
    AttemptContext,
    BaselineVerdict,
    CoreHit,
    GreenCacheEntry,
    LedgerEntry,
    PytestInvocation,
    ScopePlan,
    TestContract,
    TestTarget,
)
from .mirror import (
    deepest_existing_dir,
    distribution_of,
    prune_nested,
    pytest_file_targets,
    pytest_target_for,
    pytest_targets,
)
from .select import changed_files, plan_tests

__all__ = [
    "AttemptContext",
    "BaselineVerdict",
    "CoreHit",
    "GreenCacheEntry",
    "LedgerEntry",
    "PytestInvocation",
    "ScopePlan",
    "TestContract",
    "TestTarget",
    "VALIDATION_HEADING",
    "changed_files",
    "contract_from_index_header",
    "deepest_existing_dir",
    "distribution_of",
    "is_broad_pytest",
    "is_pytest_invocation",
    "parse_validation_commands",
    "parse_spec_contract",
    "plan_tests",
    "prune_nested",
    "pytest_file_targets",
    "pytest_target_for",
    "pytest_targets",
]
