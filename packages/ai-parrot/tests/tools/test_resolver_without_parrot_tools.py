"""Core toolkits must serve when the optional ai-parrot-tools distribution is absent (FEAT-633 C34/C35)."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

BLOCK = textwrap.dedent("""
    import sys
    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name == "parrot_tools" or name.startswith("parrot_tools."):
                raise ModuleNotFoundError(f"No module named {name!r}")
    sys.meta_path.insert(0, _Block())
    """)


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": os.pathsep.join(os.path.abspath(p) for p in sys.path if p)}


def _run(code: str, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", BLOCK + code],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=_env(),
        input=stdin,
        timeout=120,
        check=False,
    )


def test_builtin_classes_skip_wiki_without_parrot_tools(tmp_path: Path) -> None:
    proc = _run(
        "from parrot.tools.resolver import _builtin_classes\nprint(sorted(_builtin_classes()))",
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == "['dataset_manager', 'infographic']"


def test_bounded_source_lists_tools_without_parrot_tools(tmp_path: Path) -> None:
    proc = _run(
        "from parrot.tools.optimizations.reader import BoundedSourceToolkit\n"
        f"print(len(BoundedSourceToolkit(repo_root={str(tmp_path)!r}).get_tools()))",
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip().splitlines()[-1]) > 0


def test_sdd_coder_tools_without_parrot_tools(tmp_path: Path) -> None:
    proc = _run(
        "from parrot.flows.dev_loop.sdd_coder.toolkit import SddCoderToolkit\n"
        "from parrot.mcp.toolkit_seed import seed_toolkit_sections\n"
        "from parrot.mcp.toolkit_config import load_toolkits_config\n"
        f"from pathlib import Path\nroot = Path({str(tmp_path)!r})\n"
        "seed_toolkit_sections(root, ['sdd-coder'])\n"
        "kw = load_toolkits_config(root).toolkits['sdd-coder'].kwargs\n"
        "print(len(SddCoderToolkit(**kw).get_tools()))",
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert int(proc.stdout.strip().splitlines()[-1]) > 0


def test_mcp_local_bounded_source_handshake_without_parrot_tools(tmp_path: Path) -> None:
    from parrot.mcp.toolkit_seed import seed_toolkit_sections

    seed_toolkit_sections(tmp_path, ["bounded-source"])
    config = tmp_path / ".parrot" / "mcp-toolkits.yaml"
    request = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    )
    code = (
        "import sys\nfrom parrot.launcher import main_parrot\n"
        f"sys.argv = ['parrot', 'mcp-local', 'bounded-source', '--config', {str(config)!r}]\nmain_parrot()\n"
    )
    proc = _run(code, tmp_path, stdin=request + "\n")
    first = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else ""
    assert first, proc.stderr
    assert "result" in json.loads(first), (proc.stdout, proc.stderr)


def test_wiki_still_builtin_when_parrot_tools_present() -> None:
    import pytest

    pytest.importorskip("parrot_tools")
    from parrot.knowledge.wiki import LLMWikiToolkit
    from parrot.tools.resolver import _builtin_classes

    assert _builtin_classes()["wiki"] is LLMWikiToolkit
