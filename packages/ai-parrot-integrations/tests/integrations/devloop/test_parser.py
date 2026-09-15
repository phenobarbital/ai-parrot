"""Tests for parrot.integrations.devloop.parser (TASK-3201)."""

import pytest

from parrot.integrations.devloop.models import CommandSyntaxError
from parrot.integrations.devloop.parser import USAGE, parse_command


def test_dispatch_feature_with_flags() -> None:
    cmd = parse_command('--type feature --jira NAV-1 --base staging --title "Slack card" Ship the status card')
    assert cmd.action == "dispatch" and cmd.type == "feature" and cmd.jira_issue_key == "NAV-1"
    assert cmd.base_branch == "staging" and cmd.title == "Slack card" and cmd.prompt == "Ship the status card"


@pytest.mark.parametrize("text", ["status", "help", "cancel run-abc12345"])
def test_subcommands(text: str) -> None:
    assert parse_command(text).action == text.split()[0]


def test_cancel_requires_run_id() -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command("cancel")


def test_missing_type_is_error() -> None:
    with pytest.raises(CommandSyntaxError) as exc:
        parse_command("just a prompt")
    assert exc.value.usage == USAGE


def test_enhancement_rejected_naming_supported_types() -> None:
    with pytest.raises(CommandSyntaxError, match="feature|bug"):
        parse_command("--type enhancement do it")


def test_unknown_flag_is_error() -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command("--type bug --frobnicate x prompt here")


def test_bad_base_is_error() -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command("--type bug --base production a bug prompt")


def test_prompt_after_flags() -> None:
    cmd = parse_command("--type bug the prompt itself")
    assert cmd.prompt == "the prompt itself"


def test_empty_text_is_error() -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command("")


def test_missing_prompt_is_error() -> None:
    with pytest.raises(CommandSyntaxError):
        parse_command("--type bug")


def test_cancel_run_id_field() -> None:
    cmd = parse_command("cancel run-abc12345")
    assert cmd.run_id == "run-abc12345"
