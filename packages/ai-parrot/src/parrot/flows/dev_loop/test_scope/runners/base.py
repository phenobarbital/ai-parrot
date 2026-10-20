"""Runner adapter protocol and launcher normalisation (FEAT-709 M1). Stdlib only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from ..contract import _strip_uv_run_prefix, strip_env_prefix
from ..datatypes import Invocation, RunReport, TestTarget
from ..policy import ScopePolicy

EXCERPT_MAX_LINES: int = 30
DEFAULT_TIMEOUTS: Mapping[str, int] = {"pytest": 60, "vitest": 120, "cargo": 300, "parrot-e2e": 900}
LAUNCHER_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("uv", "run"),
    ("python", "-m"),
    ("python3", "-m"),
    ("pnpm", "exec"),
    ("pnpm", "run"),
    ("npx",),
)


def normalize_launcher_argv(argv: Sequence[str], *, pnpm_test_is_vitest: bool = True) -> list[str]:
    """Strip env assignments and known launcher chains; return the runner-headed argv.

    `pnpm test` / `pnpm run test` map to `vitest run` only when ``pnpm_test_is_vitest``.
    An unknown or ambiguous chain is returned unchanged (callers then match nothing).
    """
    normalized = strip_env_prefix(argv)
    while normalized:
        head = PurePosixPath(normalized[0]).name
        if head == "uv" and len(normalized) >= 2 and normalized[1] == "run":
            normalized = _strip_uv_run_prefix(normalized)
        elif head in {"python", "python3"} and len(normalized) >= 2 and normalized[1] == "-m":
            normalized = normalized[2:]
        elif head == "pnpm" and len(normalized) >= 2 and normalized[1] == "test":
            if not pnpm_test_is_vitest:
                return normalized
            normalized = ["vitest", "run", *normalized[2:]]
        elif head == "pnpm" and len(normalized) >= 3 and normalized[1:3] == ["run", "test"]:
            if not pnpm_test_is_vitest:
                return normalized
            normalized = ["vitest", "run", *normalized[3:]]
        elif head == "pnpm" and len(normalized) >= 3 and normalized[1] in {"exec", "run"}:
            normalized = normalized[2:]
        elif head == "npx" and len(normalized) >= 2:
            normalized = normalized[1:]
        else:
            break

    if normalized:
        normalized[0] = PurePosixPath(normalized[0]).name
    return normalized


@runtime_checkable
class RunnerAdapter(Protocol):
    """One test runner. Implementations are stateless; settings arrive per call."""

    kind: str
    binaries: tuple[str, ...]
    default_tiers: frozenset[str]
    report_format: str

    def matches(self, argv: Sequence[str]) -> bool: ...

    def operands(self, argv: Sequence[str]) -> list[str] | None: ...

    def is_broad(self, argv: Sequence[str], *, worktree: Path | None) -> bool: ...

    def mirror_targets(self, changed: Sequence[str], *, worktree: Path, settings: Mapping[str, str]) -> list[str]: ...

    def distribution_of(self, target: str, *, settings: Mapping[str, str]) -> str: ...

    def invocation(
        self,
        targets: Sequence[TestTarget],
        *,
        distribution: str,
        worktree: Path,
        settings: Mapping[str, str],
        policy: ScopePolicy,
        report_path: str,
    ) -> Invocation: ...

    def parse_report(
        self,
        *,
        report_path: Path | None,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_s: float,
        timed_out: bool,
        suite: str,
    ) -> RunReport: ...

    def validate_settings(self, settings: Mapping[str, str], *, worktree: Path) -> list[str]: ...
