"""Allowlist-first AST gate for Python code executed in the REPL sandbox.

Introduced in FEAT-252 (TASK-1614) as WS1 — the primary code containment layer.
An allowlist-first policy decides which import names, builtins, and operations are
permitted.  Categorical denials (env access, introspection, dynamic exec, data IO)
fire **regardless** of the allowlist as a defence-in-depth layer alongside the
existing ``PythonREPLTool._check_ast_security`` denylist.

Usage:
    >>> sanitizer = PythonCodeSanitizer(general_profile())
    >>> result = sanitizer.validate("import os; os.environ")
    >>> result.is_denied
    True
    >>> result = sanitizer.validate("sum([1, 2, 3])")
    >>> result.is_allowed
    True
"""
from __future__ import annotations

import ast
import builtins
import logging
from dataclasses import dataclass, field
from typing import FrozenSet, List, Optional

from .command_sanitizer import CommandVerdict, SecurityLevel, ValidationResult

# Frozenset of all Python builtin names — used by the allowlist gate to
# distinguish builtin references from user-defined variable names.
_PYTHON_BUILTINS: FrozenSet[str] = frozenset(vars(builtins))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowlist defaults
# ---------------------------------------------------------------------------

#: Baseline safe imports available to all profiles.
_BASELINE_IMPORTS: FrozenSet[str] = frozenset(
    {
        "builtins",  # needed by the exec environment itself — categorical denials gate use
        "collections",
        "datetime",
        "decimal",
        "enum",
        "functools",
        "itertools",
        "json",
        "math",
        "operator",
        "pprint",
        "re",
        "statistics",
        "string",
        "textwrap",
        "time",
        "typing",
        "uuid",
        # Infra always available in Parrot's REPL environment
        "navconfig",
        "navconfig.logging",
    }
)

#: Additional imports permitted in the general profile (read-only APIs).
_GENERAL_IMPORTS: FrozenSet[str] = frozenset(
    {
        "pandas",
        "numpy",
        "matplotlib",
        "matplotlib.pyplot",
        "seaborn",
        "altair",
        "plotly",
        "scipy",
        "sklearn",
    }
)

#: Extra imports permitted in the data-analysis profile.
_DATA_ANALYSIS_IMPORTS: FrozenSet[str] = frozenset(
    {
        # Broader pandas/numpy surface for compute on materialised DataFrames
        "pandas.core",
        "numpy.core",
        "numexpr",
        "tabulate",
    }
)

#: Exception classes (and warning categories) from ``builtins`` — always safe
#: to reference: they enable standard ``try/except ValueError`` handling and
#: ``raise`` statements without granting any IO or introspection capability.
_EXCEPTION_BUILTINS: FrozenSet[str] = frozenset(
    name
    for name, obj in vars(builtins).items()
    if isinstance(obj, type) and issubclass(obj, BaseException)
)

#: Baseline safe builtins.
_BASELINE_BUILTINS: FrozenSet[str] = _EXCEPTION_BUILTINS | frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "bytearray",
        "callable",
        "chr",
        "complex",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "filter",
        "float",
        "format",
        "frozenset",
        "hash",
        "hex",
        "id",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "map",
        "max",
        "min",
        "next",
        "object",
        "oct",
        "ord",
        "pow",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "slice",
        "sorted",
        "str",
        "sum",
        "tuple",
        "type",
        "zip",
        "True",
        "False",
        "None",
    }
)

# ---------------------------------------------------------------------------
# Categorical deny sets (import root names that are always denied)
# ---------------------------------------------------------------------------

