"""Regression scenarios for FEAT-584; use isolated fixtures, never live providers.

TASK-3569 (R9 / M9): the `claude-hook` fast path must never pay the cost of
importing the ADR decision plane (`decisions.cli` -> `decisions.service` ->
`structural.service`), `pandas` or `parrot.clients.base` — those are now
loaded lazily by `LazyAdrGroup` only when an `adr` subcommand is actually
resolved. This module exercises the real subprocess (never an
already-imported in-process callback) so the measurement reflects the
process's actual import cost, plus the ADR command surface's preserved
compatibility through the lazy proxy.

FEAT-595: every hook launch now goes through the real ``wikitoolkit``
console entry (``parrot.knowledge.wiki.entry:main``), which dispatches
``claude-hook`` without importing the click CLI; the hook runtime itself
rejects non-search payloads before loading the pydantic config. The warm
benchmark therefore measures two paths — the common prefilter path (hard
p50 < 300 ms) and the config path (reported, warn-only).
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import subprocess
import sys
import time
import warnings
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import wiki
from parrot.knowledge.wiki.decisions.cli import adr as _real_adr_group
from parrot.knowledge.wiki.lazy_commands import LazyAdrGroup

logger = logging.getLogger(__name__)

# The worktree's own package sources must shadow whatever `parrot` is
# installed (editable) into the active venv's site-packages — otherwise a
# subprocess launched with a bare `sys.executable` would resolve modules
# from a *different* checkout (e.g. the main repo) than the one these
# tests run against, silently measuring/testing stale code. Mirrors
# test_mcp_server.py's subprocess isolation in this same directory.
_SRC_ROOTS = [str(Path(__file__).resolve().parents[4] / "ai-parrot" / "src")]

#: Modules the eager ADR registration used to pull into every `wikitoolkit`
#: invocation (spec R9 / AC23). None of these may appear in the hook's
#: fast-path import trace once ADR registration is lazy.
_BANNED_IMPORT_PREFIXES = (
    "parrot.knowledge.wiki.decisions.cli",
    "parrot.knowledge.wiki.decisions.service",
    "parrot.knowledge.wiki.decisions.render",
    "parrot.knowledge.wiki.decisions.repository",
    "parrot.knowledge.wiki.decisions.review",
    "parrot.knowledge.wiki.decisions.generation",
    "parrot.knowledge.wiki.decisions.evidence",
    "parrot.knowledge.wiki.decisions.parser",
    "parrot.knowledge.wiki.structural.service",
    "parrot.clients",
    "pandas",
)

#: R9's aspirational target for a documented, disk-cache-warmed runner.
_TARGET_P50_MS = 300.0
#: Generous ceiling that still catches a genuine regression (e.g. a banned
#: import creeping back in, or a hang) without being sensitive to sandbox
#: scheduling/process-creation overhead this suite otherwise can't control.
_REGRESSION_CEILING_MS = 2500.0
#: How many subprocess launches count toward the warm p50/p95 (R9).
_WARM_RUNS = 20


def _subprocess_env() -> dict:
    """Env for a hook subprocess that imports THIS worktree's sources."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([*_SRC_ROOTS, existing]) if existing else os.pathsep.join(_SRC_ROOTS)
    return env


#: What the generated ``wikitoolkit`` console shim does, spelled out so the
#: test exercises this checkout's ``entry`` module regardless of which
#: checkout the shared venv's shim was generated from.
_ENTRY_CODE = (
    "import sys; sys.argv = ['wikitoolkit', *sys.argv[1:]]; " "from parrot.knowledge.wiki.entry import main; main()"
)

#: Modules the dedicated hook entry must never load (FEAT-595, AC2/AC3).
_HOOK_PATH_BANNED = (
    "parrot.knowledge.wiki.cli",
    "parrot.knowledge.wiki.claude_code.installer",
    "parrot.knowledge.wiki.repo_scan",
    "click",
)

#: Additionally banned when the stdlib prefilter rejects the payload (AC2).
_PREFILTER_PATH_BANNED = (*_HOOK_PATH_BANNED, "parrot.knowledge.wiki.project", "pydantic")


