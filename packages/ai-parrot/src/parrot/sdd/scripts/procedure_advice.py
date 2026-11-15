"""Hook-side procedure advice (FEAT-891): stdlib only, no parrot import, never raises.

Loads both as ``parrot.sdd.scripts.procedure_advice`` and as a script sibling of the guards.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

INDEX_SCHEMA_VERSION = 1
ESCAPE_ENV = "PARROT_ALLOW_PROCEDURE"
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")
PLANE_DIR = Path(".parrot") / "procedure"
INDEX_FILE = "procedures.json"
MAX_INDEX_BYTES = 262144
_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})


@dataclass(frozen=True)
class Advice:
    """Outcome of the procedure check for one command."""

    decision: Literal["none", "advise", "deny"]
    text: str = ""


def checkout_root(cwd: Path) -> Path | None:
    """Return the nearest ancestor of ``cwd`` holding a ``.git`` entry."""
    try:
        if cwd is None:
            return None
        start = Path(cwd).resolve()
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return candidate
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return None


def shared_root(cwd: Path) -> Path | None:
    """Return the primary checkout for ``cwd`` without invoking a subprocess.

    A linked worktree's ``.git`` file points at an administrative worktree directory. Its
    ``commondir`` file points back to the primary checkout's ``.git`` directory.
    """
    try:
        root = checkout_root(cwd)
        if root is None:
            return None

        git_entry = root / ".git"
        if git_entry.is_dir():
            return root
        if not git_entry.is_file():
            return None

        first_line = git_entry.read_text(encoding="utf-8").splitlines()[0]
        marker = "gitdir:"
        if not first_line.lower().startswith(marker):
            return None
        gitdir_text = first_line[len(marker) :].strip()
        if not gitdir_text:
            return None
        gitdir = Path(gitdir_text)
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        gitdir = gitdir.resolve()

        common_text = (gitdir / "commondir").read_text(encoding="utf-8").strip()
        if not common_text:
            return None
        common_dir = Path(common_text)
        if not common_dir.is_absolute():
            common_dir = gitdir / common_dir
        return common_dir.resolve().parent
    except (OSError, IndexError, RuntimeError, TypeError, ValueError):
        return None


def load_index(root: Path) -> dict[str, Any] | None:
    """Load a valid compiled procedure index from ``root`` without raising."""
    try:
        index_path = root / PLANE_DIR / INDEX_FILE
        if index_path.stat().st_size > MAX_INDEX_BYTES:
            return None
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != INDEX_SCHEMA_VERSION:
            return None
        return payload
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _replace_unquoted_newlines(command: str) -> str:
    """Turn unquoted newlines into shell segment separators for ``shlex``."""
    result: list[str] = []
    quote = ""
    escaped = False
    for character in command:
        if escaped:
            result.append(character)
            escaped = False
            continue
        if character == "\\" and quote != "'":
            result.append(character)
            escaped = True
            continue
        if character in {"'", '"'}:
            if not quote:
                quote = character
            elif quote == character:
                quote = ""
            result.append(character)
            continue
        if character == "\n" and not quote:
            result.append(" ; ")
        else:
            result.append(character)
    return "".join(result)


def command_segments(command: str) -> list[list[str]]:
    """Split a shell command into token lists, one per simple command."""
    try:
        line = _replace_unquoted_newlines(command)
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        segments: list[list[str]] = []
        current: list[str] = []
        for token in lexer:
            if token in _OPERATORS:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
        if current:
            segments.append(current)
        return segments
    except (TypeError, ValueError, OSError):
        return []


def _assignment(token: str) -> bool:
    """Return whether ``token`` is a shell-style leading environment assignment."""
    name, separator, _ = token.partition("=")
    return bool(separator and name and (name[0].isalpha() or name[0] == "_") and name.isidentifier())


def _skip_options(tokens: list[str], index: int) -> int:
    """Skip option tokens in a wrapper prefix."""
    while index < len(tokens) and tokens[index].startswith("-") and tokens[index] != "-":
        index += 1
    return index


def _clean(tokens: list[str]) -> tuple[str, list[str]]:
    """Return the executable basename and its arguments after known wrappers are removed."""
    try:
        index = 0
        while index < len(tokens) and _assignment(tokens[index]):
            index += 1

        while index < len(tokens):
            wrapper = os.path.basename(tokens[index])
            if wrapper == "rtk":
                index += 1
                continue
            if wrapper == "sudo":
                index = _skip_options(tokens, index + 1)
                continue
            if wrapper == "timeout":
                index = _skip_options(tokens, index + 1)
                if index < len(tokens):
                    index += 1
                continue
            if wrapper == "uv" and index + 1 < len(tokens) and tokens[index + 1] == "run":
                index = _skip_options(tokens, index + 2)
                continue
            if wrapper == "cd":
                return "", []
            return wrapper, tokens[index + 1 :]
        return "", []
    except (IndexError, TypeError, ValueError, OSError):
        return "", []


def leading_command(command: str) -> tuple[str, list[str]]:
    """Return the executable and arguments from the first real command segment."""
    try:
        for tokens in command_segments(command):
            executable, argv = _clean(tokens)
            if executable:
                return executable, argv
    except (TypeError, ValueError, OSError):
        pass
    return "", []


def _normalise_path(value: str) -> str:
    """Normalize a guard argument to a POSIX-style repository-relative path."""
    normalized = os.path.normpath(value).replace(os.sep, "/").replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:
    """Return index guards matching any command segment, preserving index order."""
    try:
        guards = index.get("guards", [])
        if not isinstance(guards, list):
            return []
        segments = command_segments(command)
        matches: list[dict[str, Any]] = []
        for guard in guards:
            if not isinstance(guard, Mapping):
                continue
            executable = guard.get("executable")
            argv_prefix = guard.get("argv_prefix", [])
            path_globs = guard.get("path_globs", [])
            if (
                not isinstance(executable, str)
                or not isinstance(argv_prefix, list)
                or not all(isinstance(item, str) for item in argv_prefix)
            ):
                continue
            if not isinstance(path_globs, list) or not all(isinstance(item, str) for item in path_globs):
                continue
            for tokens in segments:
                actual_executable, argv = _clean(tokens)
                if actual_executable != executable or argv[: len(argv_prefix)] != argv_prefix:
                    continue
                remaining = argv[len(argv_prefix) :]
                if path_globs and not any(
                    fnmatch.fnmatchcase(_normalise_path(argument), pattern)
                    for argument in remaining
                    for pattern in path_globs
                ):
                    continue
                matched = dict(guard)
                matched["argv"] = list(remaining)
                matches.append(matched)
                break
        return matches
    except (AttributeError, IndexError, OSError, TypeError, ValueError):
        return []


Probe = Callable[[Path, Mapping[str, str], Mapping[str, str]], "bool | None"]
MAX_ADVICE_CHARS = 600


def _read_json(path: Path) -> Any:
    """Return parsed JSON from ``path`` when it is a bounded, readable file."""
    try:
        if path.stat().st_size > MAX_INDEX_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def feature_index(checkout: Path, scope: Mapping[str, str]) -> dict[str, Any] | None:
    """Return the per-spec task index identified by ``scope`` or ``None``."""
    try:
        index_dir = checkout / "sdd" / "tasks" / "index"
        feature = scope.get("feature")
        candidates: list[Path] = []
        if feature:
            candidates.append(index_dir / f"{feature}.json")
        candidates.extend(sorted(path for path in index_dir.glob("*.json") if path.name != "_orphans.json"))

        task = scope.get("task")
        for path in candidates:
            payload = _read_json(path)
            if not isinstance(payload, dict):
                continue
            if feature and payload.get("feature") != feature and payload.get("feature_id") != feature:
                if path == candidates[0]:
                    continue
                continue
            if feature:
                return payload
            if task and any(isinstance(item, Mapping) and item.get("id") == task for item in payload.get("tasks", [])):
                return payload
        return None
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def _git_dir(checkout: Path) -> Path | None:
    """Return the git directory for a plain checkout or linked worktree."""
    try:
        git_entry = checkout / ".git"
        if git_entry.is_dir():
            return git_entry
        if not git_entry.is_file():
            return None
        first_line = git_entry.read_text(encoding="utf-8").splitlines()[0]
        marker = "gitdir:"
        if not first_line.lower().startswith(marker):
            return None
        gitdir = Path(first_line[len(marker) :].strip())
        if not gitdir.is_absolute():
            gitdir = checkout / gitdir
        return gitdir.resolve()
    except (IndexError, OSError, RuntimeError, TypeError, ValueError):
        return None


def current_branch(checkout: Path) -> str | None:
    """Return the branch named by the checkout's HEAD, or ``None`` when unknown."""
    try:
        git_dir = _git_dir(checkout)
        if git_dir is None:
            return None
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        prefix = "ref: refs/heads/"
        if not head.startswith(prefix):
            return None
        branch = head[len(prefix) :]
        return branch or None
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _settings(root: Path) -> dict[str, Any]:
    """Return procedure settings and the hotfix base, using safe defaults on bad input."""
    defaults = {"enabled": True, "enforce": True, "hotfix_base": "main"}
    try:
        payload = _read_json(root / "sdd" / "config.json")
        if not isinstance(payload, dict):
            return defaults
        procedure = payload.get("procedure", {})
        if not isinstance(procedure, Mapping):
            return defaults
        return {
            "enabled": procedure.get("enabled", True) if isinstance(procedure.get("enabled", True), bool) else True,
            "enforce": procedure.get("enforce", True) if isinstance(procedure.get("enforce", True), bool) else True,
            "hotfix_base": (
                payload.get("hotfix_base", "main") if isinstance(payload.get("hotfix_base", "main"), str) else "main"
            ),
        }
    except (AttributeError, OSError, TypeError, ValueError):
        return defaults


