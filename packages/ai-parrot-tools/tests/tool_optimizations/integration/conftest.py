"""Fixtures for the FEAT-543 integration suite.

These tests exercise the whole path a host actually uses:
``parrot mcp-local <name>`` -> ``create_toolkit_mcp_server`` ->
``StdioMCPServer`` -> ``MCPToolAdapter`` -> toolkit.
"""

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

#: integration -> tool_optimizations -> tests -> ai-parrot-tools -> packages -> repo root
REPO_ROOT = Path(__file__).resolve().parents[5]
CORE_SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
TOOLS_SRC = REPO_ROOT / "packages" / "ai-parrot-tools" / "src"
ARTIFACT_LOGS = REPO_ROOT / "artifacts" / "logs"

#: Bootstrap used to run `parrot ...` in a subprocess, mirroring
#: tests/mcp/test_mcp_local_e2e.py but with the tools package on sys.path.
BOOTSTRAP = textwrap.dedent(f"""
    import sys, types
    sys.path.insert(0, {str(CORE_SRC)!r})
    sys.path.insert(0, {str(TOOLS_SRC)!r})

    try:
        import parrot.utils.types  # noqa: F401
    except ImportError:
        _m = types.ModuleType("parrot.utils.types")
        class SafeDict(dict):
            def __missing__(self, key):
                return None
        _m.SafeDict = SafeDict
        sys.modules["parrot.utils.types"] = _m

    try:
        import parrot.utils.parsers.toml  # noqa: F401
    except ImportError:
        _pkg = types.ModuleType("parrot.utils.parsers")
        _mod = types.ModuleType("parrot.utils.parsers.toml")
        class TOMLParser:
            def __init__(self, *a, **kw):
                pass
            def parse(self, content):
                import tomllib
                return tomllib.loads(content)
        _mod.TOMLParser = TOMLParser
        _pkg.TOMLParser = TOMLParser
        sys.modules["parrot.utils.parsers"] = _pkg
        sys.modules["parrot.utils.parsers.toml"] = _mod

    from parrot.cli import cli
    cli(prog_name="parrot")
    """)

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "LC_ALL": "C",
    "LANG": "C",
}


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command with the deterministic fixture environment."""
    return subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=check)


def worker_env() -> dict:
    """Environment giving a subprocess access to the worktree's packages."""
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join([str(CORE_SRC), str(TOOLS_SRC), existing]).rstrip(os.pathsep)
    return env


def write_toolkits_yaml(repo: Path) -> Path:
    """Write a .parrot/mcp-toolkits.yaml exposing the three toolkits."""
    config = repo / ".parrot" / "mcp-toolkits.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "toolkits:\n"
        "  local-git:\n"
        "    class: parrot_tools.tool_optimizations.git.LocalGitToolkit\n"
        "    kwargs:\n"
        f"      repo_root: {repo}\n"
        "  bounded-source:\n"
        "    class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit\n"
        "    kwargs:\n"
        f"      repo_root: {repo}\n"
        "  targeted-writer:\n"
        "    class: parrot_tools.tool_optimizations.writer.TargetedWriterToolkit\n"
        "    kwargs:\n"
        f"      repo_root: {repo}\n"
    )
    return config


@pytest.fixture
def tmp_repo_with_yaml(tmp_path):
    """A git repo with source files and an MCP toolkits config."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "a.py").write_text("print('a')\n")
    (repo / "big.py").write_text("".join(f"line{i}\n" for i in range(1, 401)))
    git(repo, "add", "a.py", "big.py")
    git(repo, "commit", "-q", "-m", "base")
    return repo, write_toolkits_yaml(repo)


@pytest.fixture(scope="session", autouse=True)
def evidence_log():
    """Create the evidence log directory for this task's artefacts."""
    ARTIFACT_LOGS.mkdir(parents=True, exist_ok=True)
    log = ARTIFACT_LOGS / "TASK-3091-integration.log"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n=== integration run {datetime.now(timezone.utc).isoformat()} ===\n")
    return log


@pytest.fixture(autouse=True)
def record_outcome(request, evidence_log):
    """Append each test's name to the evidence log."""
    yield
    with evidence_log.open("a", encoding="utf-8") as handle:
        handle.write(f"{request.node.nodeid}\n")


def record_json(name: str, payload: dict) -> Path:
    """Write a JSON evidence artefact under artifacts/logs."""
    ARTIFACT_LOGS.mkdir(parents=True, exist_ok=True)
    target = ARTIFACT_LOGS / name
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target