def _run_hook(payload: dict, *, importtime: bool = False, via_cli: bool = False) -> subprocess.CompletedProcess:
    """Launch a real ``wikitoolkit claude-hook`` subprocess.

    Args:
        payload: Hook payload written to stdin.
        importtime: Add ``-X importtime`` so stderr carries the import trace.
        via_cli: Launch the legacy ``python -m parrot.knowledge.wiki.cli claude-hook``
            path instead of the console entry (reference output for AC3).
    """
    args = [sys.executable]
    if importtime:
        args += ["-X", "importtime"]
    if via_cli:
        args += ["-m", "parrot.knowledge.wiki.cli", "claude-hook"]
    else:
        args += ["-c", _ENTRY_CODE, "claude-hook"]
    return subprocess.run(
        args,
        input=json.dumps(payload).encode(),
        env=_subprocess_env(),
        capture_output=True,
        timeout=15,
        check=False,
    )


def _parse_importtime_modules(stderr: bytes) -> set[str]:
    """Extract every module name ``-X importtime`` reported importing."""
    modules: set[str] = set()
    for line in stderr.decode(errors="replace").splitlines():
        if not line.startswith("import time:"):
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        modules.add(parts[2].strip())
    return modules


def _offenders(modules: set[str], banned: tuple[str, ...]) -> set[str]:
    """Modules from ``modules`` that are (or live under) a ``banned`` prefix."""
    return {mod for mod in modules if any(mod == prefix or mod.startswith(f"{prefix}.") for prefix in banned)}


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted sequence."""
    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[index]


def _build_project(root: Path) -> None:
    """Minimal on-disk fixture that makes `is_built()`/`find_project_root()`
    true without running the real (heavy) `wikitoolkit build` pipeline."""
    (root / ".git").mkdir(parents=True)
    wiki_dir = root / ".parrot" / "wiki"
    wiki_dir.mkdir(parents=True)
    (wiki_dir / "wiki.db").write_bytes(b"")  # sqlite `is_built()` is an existence check.


def test_hook_process_protocol_and_imports(tmp_path: Path) -> None:
    """A fresh hook process emits only protocol JSON and does not import ADR service, pandas or clients.base."""
    project_root = tmp_path / "repo"
    _build_project(project_root)

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": "some_module.py"},
        "cwd": str(project_root),
    }
    result = _run_hook(payload, importtime=True)

    assert result.returncode == 0, result.stderr.decode(errors="replace")

    # stdout is protocol-only. The fixture above (built wiki + qualifying
    # Read) is deliberately set up so this exercises the real nudge
    # response, not just the quieter empty-stdout/no-nudge branch.
    stdout_text = result.stdout.decode()
    assert stdout_text.strip(), "expected a nudge response for a fresh Read on a built wiki project"
    response = json.loads(stdout_text)
    assert response["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert response["suppressOutput"] is True
    assert "additionalContext" in response["hookSpecificOutput"]

    stderr_text = result.stderr.decode(errors="replace")
    non_importtime_lines = [line for line in stderr_text.splitlines() if not line.startswith("import time:")]
    assert not any("Traceback" in line for line in non_importtime_lines), stderr_text

    imported = _parse_importtime_modules(result.stderr)
    offenders = {
        mod
        for mod in imported
        if any(mod == prefix or mod.startswith(f"{prefix}.") for prefix in _BANNED_IMPORT_PREFIXES)
    }
    assert not offenders, f"hook fast path pulled in banned modules: {sorted(offenders)}"


def test_adr_help_options_and_completion(tmp_path: Path) -> None:
    """Lazy ADR delegates every subcommand with unchanged callback, options, help and completion."""
    runner = CliRunner()

    # 1. Registration: `wiki` wires the `adr` name to our lazy proxy, never
    #    the real group object directly.
    lazy_group = wiki.commands["adr"]
    assert isinstance(lazy_group, LazyAdrGroup)
    assert lazy_group is not _real_adr_group

    # 2. Delegation is exact object identity, not a re-implementation: every
    #    real ADR subcommand (with its own callback/options/errors) is the
    #    SAME Command object whether resolved through the lazy proxy or the
    #    real group directly — this is what "completion never lies" means
    #    in practice, since Click's shell completion walks get_command too.
    ctx = click.Context(wiki)
    real_names = _real_adr_group.list_commands(ctx)
    assert real_names, "sanity: the real ADR group must expose subcommands"
    assert lazy_group.list_commands(ctx) == real_names
    for name in real_names:
        assert lazy_group.get_command(ctx, name) is _real_adr_group.get_command(ctx, name)
    assert lazy_group.get_command(ctx, "not-a-real-command") is None

    # 3. `wiki adr --help` lists every real subcommand and preserves the
    #    group's own help text — served without needing the delegated
    #    lookup above (the static help/name passed at registration).
    help_result = runner.invoke(wiki, ["adr", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert _real_adr_group.help in help_result.output
    for name in real_names:
        assert name in help_result.output

    # 4. Preserved per-command options/errors: invoking a real subcommand
    #    through the lazy-registered `wiki` app produces the identical
    #    click usage error as invoking the real group directly (mandatory
    #    --actor on `adr review`), proving the delegated Command's own
    #    parameter validation runs unchanged.
    lazy_result = runner.invoke(
        wiki, ["adr", "review", "adr:candidate:a", "--action", "accept", "--expected-revision", "1"]
    )
    direct_result = runner.invoke(
        _real_adr_group, ["review", "adr:candidate:a", "--action", "accept", "--expected-revision", "1"]
    )
    assert lazy_result.exit_code == direct_result.exit_code == 2
    assert "--actor" in lazy_result.output

    # 5. Per-subcommand `--help` (options/docstring/errors) is identical
    #    whether reached through the lazy proxy or the real group — except
    #    the first "Usage: ..." line, which legitimately differs because it
    #    spells out the full invocation chain (`wiki adr export` vs. the
    #    real group invoked standalone as `export`).
    for name in real_names:
        lazy_help = runner.invoke(wiki, ["adr", name, "--help"])
        direct_help = runner.invoke(_real_adr_group, [name, "--help"])
        assert lazy_help.exit_code == direct_help.exit_code == 0
        lazy_body = lazy_help.output.split("\n", 1)[1]
        direct_body = direct_help.output.split("\n", 1)[1]
        assert lazy_body == direct_body


def _fresh_modules(code: str) -> set[str]:
    """``sys.modules`` keys of a fresh interpreter after running ``code`` against this checkout."""
    script = f"{code}\nimport json, sys\nprint(json.dumps(sorted(sys.modules)))"
    result = subprocess.run(
        [sys.executable, "-c", script], env=_subprocess_env(), capture_output=True, timeout=30, check=True
    )
    return set(json.loads(result.stdout.decode().strip().splitlines()[-1]))


def _bash_payload(cwd: Path, command: str = "git status") -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _grep_payload(cwd: Path) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": "Grep", "tool_input": {"pattern": "foo"}, "cwd": str(cwd)}


def test_entry_module_imports_no_cli() -> None:
    """AC1: importing the console entry loads neither click, pydantic nor the wiki CLI."""
    modules = _fresh_modules("import parrot.knowledge.wiki.entry")
    assert not _offenders(modules, ("click", "pydantic", "parrot.knowledge.wiki.cli")), sorted(modules)


def test_entry_hook_argv_matches_installed_subcommand() -> None:
    """The literal the entry dispatches on is the subcommand the installers write."""
    from parrot.knowledge.wiki import entry
    from parrot.knowledge.wiki.claude_code import assets

    assert entry.HOOK_ARGV == [assets.HOOK_SUBCOMMAND]


def test_prefilter_path_imports(tmp_path: Path) -> None:
    """AC2: a non-search Bash payload exits 0 silently without loading the config or the CLI."""
    project_root = tmp_path / "repo"
    _build_project(project_root)
    result = _run_hook(_bash_payload(project_root), importtime=True)

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stdout == b""
    offenders = _offenders(_parse_importtime_modules(result.stderr), _PREFILTER_PATH_BANNED)
    assert not offenders, f"prefilter path pulled in: {sorted(offenders)}"


def test_config_path_matches_cli(tmp_path: Path) -> None:
    """AC3: a Grep nudge through the entry is byte-equal to the legacy CLI path and skips CLI/installer/scanner."""
    # Two separate fixture repos: each run claims its own fresh throttle window.
    entry_repo, cli_repo = tmp_path / "entry", tmp_path / "cli"
    _build_project(entry_repo)
    _build_project(cli_repo)

    via_entry = _run_hook(_grep_payload(entry_repo), importtime=True)
    via_cli = _run_hook(_grep_payload(cli_repo), via_cli=True)

    assert via_entry.returncode == via_cli.returncode == 0, via_entry.stderr.decode(errors="replace")
    assert via_entry.stdout.strip(), "expected a nudge for Grep on a built wiki project"
    assert via_entry.stdout == via_cli.stdout
    offenders = _offenders(_parse_importtime_modules(via_entry.stderr), _HOOK_PATH_BANNED)
    assert not offenders, f"config path pulled in: {sorted(offenders)}"


def test_entry_falls_through_to_cli() -> None:
    """AC6: any non-hook argv is handed to the click CLI unchanged (same --help output)."""
    via_entry = subprocess.run(
        [sys.executable, "-c", _ENTRY_CODE, "--help"], env=_subprocess_env(), capture_output=True, timeout=60
    )
    via_cli = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.argv = ['wikitoolkit', '--help']; " "from parrot.knowledge.wiki.cli import main; main()",
        ],
        env=_subprocess_env(),
        capture_output=True,
        timeout=60,
    )
    assert via_entry.returncode == via_cli.returncode == 0, via_entry.stderr.decode(errors="replace")
    assert via_entry.stdout == via_cli.stdout
    assert b"claude-hook" not in via_entry.stdout  # still hidden


def _benchmark(payload: dict) -> dict:
    """One cold launch plus ``_WARM_RUNS`` warm fresh-process launches of ``payload``."""

    def _measure() -> float:
        t0 = time.perf_counter()
        result = _run_hook(payload)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return elapsed_ms

    cold_ms = _measure()
    warm = sorted(_measure() for _ in range(_WARM_RUNS))
    p50 = statistics.median(warm)
    return {
        "cold_ms": cold_ms,
        "warm_p50_ms": p50,
        "warm_p95_ms": _percentile(warm, 95),
        "warm_samples_ms": warm,
        "target_met": p50 < _TARGET_P50_MS,
    }


def test_warm_process_startup(tmp_path: Path) -> None:
    """Twenty warm launches of the real entry: prefilter p50 < 300ms (hard); config path reported."""
    project_root = tmp_path / "repo"
    _build_project(project_root)

    prefilter = _benchmark(_bash_payload(project_root))
    # Grep on a built repo loads the config every time; after the first launch the
    # throttle window is claimed, so launches measure config load without output.
    config_path = _benchmark(_grep_payload(project_root))

    evidence = {
        "runner": {"platform": sys.platform, "python": sys.version},
        "entry": "parrot.knowledge.wiki.entry:main",
        "target_p50_ms": _TARGET_P50_MS,
        "prefilter_path": prefilter,
        "config_path": config_path,
    }
    try:
        logs_dir = Path(__file__).resolve().parents[5] / "artifacts" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "hook_startup_benchmark.json").write_text(json.dumps(evidence, indent=2))
    except OSError:  # pragma: no cover - evidence capture is best-effort
        logger.warning("could not persist hook startup benchmark evidence", exc_info=True)

    # AC4: the common path is stdlib-only and far below target, so it is a hard gate.
    assert prefilter["target_met"], evidence
    # The config path still pays pydantic + the project config; report it honestly.
    if not config_path["target_met"]:
        warnings.warn(
            f"config-path warm p50={config_path['warm_p50_ms']:.1f}ms >= {_TARGET_P50_MS:.0f}ms "
            f"(p95={config_path['warm_p95_ms']:.1f}ms); cost is pydantic + WikiProjectConfig load.",
            stacklevel=1,
        )
    for path in (prefilter, config_path):
        assert path["warm_p50_ms"] < _REGRESSION_CEILING_MS, evidence
        assert path["warm_p95_ms"] < _REGRESSION_CEILING_MS, evidence
