"""`## Validation Commands` parsing and over-broad pytest detection (FEAT-563 M1/M9)."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from .datatypes import TestContract

VALIDATION_HEADING: str = "## Validation Commands"
_HEADING_RE = re.compile(r"^## Validation Commands\s*$", re.M)
_NEXT_HEADING_RE = re.compile(r"^## ", re.M)
_BULLET_CMD_RE = re.compile(r"^\s*[-*]\s+`([^`]+)`")
_PYTEST_MODULE_FORMS = (("python", "-m", "pytest"), ("python3", "-m", "pytest"))
_OPTIONS_WITH_VALUE = frozenset(
    {"-m", "-k", "-c", "-p", "-o", "-n", "--rootdir", "--confcutdir", "--tb", "--ignore", "--maxfail"}
)
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SPEC_CONTRACT_HEADING: str = "### Validation Contract"
TEST_CONTRACT_SCHEMA: int = 1
_SPEC_CONTRACT_RE = re.compile(r"^### Validation Contract\s*$", re.M)
_SPEC_NEXT_RE = re.compile(r"^#{2,3} ", re.M)


def env_prefix_of(argv: Sequence[str]) -> list[str]:
    """The leading POSIX simple-command `NAME=value` assignment tokens of `argv`, in order ([] if none)."""
    prefix: list[str] = []
    for token in argv:
        if not _ENV_ASSIGNMENT_RE.match(token):
            break
        prefix.append(token)
    return prefix


def strip_env_prefix(argv: Sequence[str]) -> list[str]:
    """Drop leading POSIX simple-command `NAME=value` assignment tokens (e.g. `PYTHONPATH=x pytest ...`).

    `.claude/rules/worktree-management.md` documents exactly this idiom for running pytest inside a
    worktree (`PYTHONPATH=packages/ai-parrot/src pytest ...`) — without this strip, the guard's
    `argv[0]`/`seg[0]` check never recognizes the command as pytest and silently allows it unscoped.
    """
    argv = list(argv)
    return argv[len(env_prefix_of(argv)) :]


def _strip_uv_run_prefix(argv: list[str]) -> list[str]:
    """Drop a leading `uv run [-FLAG ...]` launcher prefix (e.g. `uv run --no-sync pytest ...`).

    `.claude/rules/worktree-management.md` documents `uv run --no-sync` as the sanctioned way to
    invoke tools in a worktree without mutating the shared environment — pytest run this way must
    be recognized just like a bare `pytest` invocation.
    """
    if len(argv) < 2 or PurePosixPath(argv[0]).name != "uv" or argv[1] != "run":
        return argv
    rest = argv[2:]
    i = 0
    while i < len(rest) and rest[i].startswith("-"):
        i += 1
    return rest[i:]


def normalize_pytest_argv(argv: Sequence[str]) -> list[str]:
    """`argv` past any leading env-assignment and/or `uv run [flags]` launcher prefix."""
    return _strip_uv_run_prefix(strip_env_prefix(argv))


def parse_validation_commands(task_md: str) -> list[list[str]]:
    """Backticked commands under '## Validation Commands' (bullets), shlex-split; [] when absent."""
    match = _HEADING_RE.search(task_md)
    if not match:
        return []
    body = task_md[match.end() :]
    nxt = _NEXT_HEADING_RE.search(body)
    body = body[: nxt.start()] if nxt else body
    commands: list[list[str]] = []
    for line in body.splitlines():
        bullet = _BULLET_CMD_RE.match(line)
        if not bullet:
            continue
        try:
            commands.append(shlex.split(bullet.group(1)))
        except ValueError:
            continue
    return commands


def _pytest_operands(argv: Sequence[str]) -> list[str] | None:
    """Positional operands of a pytest argv, or None when argv is not a pytest invocation."""
    argv = normalize_pytest_argv(argv)
    if not argv:
        return None
    head = PurePosixPath(argv[0]).name
    if head == "pytest":
        rest = argv[1:]
    elif len(argv) >= 3 and (head, argv[1], argv[2]) in _PYTEST_MODULE_FORMS:
        rest = argv[3:]
    else:
        return None

    operands: list[str] = []
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("-"):
            if "=" in token:
                # e.g. --rootdir=/path — the value is embedded, no extra token to skip.
                i += 1
                continue
            if token in _OPTIONS_WITH_VALUE:
                i += 2  # skip the option and its separate value token
                continue
            i += 1  # a bare flag, e.g. -q, --co
            continue
        operands.append(token)
        i += 1
    return operands


def _relativize(op_path: str, worktree: Path | None) -> str:
    """Best-effort: rewrite an absolute `op_path` relative to `worktree`; unchanged otherwise.

    An absolute operand pointing at the exact same broad directory as its relative form (e.g.
    `/abs/repo/packages/ai-parrot/tests` vs. `packages/ai-parrot/tests`) must be recognized the
    same way — `is_broad_pytest` only ever inspects the relative shape, so without this the guard
    silently treats an absolute-path broad run as narrow. `worktree=None` (no worktree known, e.g.
    a worktree-agnostic caller/unit test) leaves any absolute operand untouched, same as before
    this parameter existed.
    """
    if worktree is None or not PurePosixPath(op_path).is_absolute():
        return op_path
    try:
        return str(Path(op_path).resolve().relative_to(Path(worktree).resolve()).as_posix())
    except (OSError, ValueError):
        return op_path


def is_pytest_invocation(argv: Sequence[str]) -> bool:
    """True when `argv` is `pytest ...` / `python[3] -m pytest ...` (past env/`uv run` prefixes).

    A declared `## Validation Commands` entry that is NOT a pytest invocation at all (e.g. `true`
    or `ruff check .`) is silently invisible to `plan_tests`/`is_broad_pytest` — this lets a task
    (or a lint) tell the two apart from a command that IS pytest but simply narrow.
    """
    return _pytest_operands(argv) is not None


def is_broad_pytest(argv: Sequence[str], *, worktree: Path | None = None) -> bool:
    """True for pytest with no path operand or an operand in {., tests, packages/<dist>/tests} or a
    parent. Pass `worktree` so an absolute operand pointing at one of those same directories is
    also recognized (see `_relativize`)."""
    operands = _pytest_operands(argv)
    if operands is None:
        return False
    if not operands:
        return True
    for op in operands:
        raw = _relativize(op.split("::", 1)[0].rstrip("/") or ".", worktree)
        path = PurePosixPath(raw)
        parts = path.parts
        if parts in ((), (".",), ("tests",), ("packages",)):
            return True
        if len(parts) == 2 and parts[0] == "packages":
            return True
        if len(parts) == 3 and parts[0] == "packages" and parts[2] == "tests":
            return True
    return False


def contract_digest(tests: Sequence[str], markers: Sequence[str]) -> str:
    """``sha256:<hex>`` over the normalized payload; identical inputs always give identical digests."""
    payload = {"schema": TEST_CONTRACT_SCHEMA, "tests": list(tests), "markers": sorted(markers)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _normalize(tests: Sequence[str], markers: Sequence[str]) -> TestContract:
    """Validate operands and markers and build a normalized test contract.

    Raises:
        ValueError: If an operand or marker cannot safely be used by pytest.
    """
    normalized_tests: list[str] = []
    seen_tests: set[str] = set()
    for operand in tests:
        if not isinstance(operand, str) or not operand:
            raise ValueError("test contract operands must be non-empty strings")
        path = operand.split("::", 1)[0]
        if (
            operand.startswith("/")
            or any(part == ".." for part in PurePosixPath(path).parts)
            or any(character in operand for character in "*?[")
            or is_broad_pytest(["pytest", operand])
        ):
            raise ValueError(f"unsafe test contract operand: {operand!r}")
        if operand not in seen_tests:
            normalized_tests.append(operand)
            seen_tests.add(operand)

    normalized_markers: list[str] = []
    for marker in markers:
        if not isinstance(marker, str) or not marker:
            raise ValueError("test contract markers must be non-empty strings")
        if marker == "real_llm":
            raise ValueError("the real_llm marker is not permitted in a test contract")
        normalized_markers.append(marker)
    normalized_markers.sort()

    normalized_test_tuple = tuple(normalized_tests)
    normalized_marker_tuple = tuple(normalized_markers)
    return TestContract(
        schema=TEST_CONTRACT_SCHEMA,
        tests=normalized_test_tuple,
        markers=normalized_marker_tuple,
        digest=contract_digest(normalized_test_tuple, normalized_marker_tuple),
    )


def _without_comment(value: str) -> str:
    """Remove an inline Markdown comment from one contract value."""
    return value.split("#", 1)[0].strip()


def parse_spec_contract(spec_md: str) -> TestContract | None:
    """Parse spec §4 ``### Validation Contract``.

    Returns:
        ``None`` for an explicit ``none — fallback`` contract.

    Raises:
        ValueError: If the subsection is missing or malformed.
    """
    match = _SPEC_CONTRACT_RE.search(spec_md)
    if not match:
        raise ValueError(f"missing {SPEC_CONTRACT_HEADING!r} subsection")
    body = spec_md[match.end() :]
    next_heading = _SPEC_NEXT_RE.search(body)
    if next_heading:
        body = body[: next_heading.start()]

    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith(">")]
    if not lines:
        raise ValueError("empty validation contract subsection")
    if lines[0] in {"none — fallback", "none - fallback"}:
        if len(lines) != 1:
            raise ValueError("fallback validation contract must not contain additional values")
        return None

    tests: list[str] = []
    markers: list[str] = []
    section: str | None = None
    saw_tests = False
    saw_markers = False
    for line in lines:
        if line == "tests:":
            if saw_tests:
                raise ValueError("duplicate tests section")
            section = "tests"
            saw_tests = True
            continue
        if line == "markers: none":
            if saw_markers:
                raise ValueError("duplicate markers section")
            section = None
            saw_markers = True
            continue
        if line == "markers:":
            if saw_markers:
                raise ValueError("duplicate markers section")
            section = "markers"
            saw_markers = True
            continue
        if not line.startswith("- ") or section is None:
            raise ValueError(f"malformed validation contract line: {line!r}")
        value = _without_comment(line[2:])
        if not value:
            raise ValueError("validation contract values must be non-empty")
        if section == "tests":
            tests.append(value)
        else:
            markers.append(value)

    if not saw_tests or not saw_markers:
        raise ValueError("validation contract requires tests and markers sections")
    return _normalize(tests, markers)


def contract_from_index_header(header: Mapping[str, object]) -> TestContract | None:
    """Read the cached ``test_contract`` payload from an index header.

    Raises:
        ValueError: If a present payload has an invalid shape, schema, or digest.
    """
    if "test_contract" not in header:
        return None
    payload = header["test_contract"]
    if not isinstance(payload, dict):
        raise ValueError("test_contract must be an object")
    schema = payload.get("schema")
    tests = payload.get("tests")
    markers = payload.get("markers")
    digest = payload.get("digest")
    if type(schema) is not int or schema != TEST_CONTRACT_SCHEMA:
        raise ValueError("test_contract has an unsupported schema")
    if not isinstance(tests, list) or not isinstance(markers, list) or not isinstance(digest, str):
        raise ValueError("test_contract has an invalid shape")
    contract = _normalize(tests, markers)
    if digest != contract.digest:
        raise ValueError("test_contract digest does not match its content")
    return contract


def contract_to_header(contract: TestContract) -> dict[str, object]:
    """Return the JSON-ready ``test_contract`` header value."""
    return {
        "schema": contract.schema,
        "tests": list(contract.tests),
        "markers": list(contract.markers),
        "digest": contract.digest,
    }


def load_index_header(index_path: Path) -> dict[str, object]:
    """Read a per-spec index JSON and return it without its ``tasks`` member.

    Raises:
        ValueError: If the index cannot be read, decoded, or is not a JSON object.
    """
    try:
        payload = json.loads(index_path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(f"unable to read index header from {index_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("index JSON must be an object")
    header = dict(payload)
    header.pop("tasks", None)
    return header
