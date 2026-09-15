"""``/devloop`` text → :class:`DevLoopCommand` (spec §3 Module 5, FEAT-555)."""

from __future__ import annotations

import argparse
import shlex

from parrot.integrations.devloop.models import CommandSyntaxError, DevLoopCommand

USAGE = """*Usage*
`/devloop --type feature|bug [--jira KEY] [--base dev|staging] [--title "…"] [--component NAME] [--ac "<cmd>"] <prompt>`
`/devloop status` · `/devloop cancel <run-id>` · `/devloop help`
Types: `feature` (brainstorm + Open Questions) and `bug` (log-driven triage). `enhancement` is not available on Slack yet."""

_SUBCOMMANDS = ("status", "cancel", "help")
_TYPES = ("feature", "bug")
_BASE_BRANCHES = ("dev", "staging")


def _build_parser() -> argparse.ArgumentParser:
    """Flag-only parser; positionals are collected as the prompt via parse_known_args."""
    parser = argparse.ArgumentParser(prog="/devloop", add_help=False, exit_on_error=False)
    parser.add_argument("--type", dest="type_", default=None)
    parser.add_argument("--jira", default=None)
    parser.add_argument("--base", default=None)
    parser.add_argument("--title", default=None)
    parser.add_argument("--component", default=None)
    parser.add_argument("--ac", default=None)
    return parser


def parse_command(text: str) -> DevLoopCommand:
    """Parse the slash-command text.

    Args:
        text: The raw text following ``/devloop`` in Slack.

    Returns:
        The parsed :class:`DevLoopCommand`.

    Raises:
        CommandSyntaxError: empty text, unknown flag, bad ``--type``/``--base``
            value, missing prompt or missing ``--type`` for a dispatch,
            ``cancel`` without a run id. Slack caps slash-command text at
            3000 characters; that limit is not enforced here — it is
            Slack's own truncation, not this parser's concern.
    """
    try:
        tokens = shlex.split(text or "")
    except ValueError as exc:  # unbalanced quotes
        raise CommandSyntaxError(f"could not parse command: {exc}", usage=USAGE) from exc
    if not tokens:
        raise CommandSyntaxError("empty command", usage=USAGE)

    if tokens[0].lower() in _SUBCOMMANDS:
        sub = tokens[0].lower()
        if sub == "help":
            return DevLoopCommand(action="help")
        if sub == "status":
            return DevLoopCommand(action="status")
        # cancel
        if len(tokens) < 2 or not tokens[1].strip():
            raise CommandSyntaxError("cancel requires a run id: /devloop cancel <run-id>", usage=USAGE)
        return DevLoopCommand(action="cancel", run_id=tokens[1].strip())

    try:
        ns, rest = _build_parser().parse_known_args(tokens)
    except argparse.ArgumentError as exc:
        raise CommandSyntaxError(str(exc), usage=USAGE) from exc

    unknown = [t for t in rest if t.startswith("--")]
    if unknown:
        raise CommandSyntaxError(f"unknown flag(s): {', '.join(unknown)}", usage=USAGE)

    if ns.type_ not in _TYPES:
        raise CommandSyntaxError(f"--type is required and must be one of feature|bug (got {ns.type_!r})", usage=USAGE)
    if ns.base is not None and ns.base not in _BASE_BRANCHES:
        raise CommandSyntaxError(f"--base must be one of dev|staging (got {ns.base!r})", usage=USAGE)

    prompt = " ".join(rest).strip()
    if not prompt:
        raise CommandSyntaxError("a prompt is required after the flags", usage=USAGE)

    return DevLoopCommand(
        action="dispatch",
        type=ns.type_,
        prompt=prompt,
        title=ns.title,
        jira_issue_key=ns.jira,
        base_branch=ns.base,
        component=ns.component,
        acceptance_command=ns.ac,
    )
