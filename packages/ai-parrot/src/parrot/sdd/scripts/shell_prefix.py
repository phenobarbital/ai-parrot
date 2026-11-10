"""Apply the SDD sandbox after auto mode has reviewed a shell command.

Claude Code invokes this prefix with exactly one argument: the command string.
That lets known hook and MCP launch commands pass through while ordinary shell
commands enter the configured sandbox.  Any setup error exits with status 2,
because a failed PreToolUse hook must block instead of allowing an unguarded
command to proceed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn, Sequence

if __package__:
    from .worktree_environment import protected_argv, rtk_rewrite
else:  # run as a script: this file's directory is sys.path[0]
    from worktree_environment import protected_argv, rtk_rewrite


POLICY_ENV = "PARROT_SDD_SHELL_PREFIX_POLICY"
TOKEN_ENV = "PARROT_SDD_SHELL_PREFIX_TOKEN"
_POLICY_KEYS = {"schema_version", "mode", "worktree", "hook_commands", "mcp_argv", "rtk"}
_EVAL_PAYLOAD = re.compile(r""" && eval (?P<word>(?:'[^']*'|"(?:\\.|[^"\\])*"|\\.|[^\s'"<])+?) < /dev/null""")


@dataclass(frozen=True)
class PrefixPolicy:
    """The launcher's immutable policy for one shell-prefix session."""

    schema_version: int
    mode: str
    worktree: str
    hook_commands: tuple[str, ...]
    mcp_argv: tuple[tuple[str, ...], ...]
    rtk: bool


@dataclass(frozen=True)
class PrefixDecision:
    """The executable argv selected for a prefixed command."""

    kind: Literal["passthrough", "wrap", "run"]
    argv: list[str]


def _invalid_policy(reason: str) -> ValueError:
    """Build a consistent invalid-policy error.

    Args:
        reason: The schema or filesystem violation.

    Returns:
        A policy-validation exception.
    """
    return ValueError(f"invalid policy: {reason}")


def load_policy(path: str | Path) -> tuple[PrefixPolicy, str]:
    """Load a secure prefix policy and return its content digest.

    Args:
        path: Policy JSON file supplied by the launcher.

    Returns:
        The validated policy and SHA-256 digest of its original bytes.

    Raises:
        ValueError: If the file or its JSON schema is unsafe or invalid.
        OSError: If the policy cannot be inspected or read.
    """
    policy_path = Path(path)
    metadata = policy_path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise _invalid_policy("must not be a symlink")
    if metadata.st_mode & 0o022:
        raise _invalid_policy("must not be writable by group or others")

    contents = policy_path.read_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    try:
        document = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _invalid_policy("must contain valid JSON") from exc
    if not isinstance(document, dict):
        raise _invalid_policy("must be an object")
    if set(document) != _POLICY_KEYS:
        raise _invalid_policy("has missing or unknown keys")

    schema_version = document["schema_version"]
    mode = document["mode"]
    worktree = document["worktree"]
    hook_commands = document["hook_commands"]
    mcp_argv = document["mcp_argv"]
    rtk = document["rtk"]
    if type(schema_version) is not int or schema_version != 1:
        raise _invalid_policy("schema_version must be 1")
    if mode not in {"legacy", "native"}:
        raise _invalid_policy("mode must be legacy or native")
    if not isinstance(worktree, str) or not Path(worktree).is_absolute():
        raise _invalid_policy("worktree must be an absolute string")
    if not isinstance(hook_commands, list) or not all(isinstance(command, str) for command in hook_commands):
        raise _invalid_policy("hook_commands must be a list of strings")
    if not isinstance(mcp_argv, list) or not all(
        isinstance(command, list) and all(isinstance(argument, str) for argument in command) for command in mcp_argv
    ):
        raise _invalid_policy("mcp_argv must be a list of string lists")
    if type(rtk) is not bool:
        raise _invalid_policy("rtk must be a boolean")

    return (
        PrefixPolicy(
            schema_version=schema_version,
            mode=mode,
            worktree=worktree,
            hook_commands=tuple(hook_commands),
            mcp_argv=tuple(tuple(command) for command in mcp_argv),
            rtk=rtk,
        ),
        digest,
    )


def decide(arg: str, policy: PrefixPolicy, cwd: Path) -> PrefixDecision:
    """Choose whether a prefix invocation passes through or enters a sandbox.

    Args:
        arg: The sole command-string argument supplied by Claude Code.
        policy: The validated session policy.
        cwd: Current working directory used for the legacy sandbox.

    Returns:
        The kind of execution and argv to execute.
    """
    shell_argv = ["/bin/bash", "-c", arg]
    if arg in policy.hook_commands:
        return PrefixDecision("passthrough", shell_argv)
    try:
        parsed = shlex.split(arg)
    except ValueError:
        parsed = None
    if parsed is not None and tuple(parsed) in policy.mcp_argv:
        return PrefixDecision("passthrough", shell_argv)
    if policy.mode == "legacy":
        return PrefixDecision("wrap", protected_argv(cwd, shell_argv))
    return PrefixDecision("run", shell_argv)


def rtk_payload(arg: str) -> str:
    """Rewrite the one Claude Bash ``eval`` payload when RTK has an equivalent command.

    Args:
        arg: Claude Code's complete Bash preamble passed to the shell prefix.

    Returns:
        The preamble with only its eval word replaced, or the original bytes when it does not have
        exactly one supported payload or RTK cannot improve it.
    """
    matches = tuple(_EVAL_PAYLOAD.finditer(arg))
    if len(matches) != 1:
        return arg
    match = matches[0]
    try:
        parsed = shlex.split(match.group("word"), posix=True)
    except ValueError:
        return arg
    if len(parsed) != 1:
        return arg
    rewritten = rtk_rewrite(parsed[0])
    if rewritten is None or rewritten == parsed[0]:
        return arg
    return f"{arg[:match.start('word')]}{shlex.quote(rewritten)}{arg[match.end('word') :]}"


def _fail(reason: str) -> NoReturn:
    """Report a fail-closed prefix error and terminate.

    Args:
        reason: The failure explanation.
    """
    print(f"sdd shell prefix: {reason}", file=sys.stderr)
    raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> NoReturn:
    """Execute the one configured shell-prefix command or fail closed.

    Args:
        argv: Command arguments excluding the program name; defaults to ``sys.argv[1:]``.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        _fail("expected exactly one command argument")
    policy_path = os.environ.get(POLICY_ENV)
    if not policy_path:
        _fail(f"missing {POLICY_ENV}")
    try:
        policy, token = load_policy(policy_path)
        decision = decide(arguments[0], policy, Path.cwd())
        if decision.kind in {"wrap", "run"} and policy.rtk:
            rewritten = rtk_payload(arguments[0])
            if rewritten != arguments[0]:
                decision = decide(rewritten, policy, Path.cwd())
        environment = os.environ.copy()
        if decision.kind == "passthrough":
            environment[TOKEN_ENV] = token
        else:
            environment.pop(TOKEN_ENV, None)
        os.execvpe(decision.argv[0], decision.argv, environment)
    except (OSError, RuntimeError, ValueError) as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
