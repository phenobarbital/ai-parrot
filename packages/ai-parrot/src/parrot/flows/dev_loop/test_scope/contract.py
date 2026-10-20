"""`## Validation Commands` parsing and over-broad pytest detection (FEAT-563 M1/M9)."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from .datatypes import RunnerContract, TestContract
from .policy import TIERS

if TYPE_CHECKING:
    from .runners.registry import RunnerRegistry

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
TEST_CONTRACT_SCHEMA: int = 2
KNOWN_RUNNER_KINDS: frozenset[str] = frozenset({"pytest", "vitest", "cargo", "parrot-e2e"})
_DEFAULT_RUNNER_TIERS: Mapping[str, tuple[str, ...]] = {
    "pytest": TIERS,
    "vitest": TIERS,
    "cargo": TIERS,
    "parrot-e2e": ("merge", "feature"),
}
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


def _runner_payload(runner: RunnerContract) -> dict[str, object]:
    """Return one normalized runner as a JSON-ready mapping."""
    return {
        "kind": runner.kind,
        "targets": list(runner.targets),
        "settings": dict(runner.settings),
        "tiers": list(runner.tiers),
    }


def contract_digest(runners: Sequence[RunnerContract]) -> str:
    """Return a stable digest over the normalized schema-2 payload."""
    payload = {"schema": TEST_CONTRACT_SCHEMA, "runners": [_runner_payload(runner) for runner in runners]}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _legacy_digest(tests: Sequence[str], markers: Sequence[str]) -> str:
    """Return the FEAT-699 schema-1 digest for integrity checking during lift."""
    payload = {"schema": 1, "tests": list(tests), "markers": sorted(markers)}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _normalize_pytest(tests: Sequence[object], markers: Sequence[object]) -> RunnerContract:
    """Validate pytest operands and markers and return a normalized runner block.

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

    return RunnerContract(
        kind="pytest",
        targets=tuple(normalized_tests),
        settings={"markers": ",".join(normalized_markers)},
    )


def _build_contract(runners: Sequence[RunnerContract]) -> TestContract:
    """Build a schema-2 contract and compute its digest."""
    normalized = tuple(runners)
    if not normalized:
        raise ValueError("validation contract requires at least one runner")
    return TestContract(schema=TEST_CONTRACT_SCHEMA, runners=normalized, digest=contract_digest(normalized))


def _normalize_targets(targets: Sequence[object], *, kind: str) -> tuple[str, ...]:
    """Validate and de-duplicate non-pytest targets while preserving order."""
    normalized: list[str] = []
    for target in targets:
        if not isinstance(target, str) or not target:
            raise ValueError(f"{kind} runner targets must be non-empty strings")
        if target not in normalized:
            normalized.append(target)
    return tuple(normalized)


def _normalize_runner(
    *,
    kind: object,
    targets: Sequence[object],
    settings: Mapping[object, object],
    tiers: Sequence[object] | None,
    registry: "RunnerRegistry | None",
) -> RunnerContract:
    """Validate one runner block against built-ins or an explicitly supplied registry."""
    if not isinstance(kind, str) or not kind:
        raise ValueError("runner kind must be a non-empty string")
    if registry is None:
        if kind not in KNOWN_RUNNER_KINDS:
            raise ValueError(f"unknown runner kind: {kind!r}")
        allowed_tiers = frozenset(_DEFAULT_RUNNER_TIERS[kind])
        adapter = None
    else:
        try:
            adapter = registry.adapter_for_kind(kind)
            allowed_tiers = registry.tiers_for(kind)
        except (KeyError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

    normalized_settings: dict[str, str] = {}
    for key, value in settings.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"{kind} runner settings must contain string keys and values")
        normalized_settings[key] = value

    chosen_tiers = tuple(allowed_tiers) if tiers is None else tuple(tiers)
    if not chosen_tiers or any(not isinstance(tier, str) or not tier for tier in chosen_tiers):
        raise ValueError(f"{kind} runner tiers must be non-empty strings")
    if len(set(chosen_tiers)) != len(chosen_tiers):
        raise ValueError(f"{kind} runner tiers must not contain duplicates")
    unknown_tiers = set(chosen_tiers) - set(TIERS)
    if unknown_tiers:
        raise ValueError(f"{kind} runner has unknown tiers: {', '.join(sorted(unknown_tiers))}")
    forbidden_tiers = set(chosen_tiers) - set(allowed_tiers)
    if forbidden_tiers:
        raise ValueError(f"{kind} runner does not support tiers: {', '.join(sorted(forbidden_tiers))}")

    if kind == "pytest":
        marker_value = normalized_settings.get("markers", "")
        pytest_runner = _normalize_pytest(targets, marker_value.split(",") if marker_value else ())
        normalized_targets = pytest_runner.targets
        normalized_settings["markers"] = pytest_runner.settings["markers"]
    else:
        normalized_targets = _normalize_targets(targets, kind=kind)

    if registry is not None and adapter is not None:
        effective_settings = {**registry.settings_for(kind), **normalized_settings}
        diagnostics = adapter.validate_settings(effective_settings, worktree=Path.cwd())
        if diagnostics:
            raise ValueError("; ".join(diagnostics))

    ordered_tiers = tuple(tier for tier in TIERS if tier in chosen_tiers)
    return RunnerContract(kind=kind, targets=normalized_targets, settings=normalized_settings, tiers=ordered_tiers)


