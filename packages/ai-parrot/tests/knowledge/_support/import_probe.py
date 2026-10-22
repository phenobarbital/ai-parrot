"""Fresh-interpreter import probe for the FEAT-540 import ceilings."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel

FORBIDDEN: tuple[str, ...] = (
    "navconfig",
    "parrot.conf",
    "navigator_eventbus",
    "asyncdb",
    "pandas",
    "faiss",
    "pyarrow",
    "redis",
    "asyncpg",
)

_SRC_ROOT = Path(__file__).resolve().parents[3] / "src"

_PROBE = (
    "import importlib, json, sys\n"
    "sys.path.insert(0, sys.argv[2])\n"
    "err = None\n"
    "try:\n"
    "    importlib.import_module(sys.argv[1])\n"
    "except Exception as exc:\n"
    "    err = f'{type(exc).__name__}: {exc}'\n"
    "print(json.dumps({'count': len(sys.modules), 'modules': sorted(sys.modules), "
    "'python': sys.version, 'error': err}))\n"
)


class ImportProbeResult(BaseModel):
    """Outcome of importing one module in a fresh interpreter."""

    module: str
    count: int
    loaded_forbidden: list[str]
    python: str
    revision: str
    error: str | None = None
    modules: list[str]

    def has(self, module: str) -> bool:
        """Return whether the fresh interpreter loaded ``module`` exactly."""
        return module in self.modules


def run_import_probe(module: str, *, forbidden: tuple[str, ...] = FORBIDDEN) -> ImportProbeResult:
    """Import a module in ``python -I`` and report its isolated import footprint.

    Args:
        module: Fully-qualified module name to import.
        forbidden: Module prefixes that must remain unloaded.

    Returns:
        Import metadata, forbidden-prefix matches, and any import failure.
    """
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _PROBE, module, str(_SRC_ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    revision_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    revision = revision_proc.stdout.strip() or "unknown"
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    payload: dict[str, object] = {}
    parse_error: str | None = None
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            parse_error = f"invalid probe output: {exc}"
    else:
        parse_error = "probe emitted no JSON output"

    modules = payload.get("modules", [])
    if not isinstance(modules, list) or not all(isinstance(item, str) for item in modules):
        modules = []
        parse_error = parse_error or "probe returned an invalid module list"
    child_error = payload.get("error")
    error = parse_error or (str(child_error) if child_error else None)
    if proc.returncode:
        stderr = proc.stderr.strip()
        error = f"subprocess exited {proc.returncode}: {stderr}" if stderr else f"subprocess exited {proc.returncode}"

    return ImportProbeResult(
        module=module,
        count=int(payload.get("count", 0)),
        loaded_forbidden=[
            prefix for prefix in forbidden if any(name == prefix or name.startswith(prefix + ".") for name in modules)
        ],
        python=str(payload.get("python", sys.version)),
        revision=revision,
        error=error,
        modules=modules,
    )