_ENV_ACCESS_IMPORTS: FrozenSet[str] = frozenset({"os", "posix", "nt", "environ"})
_INTROSPECTION_IMPORTS: FrozenSet[str] = frozenset({"inspect", "dis", "gc", "sys", "ctypes"})
_DYNAMIC_EXEC_NAMES: FrozenSet[str] = frozenset(
    {
        "eval", "exec", "compile", "__import__", "execfile", "reload",
        "getattr", "setattr", "hasattr",
        "breakpoint", "input",
    }
)
_DATA_IO_IMPORTS: FrozenSet[str] = frozenset(
    {
        "io",
        "pathlib",
        "glob",
        "shutil",
        "tempfile",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "socket",
        "ssl",
        "http",
        "ftplib",
        "smtplib",
        "sqlite3",
        "psycopg2",
        "sqlalchemy",
        "pymongo",
        "redis",
        "boto3",
        "botocore",
        "subprocess",
        "multiprocessing",
        "threading",
    }
)
#: pandas IO function names that are categorically denied even when pandas is allowed.
_PANDAS_IO_NAMES: FrozenSet[str] = frozenset(
    {
        "read_clipboard",
        "read_csv",
        "read_excel",
        "read_json",
        "read_parquet",
        "read_sql",
        "read_html",
        "read_feather",
        "read_hdf",
        "read_orc",
        "read_pickle",
        "read_sas",
        "read_spss",
        "read_stata",
        "read_table",
        "to_csv",
        "to_excel",
        "to_sql",
        "to_json",
        "to_parquet",
    }
)
#: Builtins / names categorically denied for data-IO.
_DATA_IO_NAMES: FrozenSet[str] = frozenset({"open", "file"})
#: os attribute names denied when os access is blocked.
_ENV_ATTR_NAMES: FrozenSet[str] = frozenset({"environ", "getenv", "putenv", "unsetenv"})
#: Introspection builtins always denied.
#: ``dir`` is deliberately NOT here: it returns attribute *names* only and is
#: the supported way for agents to explore the sandboxed namespace. ``globals``/
#: ``locals``/``vars`` stay denied — they return the live namespace dict whose
#: ``__builtins__`` entry is a sandbox-escape vector.
_INTROSPECTION_NAMES: FrozenSet[str] = frozenset({"globals", "locals", "vars", "__class__", "__bases__"})


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PythonExecutionPolicy:
    """Policy controlling the ``PythonCodeSanitizer`` allowlist-first gate.

    Attributes:
        level: The ``SecurityLevel`` posture (default ``RESTRICTIVE``).
        default_deny: When ``True`` (default), any import / call / name NOT on
            the allowlist is denied. Set to ``False`` only for trusted contexts.
        allowed_imports: Frozenset of module root names that may be imported.
        allowed_builtins: Frozenset of builtin names that may be called.
            Wired into ``_check_name``: when ``default_deny=True`` and this set
            is non-empty, any name not in this allowlist is denied (spec §WS1).
        deny_env_access: Deny all ``os.environ`` / ``os.getenv`` access (default ``True``).
        deny_introspection: Deny ``globals``, ``locals``, ``__class__.__bases__`` etc.
            (default ``True``).
        deny_dynamic_exec: Deny ``eval``, ``exec``, ``compile``, ``__import__``
            (default ``True``).
        deny_data_io: Deny file/network/DB IO (default ``True``).
        isolation: Execution isolation mode (``"in_process"`` — subprocess is a Non-Goal).
        max_output_bytes: Maximum allowed output size in bytes.
    """

    level: SecurityLevel = SecurityLevel.RESTRICTIVE
    default_deny: bool = True
    allowed_imports: FrozenSet[str] = field(default_factory=frozenset)
    allowed_builtins: FrozenSet[str] = field(default_factory=frozenset)
    deny_env_access: bool = True
    deny_introspection: bool = True
    deny_dynamic_exec: bool = True
    deny_data_io: bool = True
    isolation: str = "in_process"
    max_output_bytes: int = 1_048_576  # 1 MiB