def _without_comment(value: str) -> str:
    """Remove an inline Markdown comment from one contract value."""
    return value.split("#", 1)[0].strip()


def _parse_inline_list(value: str, *, field_name: str) -> list[str]:
    """Parse a small Markdown/YAML-style inline list used by runner blocks."""
    value = _without_comment(value)
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError(f"{field_name} must be a bracketed list")
    inner = value[1:-1].strip()
    if not inner:
        return []
    values = [_without_comment(item) for item in inner.split(",")]
    if any(not item for item in values):
        raise ValueError(f"{field_name} values must be non-empty")
    return values


def _parse_runner_lines(lines: Sequence[str], *, registry: "RunnerRegistry | None") -> TestContract:
    """Parse the documented indentation-based ``runners:`` authoring form."""
    raw_runners: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    seen_fields: set[str] = set()
    list_field: str | None = None
    for raw_line in lines[1:]:
        if not raw_line.strip() or raw_line.lstrip().startswith(">"):
            continue
        stripped = raw_line.strip()
        if raw_line == raw_line.lstrip() and stripped.startswith("- kind:"):
            kind = _without_comment(stripped.removeprefix("- kind:").strip())
            if not kind:
                raise ValueError("runner kind must be a non-empty string")
            current = {"kind": kind, "targets": [], "settings": {}}
            raw_runners.append(current)
            seen_fields = {"kind"}
            list_field = None
            continue
        if current is None or raw_line == raw_line.lstrip():
            raise ValueError(f"malformed validation contract line: {stripped!r}")
        if stripped.startswith("- "):
            if list_field is None:
                raise ValueError(f"malformed validation contract line: {stripped!r}")
            value = _without_comment(stripped[2:])
            if not value:
                raise ValueError("validation contract values must be non-empty")
            cast_values = current[list_field]
            if not isinstance(cast_values, list):
                raise ValueError(f"duplicate runner field: {list_field}")
            cast_values.append(value)
            continue
        if ":" not in stripped:
            raise ValueError(f"malformed validation contract line: {stripped!r}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = _without_comment(raw_value)
        if key in seen_fields:
            raise ValueError(f"duplicate runner field: {key}")
        seen_fields.add(key)
        if key == "tests":
            if value:
                raise ValueError("runner tests must be a list")
            current["targets"] = []
            list_field = "targets"
        elif key in {"markers", "tiers"} and not value:
            current[key] = []
            list_field = key
        elif key == "markers":
            current[key] = [] if value == "none" else _parse_inline_list(value, field_name="markers")
            list_field = None
        elif key == "tiers":
            current[key] = _parse_inline_list(value, field_name="tiers")
            list_field = None
        elif key == "filter":
            if not value:
                raise ValueError("runner filter must be non-empty")
            targets = current["targets"]
            if not isinstance(targets, list):
                raise ValueError("runner targets have an invalid shape")
            targets.append(value)
            list_field = None
        else:
            if not key or not value:
                raise ValueError(f"runner setting {key!r} must be non-empty")
            settings = current["settings"]
            if not isinstance(settings, dict):
                raise ValueError("runner settings have an invalid shape")
            settings[key] = value
            list_field = None

    runners: list[RunnerContract] = []
    seen_kinds: set[str] = set()
    for raw in raw_runners:
        kind = raw["kind"]
        if isinstance(kind, str) and kind in seen_kinds:
            raise ValueError(f"duplicate runner kind: {kind!r}")
        if isinstance(kind, str):
            seen_kinds.add(kind)
        settings = raw["settings"]
        if not isinstance(settings, dict):
            raise ValueError("runner settings have an invalid shape")
        markers = raw.get("markers")
        if markers is not None:
            if kind != "pytest" or not isinstance(markers, list):
                raise ValueError("markers are only valid for the pytest runner")
            settings["markers"] = ",".join(markers)
        tiers = raw.get("tiers")
        runners.append(
            _normalize_runner(
                kind=kind,
                targets=raw["targets"] if isinstance(raw["targets"], list) else (),
                settings=settings,
                tiers=tiers if isinstance(tiers, list) else None,
                registry=registry,
            )
        )
    return _build_contract(runners)


def parse_spec_contract(spec_md: str, *, registry: "RunnerRegistry | None" = None) -> TestContract | None:
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

    raw_lines = [line.rstrip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith(">")]
    lines = [line.strip() for line in raw_lines]
    if not lines:
        raise ValueError("empty validation contract subsection")
    if lines[0] in {"none — fallback", "none - fallback"}:
        if len(lines) != 1:
            raise ValueError("fallback validation contract must not contain additional values")
        return None
    if lines[0] == "runners:":
        return _parse_runner_lines(raw_lines, registry=registry)

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
    pytest_runner = _normalize_runner(
        kind="pytest",
        targets=tests,
        settings={"markers": ",".join(markers)},
        tiers=None,
        registry=registry,
    )
    return _build_contract((pytest_runner,))


def lift_schema1(payload: Mapping[str, object]) -> TestContract:
    """Lift schema 1 to one pytest runner after validating its original digest."""
    tests = payload.get("tests")
    markers = payload.get("markers")
    digest = payload.get("digest")
    if not isinstance(tests, list) or not isinstance(markers, list) or not isinstance(digest, str):
        raise ValueError("test_contract has an invalid schema-1 shape")
    runner = _normalize_pytest(tests, markers)
    normalized_markers = tuple(filter(None, runner.settings["markers"].split(",")))
    if digest != _legacy_digest(runner.targets, normalized_markers):
        raise ValueError("test_contract digest does not match its content")
    return _build_contract((runner,))


def contract_from_index_header(
    header: Mapping[str, object], *, registry: "RunnerRegistry | None" = None
) -> TestContract | None:
    """Read the cached ``test_contract`` payload from an index header.

    Raises:
        ValueError: If a present payload has an invalid shape, schema, or digest.
    """
    if "test_contract" not in header:
        return None
    payload = header["test_contract"]
    if not isinstance(payload, Mapping):
        raise ValueError("test_contract must be an object")
    schema = payload.get("schema")
    if type(schema) is not int:
        raise ValueError("test_contract has an unsupported schema")
    if schema == 1:
        return lift_schema1(payload)
    if schema != TEST_CONTRACT_SCHEMA:
        raise ValueError("test_contract has an unsupported schema")
    raw_runners = payload.get("runners")
    digest = payload.get("digest")
    if not isinstance(raw_runners, list) or not isinstance(digest, str):
        raise ValueError("test_contract has an invalid shape")
    runners: list[RunnerContract] = []
    seen_kinds: set[str] = set()
    for raw_runner in raw_runners:
        if not isinstance(raw_runner, Mapping) or set(raw_runner) != {"kind", "targets", "settings", "tiers"}:
            raise ValueError("test_contract contains a malformed runner block")
        kind = raw_runner["kind"]
        if isinstance(kind, str) and kind in seen_kinds:
            raise ValueError(f"duplicate runner kind: {kind!r}")
        if isinstance(kind, str):
            seen_kinds.add(kind)
        targets = raw_runner["targets"]
        settings = raw_runner["settings"]
        tiers = raw_runner["tiers"]
        if not isinstance(targets, list) or not isinstance(settings, Mapping) or not isinstance(tiers, list):
            raise ValueError("test_contract contains a malformed runner block")
        runners.append(_normalize_runner(kind=kind, targets=targets, settings=settings, tiers=tiers, registry=registry))
    contract = _build_contract(runners)
    if digest != contract.digest:
        raise ValueError("test_contract digest does not match its content")
    return contract


def contract_to_header(contract: TestContract) -> dict[str, object]:
    """Always write schema 2 with normalized runner blocks."""
    return {
        "schema": TEST_CONTRACT_SCHEMA,
        "runners": [_runner_payload(runner) for runner in contract.runners],
        "digest": contract_digest(contract.runners),
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