def _task(index: Mapping[str, Any] | None, task_id: str | None) -> Mapping[str, Any] | None:
    """Return a task entry from an index when both are available."""
    if index is None or not task_id:
        return None
    tasks = index.get("tasks", [])
    if not isinstance(tasks, list):
        return None
    return next((item for item in tasks if isinstance(item, Mapping) and item.get("id") == task_id), None)


def _probe_spec_exists(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether the scoped feature specification exists."""
    feature = scope.get("feature")
    return (checkout / "sdd" / "specs" / f"{feature}.spec.md").is_file() if feature else None


def _probe_index_exists(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether the scoped feature task index exists."""
    if not scope.get("feature") and not scope.get("task"):
        return None
    return feature_index(checkout, scope) is not None


def _probe_task_status(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether the scoped task has an expected status."""
    task = _task(feature_index(checkout, scope), scope.get("task"))
    expected = args.get("expect")
    if task is None or not isinstance(expected, str):
        return None
    return task.get("status") in expected.split("|")


def _probe_task_depends_done(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether all dependencies of the scoped task are done."""
    index = feature_index(checkout, scope)
    task = _task(index, scope.get("task"))
    if task is None or index is None:
        return None
    tasks = index.get("tasks", [])
    if not isinstance(tasks, list):
        return None
    statuses = {item.get("id"): item.get("status") for item in tasks if isinstance(item, Mapping) and item.get("id")}
    dependencies = task.get("depends_on", [])
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        return None
    return all(statuses.get(dependency) == "done" for dependency in dependencies)


def _probe_feature_tasks_done(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether every task in the scoped feature is closed."""
    index = feature_index(checkout, scope)
    if index is None:
        return None
    tasks = index.get("tasks", [])
    if not isinstance(tasks, list):
        return None
    return all(isinstance(item, Mapping) and item.get("status") in {"done", "done-with-issues"} for item in tasks)


def _probe_flow_base_allowed(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether the command's selected base is allowed for the current branch."""
    base = scope.get("base")
    branch = scope.get("branch")
    if base is None or branch is None:
        return None
    hotfix_base = args.get("hotfix_base", "main")
    return not (branch.startswith(("feat-", "fix-")) and base == hotfix_base)


def _probe_env_not_worker_sandbox(checkout: Path, scope: Mapping[str, str], args: Mapping[str, str]) -> bool | None:
    """Return whether the current process is outside a worker sandbox."""
    worker_sandbox = scope.get("worker_sandbox")
    if worker_sandbox is not None:
        return worker_sandbox != "1"
    return not any(marker in os.environ for marker in LAUNCHER_MARKERS)


LOCAL_PROBES: dict[str, Probe] = {
    "spec.exists": _probe_spec_exists,
    "index.exists": _probe_index_exists,
    "task.status": _probe_task_status,
    "task.depends_done": _probe_task_depends_done,
    "feature.tasks_done": _probe_feature_tasks_done,
    "flow.base_allowed": _probe_flow_base_allowed,
    "env.not_worker_sandbox": _probe_env_not_worker_sandbox,
}


def apply_check(
    check: Mapping[str, Any],
    checkout: Path,
    scope: Mapping[str, str],
    *,
    probes: Mapping[str, Probe] | None = None,
) -> bool | None:
    """Evaluate one index-shaped local check without allowing exceptions to escape."""
    try:
        registry = LOCAL_PROBES if probes is None else probes
        probe_name = check.get("probe")
        probe = registry.get(probe_name) if isinstance(probe_name, str) else None
        if probe is None:
            return None
        raw_args = check.get("args", {})
        args = dict(raw_args) if isinstance(raw_args, Mapping) else {}
        expect = check.get("expect", True)
        if isinstance(expect, str):
            args["expect"] = expect
            value = probe(checkout, scope, args)
            return value if value is True or value is False or value is None else None
        if not isinstance(expect, bool):
            return None
        value = probe(checkout, scope, args)
        return None if value is None else value == expect
    except Exception:  # noqa: BLE001 — a hook helper never raises
        return None


def _scope_for_guard(guard: Mapping[str, Any]) -> dict[str, str]:
    """Extract positional and flag-based scope values from a matched guard."""
    scope: dict[str, str] = {}
    argv = guard.get("argv", [])
    definitions = guard.get("scope", {})
    if not isinstance(argv, list) or not isinstance(definitions, Mapping):
        return scope
    positional = [value for value in argv if isinstance(value, str) and not value.startswith("-")]
    for name, definition in definitions.items():
        if not isinstance(name, str) or not isinstance(definition, Mapping):
            continue
        if isinstance(definition.get("argv"), int):
            index = definition["argv"]
            if 0 <= index < len(positional):
                scope[name] = positional[index]
            continue
        flags = definition.get("flag")
        if not isinstance(flags, str):
            continue
        for flag in flags.split("|"):
            for index, token in enumerate(argv):
                if not isinstance(token, str):
                    continue
                if token == flag and index + 1 < len(argv) and isinstance(argv[index + 1], str):
                    value = argv[index + 1]
                    if not value.startswith("-"):
                        scope[name] = value
                    break
                prefix = f"{flag}="
                if token.startswith(prefix):
                    scope[name] = token[len(prefix) :]
                    break
            if name in scope:
                break
    return scope


def _render_check(check: Mapping[str, Any], value: bool | None) -> str:
    """Render a failed or unknown precondition for an advice message."""
    probe = str(check.get("probe", "unknown"))
    expect = check.get("expect", True)
    rendered = f"{probe}={expect}" if isinstance(expect, str) else probe
    return f"{rendered} (unknown)" if value is None else rendered


def _fresh_sources(root: Path, index: Mapping[str, Any]) -> bool:
    """Return whether every source recorded in the compiled index still matches."""
    sources = index.get("sources", [])
    if not isinstance(sources, list):
        return False
    for source in sources:
        if not isinstance(source, Mapping) or not isinstance(source.get("path"), str):
            return False
        expected = source.get("sha1")
        if not isinstance(expected, str):
            return False
        path = root / source["path"]
        if not path.is_file() or hashlib.sha1(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:
    """Apply the compiled plane's guard decision table to one shell command."""
    try:
        environment = os.environ if env is None else env
        root = shared_root(cwd)
        checkout = checkout_root(cwd)
        if root is None or checkout is None:
            return Advice("none")
        index = load_index(root)
        if index is None:
            return Advice("none")
        settings = _settings(root)
        if not settings["enabled"]:
            return Advice("none")
        matches = match_guards(index, command)
        if not matches:
            return Advice("none")
        if not _fresh_sources(root, index):
            return Advice("none")

        branch = current_branch(checkout)
        worker_sandbox = "1" if any(marker in environment for marker in LAUNCHER_MARKERS) else "0"
        decisions: list[tuple[str, str, str, Mapping[str, Any]]] = []
        procedures = index.get("procedures", {})
        if not isinstance(procedures, Mapping):
            return Advice("none")
        for guard in matches:
            procedure_id = guard.get("procedure")
            procedure = procedures.get(procedure_id)
            if not isinstance(procedure_id, str) or not isinstance(procedure, Mapping):
                return Advice("none")
            scope = _scope_for_guard(guard)
            if branch is not None:
                scope["branch"] = branch
            scope["worker_sandbox"] = worker_sandbox
            raw_checks = procedure.get("preconditions", [])
            checks = [check for check in raw_checks if isinstance(check, Mapping) and check.get("cost") == "local"]
            results: list[tuple[Mapping[str, Any], bool | None]] = []
            for check in checks:
                check_args = dict(check)
                args = dict(check.get("args", {})) if isinstance(check.get("args"), Mapping) else {}
                args["hotfix_base"] = settings["hotfix_base"]
                check_args["args"] = args
                results.append((check_args, apply_check(check_args, checkout, scope)))

            mode = procedure.get("mode")
            kind = guard.get("kind")
            failed = [(check, value) for check, value in results if value is False]
            unknown = [(check, value) for check, value in results if value is None]
            if mode == "mandatory" and kind == "bypass":
                decisions.append(("deny", "do not replace this procedure by hand", procedure_id, procedure))
            elif mode == "mandatory" and kind == "entry" and failed:
                reason = ", ".join(_render_check(check, value) for check, value in failed)
                decisions.append(("deny", reason, procedure_id, procedure))
            elif mode == "mandatory" and kind == "entry" and unknown:
                reason = ", ".join(_render_check(check, value) for check, value in unknown)
                decisions.append(("advise", reason, procedure_id, procedure))
            elif mode == "advisory" and (kind == "bypass" or failed or unknown):
                details = failed + unknown
                reason = ", ".join(_render_check(check, value) for check, value in details)
                if kind == "bypass" and not reason:
                    reason = "do not replace this procedure by hand"
                decisions.append(("advise", reason, procedure_id, procedure))

        if not decisions:
            return Advice("none")
        selected = next((item for item in decisions if item[0] == "deny"), decisions[0])
        decision, reason, procedure_id, procedure = selected
        if decision == "deny" and (
            environment.get(ESCAPE_ENV) == "1"
            or environment.get("PARROT_ALLOW_DANGEROUS") == "1"
            or not settings["enforce"]
        ):
            decision = "advise"
        if decision == "deny":
            text = (
                f"Procedure {procedure_id} is mandatory: {reason}. Use: "
                f"{procedure.get('use_instead') or procedure.get('command')}. "
                "(Deliberate exception: ask the user to re-run with PARROT_ALLOW_PROCEDURE=1.)"
            )
        else:
            advice_text = procedure.get("advice") or procedure.get("use_instead") or procedure.get("command") or ""
            text = f"Procedure {procedure_id}: {reason}. {advice_text}"
        return Advice(decision, text[:MAX_ADVICE_CHARS])
    except Exception:  # noqa: BLE001 — a hook helper never raises
        return Advice("none")
