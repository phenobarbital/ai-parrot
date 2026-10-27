"""Tests for the /sdd-done closeout-hooks TOML registry."""
from pathlib import Path

import pytest

from scripts.sdd.closeout_hooks_config import HooksConfigError, load_hooks


def _cfg(tmp_path: Path, body: str) -> Path:
    """Write a hooks config below an isolated repository root."""
    hooks_dir = tmp_path / ".parrot"
    hooks_dir.mkdir()
    (hooks_dir / "sdd_hooks.toml").write_text(body, encoding="utf-8")
    return tmp_path


def test_absent_file_is_empty(tmp_path: Path) -> None:
    """A repository without a hooks file has no subscribed hooks."""
    config = load_hooks(tmp_path)
    assert config.pre_pr == []
    assert config.post_pr == []
    assert config.on_failure == []


def test_valid_all_kinds_load(tmp_path: Path) -> None:
    """Command, agent, and builtin hooks preserve their declared fields."""
    config = load_hooks(
        _cfg(
            tmp_path,
            """
            [[hooks.pre_pr]]
            name = "lint"
            kind = "command"
            run = "ruff check"

            [[hooks.pre_pr]]
            name = "e2e"
            kind = "agent"
            agent = "e2e-ui-tester"
            prompt = "Test {feat_id}"

            [[hooks.post_pr]]
            name = "notify"
            kind = "builtin"
            builtin = "telegram.send"
            with = { chat_id_env = "CHAT_ID" }
            """,
        )
    )
    assert [hook.name for hook in config.pre_pr] == ["lint", "e2e"]
    assert config.post_pr[0].with_ == {"chat_id_env": "CHAT_ID"}


def test_malformed_toml_raises(tmp_path: Path) -> None:
    """Malformed TOML is never treated as an empty configuration."""
    with pytest.raises(HooksConfigError):
        load_hooks(_cfg(tmp_path, "[hooks"))


def test_blocking_on_post_pr_raises(tmp_path: Path) -> None:
    """Post-PR hooks cannot block closeout."""
    with pytest.raises(HooksConfigError):
        load_hooks(
            _cfg(
                tmp_path,
                """
                [[hooks.post_pr]]
                name = "notify"
                kind = "command"
                run = "echo notify"
                blocking = true
                """,
            )
        )


def test_unknown_builtin_raises(tmp_path: Path) -> None:
    """Only builtins owned by the closeout dispatcher are accepted."""
    with pytest.raises(HooksConfigError):
        load_hooks(_cfg(tmp_path, '[[hooks.pre_pr]]\nname = "bad"\nkind = "builtin"\nbuiltin = "unknown"'))


def test_push_send_unknown_provider_raises(tmp_path: Path) -> None:
    """Push notifications reject providers outside the supported set."""
    with pytest.raises(HooksConfigError):
        load_hooks(
            _cfg(
                tmp_path,
                '[[hooks.pre_pr]]\nname = "push"\nkind = "builtin"\nbuiltin = "push.send"\nwith = { provider = "other" }',
            )
        )


@pytest.mark.parametrize("provider", ["ntfy", "gotify"])
def test_push_send_ntfy_and_gotify_ok(tmp_path: Path, provider: str) -> None:
    """Both supported push notification providers load successfully."""
    config = load_hooks(
        _cfg(
            tmp_path,
            f'[[hooks.pre_pr]]\nname = "push"\nkind = "builtin"\nbuiltin = "push.send"\nwith = {{ provider = "{provider}" }}',
        )
    )
    assert config.pre_pr[0].with_["provider"] == provider


def test_duplicate_name_raises(tmp_path: Path) -> None:
    """A hook event cannot subscribe two hooks with the same name."""
    with pytest.raises(HooksConfigError):
        load_hooks(
            _cfg(
                tmp_path,
                """
                [[hooks.pre_pr]]
                name = "check"
                kind = "command"
                run = "first"

                [[hooks.pre_pr]]
                name = "check"
                kind = "command"
                run = "second"
                """,
            )
        )


@pytest.mark.parametrize(
    "body",
    [
        '[[hooks.pre_pr]]\nname = "command"\nkind = "command"',
        '[[hooks.pre_pr]]\nname = "agent"\nkind = "agent"\nagent = "reviewer"',
    ],
)
def test_missing_kind_field_raises(tmp_path: Path, body: str) -> None:
    """Each hook kind requires the fields needed for its execution mode."""
    with pytest.raises(HooksConfigError):
        load_hooks(_cfg(tmp_path, body))


def test_unknown_event_key_raises(tmp_path: Path) -> None:
    """The [hooks] table accepts only the three documented event names."""
    with pytest.raises(HooksConfigError):
        load_hooks(_cfg(tmp_path, '[[hooks.other]]\nname = "x"\nkind = "command"\nrun = "echo x"'))


def test_extra_hook_key_raises(tmp_path: Path) -> None:
    """Unknown hook keys fail rather than being ignored."""
    with pytest.raises(HooksConfigError):
        load_hooks(_cfg(tmp_path, '[[hooks.pre_pr]]\nname = "x"\nkind = "command"\nrun = "echo x"\nextra = true'))


def test_disabled_hook_filtered_by_for_event(tmp_path: Path) -> None:
    """Disabled hooks remain available in the model but are not dispatched."""
    config = load_hooks(
        _cfg(
            tmp_path,
            """
            [[hooks.pre_pr]]
            name = "disabled"
            kind = "command"
            run = "echo disabled"
            enabled = false

            [[hooks.pre_pr]]
            name = "enabled"
            kind = "command"
            run = "echo enabled"
            """,
        )
    )
    assert [hook.name for hook in config.for_event("pre_pr")] == ["enabled"]