def general_profile() -> PythonExecutionPolicy:
    """Return the general (tightest) execution policy.

    Suitable for Jira/GitHub/tool-orchestration agents that consume data via
    structured tools rather than raw REPL IO.

    Returns:
        ``PythonExecutionPolicy`` with restricted import/builtin allowlists.
    """
    return PythonExecutionPolicy(
        level=SecurityLevel.RESTRICTIVE,
        default_deny=True,
        allowed_imports=_BASELINE_IMPORTS | _GENERAL_IMPORTS,
        allowed_builtins=_BASELINE_BUILTINS,
        deny_env_access=True,
        deny_introspection=True,
        deny_dynamic_exec=True,
        deny_data_io=True,
    )


def data_analysis_profile() -> PythonExecutionPolicy:
    """Return the data-analysis execution policy.

    Widens the allowlist for pandas/numpy compute on already-materialised
    DataFrames injected via REPL locals.  File / network IO remains denied.

    Returns:
        ``PythonExecutionPolicy`` with a broader but still restricted import
        allowlist.
    """
    return PythonExecutionPolicy(
        level=SecurityLevel.MODERATE,
        default_deny=True,
        allowed_imports=_BASELINE_IMPORTS | _GENERAL_IMPORTS | _DATA_ANALYSIS_IMPORTS,
        allowed_builtins=_BASELINE_BUILTINS,
        deny_env_access=True,
        deny_introspection=True,
        deny_dynamic_exec=True,
        deny_data_io=True,  # Even data-analysis profile denies file/net IO
    )


# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------


