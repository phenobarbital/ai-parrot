"""What `import parrot.clients.base` is allowed to drag in.

Every module that touches an LLM client imports this one, so a single eager
import here is paid by the whole framework -- the server, every bot, and
every CLI. These are subprocess checks on purpose: sys.modules is global and
a sibling test that imported the module under scrutiny would mask the
regression.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

#: Modules that must NOT be imported as a side effect of importing the client
#: base. Each is reachable from a feature that only some callers use, and each
#: was, at some point, imported eagerly for a name used in an annotation or in
#: one rarely-called factory.
FORBIDDEN_ON_IMPORT = [
    "parrot.tools.pythonrepl",
    "parrot.security.redaction",
    "parrot.interfaces.documentdb",
]


def _import_probe(module: str, forbidden: str) -> subprocess.CompletedProcess[str]:
    """Import ``module`` in a clean interpreter and report on ``forbidden``."""
    code = f"import sys; import {module}; print({forbidden!r} in sys.modules)"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("forbidden", FORBIDDEN_ON_IMPORT)
def test_client_base_does_not_import(forbidden: str):
    """The heavy optional subsystems stay unimported until something uses them."""
    result = _import_probe("parrot.clients.base", forbidden)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("False"), (
        f"importing parrot.clients.base pulled in {forbidden!r}. "
        "Import it inside the function that needs it, or under TYPE_CHECKING "
        "when it is only an annotation."
    )


def test_python_repl_tool_is_still_reachable():
    """Laziness must not cost the caller the feature (or the annotation)."""
    from parrot.clients.base import register_python_tool

    class _Client:
        def register_tool(self, **kwargs):
            self.registered = kwargs

    client = _Client()
    tool = register_python_tool(client, report_dir=None)
    assert type(tool).__name__ == "PythonREPLTool"
    assert client.registered["name"] == "python_repl"
