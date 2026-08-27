"""Static validator for Studio draft agents (FEAT-467 TASK-2513).

Pure static analysis — the draft source is NEVER imported or executed
here. That only happens on explicit activation (``POST
.../drafts/{name}/activate``), and only after this validator reports
``passed=True`` (spec §7 "Draft import side effects": the AST allowlist
must run BEFORE any import — the gate IS the security boundary).
"""

from __future__ import annotations

import ast

from .models import DraftValidationReport

# Only parrot's own namespace + parrot_tools may be imported by a draft.
_ALLOWED_TOP_LEVEL_PACKAGES = {"parrot", "parrot_tools"}

# SECURITY (adversarial-review fix): stdlib imports are ALLOWLISTED, not
# blanket-allowed. The previous rule ("any sys.stdlib_module_names
# member") let a draft `import os` / `import subprocess` and execute
# `os.system(...)` at module top level the moment it was activated —
# i.e. arbitrary command execution through the "safe" pipeline. Only
# modules with no process/filesystem/network/dynamic-import primitives
# (pathlib excepted — see note) are allowed; everything else (os, sys,
# subprocess, shutil, socket, importlib, ctypes, pickle, io, tempfile,
# builtins, ...) is rejected at validation time.
#
# NOTE on residual risk: this AST gate is defense-in-depth, not a
# sandbox. `parrot.*` is allowed by design and transitively reaches the
# stdlib, and `pathlib` is deliberately kept (ubiquitous in legitimate
# agent code) despite enabling file I/O. The actual trust boundary
# remains the explicit, owner-gated `POST .../activate` step — a draft
# NEVER executes without a human deliberately activating it.
_SAFE_STDLIB_MODULES = frozenset(
    {
        "abc",
        "array",
        "asyncio",
        "base64",
        "binascii",
        "bisect",
        "calendar",
        "collections",
        "contextlib",
        "copy",
        "dataclasses",
        "datetime",
        "decimal",
        "difflib",
        "enum",
        "fractions",
        "functools",
        "hashlib",
        "heapq",
        "hmac",
        "html",
        "itertools",
        "json",
        "logging",
        "math",
        "numbers",
        "operator",
        "pathlib",
        "pprint",
        "random",
        "re",
        "secrets",
        "statistics",
        "string",
        "struct",
        "textwrap",
        "time",
        "types",
        "typing",
        "unicodedata",
        "uuid",
        "warnings",
        "zoneinfo",
    }
)

# Dynamic-execution escape hatches — never allowed in a draft, regardless
# of the import allowlist (spec §7: "no dynamic __import__/exec/eval
# calls allowed in the draft").
_FORBIDDEN_CALLS = {"exec", "eval", "__import__", "compile", "breakpoint"}

# SECURITY (adversarial-review fix): the bare-name check above never
# inspected ``ast.Attribute`` calls, so ``builtins.exec(...)``-style
# access sailed through. Attribute calls whose terminal attribute is one
# of these names are rejected too. Kept to names with essentially no
# benign top-level use in an agent draft (``run`` is deliberately absent:
# ``asyncio.run`` is legitimate; ``subprocess.run`` is unreachable anyway
# because ``subprocess`` itself can no longer be imported).
_FORBIDDEN_ATTR_CALLS = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "system",
        "popen",
        "exec_module",
        "import_module",
        "run_module",
        "run_path",
        "fork",
        "execl",
        "execle",
        "execlp",
        "execv",
        "execve",
        "execvp",
        "spawnl",
        "spawnv",
        "spawnve",
    }
)

# Base-name heuristic (spec §3 Module 5) — matched against the AST
# ClassDef's base NAMES only; the draft is never imported to resolve a
# real MRO. Mirrors `parrot.bots.__all__` plus the wider base-class
# family documented in the Codebase Contract.
KNOWN_BOT_BASE_NAMES = {
    "AbstractBot",
    "BaseBot",
    "BasicBot",
    "Chatbot",
    "BasicAgent",
    "Agent",
    "PandasAgent",
    "DocumentAgent",
    "WebSearchAgent",
    "WebAgent",
    "MCPAgent",
    "A2AAgent",
    "InfoAgent",
    "VoiceBot",
}


def _is_allowed_module(root: str) -> bool:
    """Return True if a top-level import root is allowed in a draft."""
    return root in _ALLOWED_TOP_LEVEL_PACKAGES or root in _SAFE_STDLIB_MODULES