class PythonCodeSanitizer:
    """Allowlist-first AST gate for Python code.

    Walks the AST of ``code`` and checks each import statement, name reference,
    and function call against the active ``PythonExecutionPolicy``.

    Categorical denials (env / introspection / dynamic-exec / data-IO) fire
    regardless of the allowlist, providing a belt-and-suspenders defence on top
    of the existing ``PythonREPLTool._check_ast_security`` denylist.

    Example:
        >>> sanitizer = PythonCodeSanitizer(general_profile())
        >>> sanitizer.validate("import os").is_denied
        True
        >>> sanitizer.validate("sum([1, 2, 3])").is_allowed
        True
    """

    def __init__(self, policy: Optional[PythonExecutionPolicy] = None) -> None:
        """Initialise the sanitizer.

        Args:
            policy: Execution policy to apply. Defaults to ``general_profile()``.
        """
        self.policy = policy if policy is not None else general_profile()
        self.logger = logging.getLogger(__name__)

    def validate(self, code: str) -> ValidationResult:
        """Validate *code* against the active policy.

        Args:
            code: Python source code to validate.

        Returns:
            ``ValidationResult`` with ``verdict=ALLOW`` or ``verdict=DENY``.
            On deny, ``reasons`` lists why each denial fired.
        """
        reasons: List[str] = []

        # Step 1: parse — syntax errors are a denial (cannot exec)
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return ValidationResult(
                verdict=CommandVerdict.DENIED,
                command=code,
                reasons=(f"SyntaxError: {exc}",),
                sanitized_command=code,
                risk_score=1.0,
            )

        # Step 2: walk AST for violations
        reasons.extend(self._walk(tree))

        if reasons:
            return ValidationResult(
                verdict=CommandVerdict.DENIED,
                command=code,
                reasons=tuple(reasons),
                sanitized_command="",
                risk_score=min(1.0, 0.3 * len(reasons)),
            )

        return ValidationResult(
            verdict=CommandVerdict.ALLOWED,
            command=code,
            reasons=(),
            sanitized_command=code,
            risk_score=0.0,
        )

    # ------------------------------------------------------------------
    # Internal AST walker
    # ------------------------------------------------------------------

    def _walk(self, tree: ast.AST) -> List[str]:
        """Walk the AST and return a list of denial reasons (empty = OK)."""
        reasons: List[str] = []
        p = self.policy

        for node in ast.walk(tree):
            # ── Import statements ──────────────────────────────────────────
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    denial = self._check_import_root(root)
                    if denial:
                        reasons.append(denial)

            elif isinstance(node, ast.ImportFrom):
                module = (node.module or "").split(".")[0]
                denial = self._check_import_root(module)
                if denial:
                    reasons.append(denial)
                # Also check function-level data IO (e.g. from pandas import read_csv)
                if p.deny_data_io:
                    for alias in node.names:
                        if alias.name in _PANDAS_IO_NAMES:
                            reasons.append(
                                f"denied: data-IO function '{alias.name}' may not be imported"
                            )
                        if alias.name in _DATA_IO_NAMES:
                            reasons.append(
                                f"denied: data-IO builtin '{alias.name}' may not be imported"
                            )

            # ── Name references ────────────────────────────────────────────
            elif isinstance(node, ast.Name):
                denial = self._check_name(node.id)
                if denial:
                    reasons.append(denial)

            # ── Attribute access ───────────────────────────────────────────
            elif isinstance(node, ast.Attribute):
                denial = self._check_attribute(node)
                if denial:
                    reasons.append(denial)

        return list(dict.fromkeys(reasons))  # deduplicate while preserving order

    def _check_import_root(self, root: str) -> Optional[str]:
        """Return a denial reason if *root* module is not allowed."""
        p = self.policy

        # Categorical: env access
        if p.deny_env_access and root in _ENV_ACCESS_IMPORTS:
            return f"denied: env-access import '{root}' is categorically denied"

        # Categorical: introspection
        if p.deny_introspection and root in _INTROSPECTION_IMPORTS:
            return f"denied: introspection import '{root}' is categorically denied"

        # Categorical: data IO
        if p.deny_data_io and root in _DATA_IO_IMPORTS:
            return f"denied: data-IO import '{root}' is categorically denied"

        # Allowlist gate (default_deny)
        if p.default_deny and root not in p.allowed_imports:
            return f"denied: import '{root}' is not on the allowlist"

        return None

    def _check_name(self, name: str) -> Optional[str]:
        """Return a denial reason if *name* is forbidden."""
        p = self.policy

        # Categorical: dynamic exec
        if p.deny_dynamic_exec and name in _DYNAMIC_EXEC_NAMES:
            return f"denied: dynamic-exec name '{name}' is categorically denied"

        # Categorical: data IO builtins
        if p.deny_data_io and name in _DATA_IO_NAMES:
            return f"denied: data-IO builtin '{name}' is categorically denied"

        # Categorical: introspection builtins
        if p.deny_introspection and name in _INTROSPECTION_NAMES:
            return f"denied: introspection name '{name}' is categorically denied"

        # Allowlist gate: if default_deny + allowed_builtins is set, any name
        # that is a Python builtin AND is NOT on the allowlist is denied
        # (allowlist-first policy, spec §WS1).
        # User-defined variable names are never blocked here — only builtin
        # function/constant references that shadow controlled names.
        if (
            p.default_deny
            and p.allowed_builtins
            and name in _PYTHON_BUILTINS
            and name not in p.allowed_builtins
        ):
            return f"denied: name '{name}' is not on the allowed_builtins allowlist"

        return None

    def _check_attribute(self, node: ast.Attribute) -> Optional[str]:
        """Return a denial reason if an attribute access is forbidden."""
        p = self.policy
        attr = node.attr

        # Categorically denied attributes on os / environ proxies
        if p.deny_env_access and attr in _ENV_ATTR_NAMES:
            return f"denied: env-access attribute '.{attr}' is categorically denied"

        # Categorical: pandas IO methods
        if p.deny_data_io and attr in _PANDAS_IO_NAMES:
            return f"denied: data-IO attribute '.{attr}' is categorically denied"

        # Introspection dunder attributes
        if p.deny_introspection and attr in {"__class__", "__bases__", "__subclasses__", "__mro__", "__dict__"}:
            return f"denied: introspection attribute '.{attr}' is categorically denied"

        return None
