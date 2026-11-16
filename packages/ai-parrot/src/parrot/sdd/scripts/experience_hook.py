"""Bounded stdlib hook adapter; executable as an isolated module."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

from parrot.knowledge.wiki.experience.fastpath import (
    agy_exit_code,
    frozen_plane_dir,
    load_triggers,
    resolve_plane_dir,
    safe_open,
    session_file,
    update_session,
)
from parrot.knowledge.wiki.experience.transitions import on_outcome

_MAX_HOOK_INPUT_BYTES = 262_144
_MAX_TRANSCRIPT_TAIL_BYTES = 262_144
_MAX_SESSION_PENDING = 32
_KNOWN_HOSTS = frozenset({"claude", "codex", "agy"})
# A sandboxed launch injects its own isolated-interpreter Claude hooks (``--isolated``) and sets this
# marker; any other Claude registration of this hook (the portable one in a project's settings.json)
# then stands down. Codex/agy hooks are portable-only and are not affected.
ISOLATED_ENV = "PARROT_SDD_EXPERIENCE_ISOLATED"
_ISOLATED_FLAG = "--isolated"


@dataclass(frozen=True)
class _HookOutcome:
    """Immutable stdlib outcome adapted for the shared transition engine."""

    command: str
    ok: bool
    error: str
    observation_id: str


def main(argv: Sequence[str] | None = None) -> int:
    """Read bounded stdin and emit advisory host JSON; all paths return zero.

    Args:
        argv: Hook command-line arguments, excluding the executable name.

    Returns:
        Always zero so an advisory hook never blocks its host.
    """
    try:
        arguments = list(argv if argv is not None else sys.argv[1:])
        host, event = _hook_args(arguments)
        if host == "claude" and os.environ.get(ISOLATED_ENV) == "1" and _ISOLATED_FLAG not in arguments:
            return 0  # the session's injected isolated Claude hook handles this event
        if host not in _KNOWN_HOSTS or event not in {"post", "post-failure", "post-invocation"}:
            return 0
        payload = _read_payload()
        if payload is None:
            return 0
        cwd = payload.get("cwd")
        current_dir = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
        plane_dir = frozen_plane_dir(current_dir, os.environ) or resolve_plane_dir(current_dir)
        if plane_dir is None:
            return 0

        if event == "post-invocation":
            if host != "agy":
                return 0
            advice = handle_post_invocation(payload, plane_dir=plane_dir)
        elif event == "post":
            advice = handle_post(payload, host=host, event=event, plane_dir=plane_dir)
        elif host == "claude":
            advice = handle_post(payload, host=host, event=event, plane_dir=plane_dir)
        else:
            return 0

        if advice is not None or (host == "agy" and event == "post"):
            sys.stdout.write(json.dumps(render(advice or "", host=host, event=event), separators=(",", ":")) + "\n")
    except Exception:
        return 0
    return 0


def session_of(payload: Mapping[str, Any], env: Mapping[str, str]) -> str:
    """Return env/host session key suffixed by nonempty agent_id.

    Args:
        payload: Host callback payload.
        env: Environment variables visible to the hook.

    Returns:
        Opaque session identity, never used as a filesystem path.
    """
    session = env.get("PARROT_EXPERIENCE_SESSION")
    if not session:
        for key in ("session_id", "conversationId"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate:
                session = candidate
                break
    session = session or "unknown"
    agent_id = payload.get("agent_id")
    return f"{session}/{agent_id}" if isinstance(agent_id, str) and agent_id else session


def command_of(payload: Mapping[str, Any], host: str) -> str:
    """Extract Bash or run_command input; otherwise return empty string.

    Args:
        payload: Host callback payload.
        host: Calling host name.

    Returns:
        The host-reported command, or an empty string for non-command tools.
    """
    if host in {"claude", "codex"}:
        tool_input = payload.get("tool_input")
        command = tool_input.get("command") if isinstance(tool_input, Mapping) else None
        return command if payload.get("tool_name") == "Bash" and isinstance(command, str) else ""
    if host == "agy":
        tool_call = payload.get("toolCall")
        if not isinstance(tool_call, Mapping) or tool_call.get("name") != "run_command":
            return ""
        arguments = tool_call.get("args")
        command = arguments.get("CommandLine") if isinstance(arguments, Mapping) else None
        return command if isinstance(command, str) else ""
    return ""


def outcome_of(payload: Mapping[str, Any], host: str, event: str) -> tuple[bool, str] | None:
    """Return a known command outcome, otherwise None.

    Args:
        payload: Host callback payload.
        host: Calling host name.
        event: Normalized event name.

    Returns:
        A success/error pair only when the host provided a trustworthy result.
    """
    if host == "claude":
        if event == "post":
            return True, ""
        if event == "post-failure":
            error = payload.get("error")
            return False, error if isinstance(error, str) else ""
        return None
    if host == "codex" and event == "post":
        path = payload.get("transcript_path")
        tool_use_id = payload.get("tool_use_id")
        if isinstance(path, str) and path and isinstance(tool_use_id, str) and tool_use_id:
            return codex_outcome(Path(path), tool_use_id, max_bytes=_MAX_TRANSCRIPT_TAIL_BYTES)
    return None


def codex_outcome(transcript_path: Path, tool_use_id: str, *, max_bytes: int) -> tuple[bool, str] | None:
    """Join a bounded rollout tail by CommandExecution item.id.

    Args:
        transcript_path: Codex rollout JSONL path.
        tool_use_id: Command execution item id from the callback.
        max_bytes: Maximum rollout tail to inspect.

    Returns:
        The command result, or ``None`` for missing, unsafe, or unknown records.
    """
    for item in _tail_json_objects(transcript_path, max_bytes):
        payload = item.get("payload")
        if item.get("type") != "event_msg" or not isinstance(payload, Mapping):
            continue
        command = payload.get("item")
        if payload.get("type") != "item_completed" or not isinstance(command, Mapping):
            continue
        exit_code = command.get("exit_code")
        output = command.get("aggregated_output")
        if (
            command.get("type") != "CommandExecution"
            or command.get("id") != tool_use_id
            or command.get("status") not in {"completed", "failed"}
            or not isinstance(exit_code, int)
            or isinstance(exit_code, bool)
            or not isinstance(output, str)
        ):
            continue
        return exit_code == 0, output
    return None


def agy_outcome(transcript_path: Path, step_idx: int, *, max_bytes: int) -> tuple[bool, str] | None:
    """Read a GENERIC step result and header-only exit status.

    Args:
        transcript_path: Agy transcript JSONL path.
        step_idx: Host step index to resolve.
        max_bytes: Maximum transcript tail to inspect.

    Returns:
        The command result, or ``None`` for missing, unsafe, or unknown records.
    """
    for item in _tail_json_objects(transcript_path, max_bytes):
        content = item.get("content")
        if item.get("step_index") != step_idx or item.get("type") != "GENERIC" or not isinstance(content, str):
            continue
        exit_code = agy_exit_code(content)
        if exit_code is None:
            return None
        return exit_code == 0, _agy_error(content) if exit_code else ""
    return None


def observation_of(payload: Mapping[str, Any], host: str) -> str:
    """Return tool_use_id or conversationId:stepIdx.

    Args:
        payload: Host callback payload.
        host: Calling host name.

    Returns:
        Stable host observation identity, or an empty string when unavailable.
    """
    if host in {"claude", "codex"}:
        tool_use_id = payload.get("tool_use_id")
        return tool_use_id if isinstance(tool_use_id, str) else ""
    if host == "agy":
        conversation = payload.get("conversationId")
        step = payload.get("stepIdx")
        return f"{conversation}:{step}" if isinstance(conversation, str) and isinstance(step, int) else ""
    return ""


def handle_post(payload: Mapping[str, Any], *, host: str, event: str, plane_dir: Path) -> str | None:
    """Handle known outcomes, or queue an agy pending transcript lookup.

    Args:
        payload: Host callback payload.
        host: Calling host name.
        event: Normalized hook event.
        plane_dir: Shared experience plane.

    Returns:
        Advisory text emitted by the transition engine, if any.
    """
    command = command_of(payload, host)
    if not command:
        return None
    if not _within_file_limit(plane_dir / "triggers.json", _MAX_HOOK_INPUT_BYTES):
        return None
    session = session_of(payload, os.environ)
    if host == "agy":
        step = payload.get("stepIdx")
        if event != "post" or not isinstance(step, int) or isinstance(step, bool):
            return None

        def queue(state: dict) -> dict:
            pending = state.setdefault("agy_pending", [])
            if not isinstance(pending, list):
                pending = []
                state["agy_pending"] = pending
            pending.append({"step_idx": step, "command": command, "observation_id": observation_of(payload, host)})
            del pending[:-_MAX_SESSION_PENDING]
            return state

        update_session(plane_dir, session, queue)
        return None

    outcome = outcome_of(payload, host, event)
    if outcome is None:
        return None
    return on_outcome(
        plane_dir,
        session=session,
        command=command,
        outcome=_HookOutcome(command, outcome[0], outcome[1], observation_of(payload, host)),
        seat=host,
        matcher=_trigger_matcher(plane_dir),
    )


def handle_post_invocation(payload: Mapping[str, Any], *, plane_dir: Path) -> str | None:
    """Resolve agy pending commands; unknown results defer to replay.

    Args:
        payload: Agy PostInvocation callback payload.
        plane_dir: Shared experience plane.

    Returns:
        The first produced advisory text, if any.
    """
    session = session_of(payload, os.environ)
    try:
        if not session_file(plane_dir, session).exists():
            return None
    except OSError:
        return None

    captured: list[dict[str, Any]] = []

    def take_pending(state: dict) -> dict:
        pending = state.get("agy_pending")
        if isinstance(pending, list):
            captured.extend(item for item in pending if isinstance(item, dict))
        state["agy_pending"] = []
        return state

    if update_session(plane_dir, session, take_pending) is None:
        return None
    transcript = payload.get("transcriptPath")
    if not isinstance(transcript, str) or not transcript:
        return None
    advice: str | None = None
    for pending in captured:
        step = pending.get("step_idx")
        command = pending.get("command")
        observation = pending.get("observation_id")
        if (
            not isinstance(step, int)
            or isinstance(step, bool)
            or not isinstance(command, str)
            or not isinstance(observation, str)
        ):
            continue
        outcome = agy_outcome(Path(transcript), step, max_bytes=_MAX_TRANSCRIPT_TAIL_BYTES)
        if outcome is None:
            continue
        result = on_outcome(
            plane_dir,
            session=session,
            command=command,
            outcome=_HookOutcome(command, outcome[0], outcome[1], observation),
            seat="agy",
            matcher=_trigger_matcher(plane_dir),
        )
        if advice is None and result is not None:
            advice = result
    return advice


def render(advice: str, *, host: str, event: str) -> dict[str, Any]:
    """Return the exact M4 host response envelope.

    Args:
        advice: Advisory text to pass to the host.
        host: Calling host name.
        event: Normalized hook event.

    Returns:
        The host-specific advisory envelope.
    """
    if host == "claude" and event in {"post", "post-failure"}:
        name = "PostToolUseFailure" if event == "post-failure" else "PostToolUse"
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": advice}, "suppressOutput": True}
    if host == "codex" and event == "post":
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": advice}}
    if host == "agy" and event == "post-invocation" and advice:
        return {"injectSteps": [{"systemMessage": {"systemMessage": advice}}]}
    return {}


def _hook_args(argv: Sequence[str]) -> tuple[str, str]:
    """Extract the supported host and event flags without a CLI dependency."""
    values: dict[str, str] = {}
    iterator = iter(argv)
    for argument in iterator:
        if argument not in {"--host", "--event"}:
            continue
        value = next(iterator, "")
        if isinstance(value, str):
            values[argument] = value
    return values.get("--host", ""), values.get("--event", "")


def _read_payload() -> Mapping[str, Any] | None:
    """Read one bounded JSON object from stdin without raising."""
    raw = sys.stdin.buffer.read(_MAX_HOOK_INPUT_BYTES + 1)
    if len(raw) > _MAX_HOOK_INPUT_BYTES:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _tail_json_objects(path: Path, max_bytes: int) -> list[Mapping[str, Any]]:
    """Return complete JSON objects from a bounded regular-file tail."""
    if max_bytes < 0:
        return []
    descriptor = safe_open(path, os.O_RDONLY)
    if descriptor is None:
        return []
    try:
        size = os.fstat(descriptor).st_size
        start = max(size - max_bytes, 0)
        os.lseek(descriptor, start, os.SEEK_SET)
        raw = os.read(descriptor, max_bytes + 1)
        if len(raw) > max_bytes:
            return []
        if start:
            marker = raw.find(b"\n")
            if marker < 0:
                return []
            raw = raw[marker + 1 :]
        result: list[Mapping[str, Any]] = []
        for line in raw.splitlines():
            try:
                item = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(item, Mapping):
                result.append(item)
        return result
    except OSError:
        return []
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _agy_error(content: str) -> str:
    """Return only agy's command-output body after its trusted header."""
    marker = "Command output:"
    before, found, after = content.partition(marker)
    return after.lstrip("\r\n") if found else ""


def _trigger_matcher(plane_dir: Path):
    """Build the hook's bounded published-trigger matcher."""
    triggers = load_triggers(plane_dir, max_bytes=_MAX_HOOK_INPUT_BYTES)

    def match(executable: str, subcommand: str, error: str) -> Mapping[str, Any] | None:
        normalized_error = error.casefold()
        for stub in triggers.get(executable, []):
            if not isinstance(stub, Mapping) or stub.get("subcommand") != subcommand:
                continue
            tokens = stub.get("error_tokens")
            if isinstance(tokens, list) and all(
                isinstance(token, str) and token.casefold() in normalized_error for token in tokens
            ):
                return stub
        return None

    return match


def _within_file_limit(path: Path, max_bytes: int) -> bool:
    """Return whether a present regular file fits the hook's read budget."""
    descriptor = safe_open(path, os.O_RDONLY)
    if descriptor is None:
        return not path.exists()
    try:
        return os.fstat(descriptor).st_size <= max_bytes
    except OSError:
        return False
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