def _bot_class_defs(tree: ast.Module) -> list[ast.ClassDef]:
    """Return every ``ClassDef`` whose bases include a known bot base name."""
    defs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
            if base_names & KNOWN_BOT_BASE_NAMES:
                defs.append(node)
    return defs


def detect_base_class(source: str) -> str | None:
    """Return the detected AbstractBot-family base name, or ``None``.

    Best-effort — returns ``None`` on a parse error, or when the source
    does not contain exactly one recognizable bot subclass. Callers
    should only trust this after :func:`validate_draft` has reported
    ``passed=True`` for the same source.

    Args:
        source: Draft Python source text.

    Returns:
        The matched base class name, or ``None``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    defs = _bot_class_defs(tree)
    if len(defs) != 1:
        return None
    base_names = {b.id for b in defs[0].bases if isinstance(b, ast.Name)}
    matched = base_names & KNOWN_BOT_BASE_NAMES
    return next(iter(matched)) if matched else None


def validate_draft(source: str) -> DraftValidationReport:
    """Statically validate a draft agent's Python source.

    Checks (spec §3 Module 5, hardened per adversarial review):
      - Syntax is valid Python (``ast.parse``).
      - Every import's top-level module is ``parrot``/``parrot_tools`` or
        a member of the SAFE stdlib allowlist — no arbitrary third-party
        imports, and no process/filesystem/network/dynamic-import stdlib
        modules (``os``, ``subprocess``, ``socket``, ``importlib``, ...).
      - No relative imports.
      - No calls to ``exec``/``eval``/``__import__``/``compile``/
        ``breakpoint`` — in bare-name OR attribute form (plus a set of
        process-spawning attribute names like ``.system()``/``.popen()``).
      - Exactly ONE class derives (by base NAME) from a known
        AbstractBot-family base class.

    Args:
        source: The draft's raw Python source text.

    Returns:
        A :class:`~parrot.handlers.studio.models.DraftValidationReport` —
        ``passed=True`` only when every check above succeeds; otherwise
        ``errors`` lists every finding with its line number and a stable
        ``code``.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return DraftValidationReport(
            passed=False,
            errors=[
                {
                    "line": exc.lineno or 0,
                    "code": "syntax-error",
                    "message": exc.msg or "Invalid Python syntax.",
                }
            ],
        )

    errors: list[dict] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if not _is_allowed_module(root):
                    errors.append(
                        {
                            "line": node.lineno,
                            "code": "forbidden-import",
                            "message": f"Import of '{alias.name}' is not allowed.",
                        }
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                errors.append(
                    {
                        "line": node.lineno,
                        "code": "forbidden-import",
                        "message": "Relative imports are not allowed in drafts.",
                    }
                )
            elif node.module:
                root = node.module.split(".")[0]
                if not _is_allowed_module(root):
                    errors.append(
                        {
                            "line": node.lineno,
                            "code": "forbidden-import",
                            "message": f"Import from '{node.module}' is not allowed.",
                        }
                    )
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
            errors.append(
                {
                    "line": node.lineno,
                    "code": "forbidden-call",
                    "message": f"Call to '{node.func.id}()' is not allowed in drafts.",
                }
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _FORBIDDEN_ATTR_CALLS
        ):
            # Adversarial-review fix: attribute-form access to the same
            # escape hatches (e.g. ``builtins.exec(...)``, ``x.system(...)``)
            # was previously invisible to the bare-Name check above.
            errors.append(
                {
                    "line": node.lineno,
                    "code": "forbidden-call",
                    "message": (f"Call to attribute '.{node.func.attr}()' is not allowed in drafts."),
                }
            )

    bot_defs = _bot_class_defs(tree)
    if not bot_defs:
        errors.append(
            {
                "line": 1,
                "code": "no-bot-subclass",
                "message": (
                    "Draft must define exactly one class deriving from a " "known AbstractBot-family base; found none."
                ),
            }
        )
    elif len(bot_defs) > 1:
        errors.append(
            {
                "line": bot_defs[1].lineno,
                "code": "multiple-bot-subclasses",
                "message": ("Draft must define exactly one AbstractBot-family " f"subclass; found {len(bot_defs)}."),
            }
        )

    return DraftValidationReport(passed=not errors, errors=errors)
