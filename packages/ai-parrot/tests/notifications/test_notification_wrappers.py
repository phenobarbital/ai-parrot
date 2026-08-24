"""Tests for the homologated ``NotificationMixin.send_*`` convenience wrappers.

Every wrapper must share one shape: canonical ``message``/``recipients``
parameters, explicit ``report``/``with_attachments``/``provider_options``
pass-throughs, legacy per-provider aliases, and a never-raise contract
that returns a uniform error dict.
"""

import importlib
import inspect
import logging
from unittest.mock import AsyncMock

import pytest


def _load_notifications():
    mod = importlib.import_module("parrot.notifications")
    if not hasattr(mod, "NotificationMixin"):
        pytest.skip("parrot.notifications resolved as namespace package")
    return mod


def _owner(send_notification=None):
    """Mixin instance whose send_notification is captured, not executed."""
    notifications = _load_notifications()

    class _Owner(notifications.NotificationMixin):
        def __init__(self):
            self.logger = logging.getLogger("test.notifications.wrappers")

    owner = _Owner()
    owner.send_notification = send_notification or AsyncMock(
        return_value={"status": "success"}
    )
    return owner


# The homologated wrapper matrix: name -> (provider value, recipient alias)
WRAPPERS = {
    "send_email": ("email", None),
    "send_slack_message": ("slack", "channel"),
    "send_telegram_message": ("telegram", "chat"),
    "send_teams_message": ("teams", "recipient"),
    "send_teams_card": ("teams", "recipient"),
}


# ===================================================================
# Signature homologation
# ===================================================================

class TestSignatureConsistency:
    """Every wrapper exposes the same canonical surface."""

    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    def test_canonical_parameters_present(self, name):
        notifications = _load_notifications()
        params = inspect.signature(
            getattr(notifications.NotificationMixin, name)
        ).parameters
        for expected in (
            "message",
            "recipients",
            "report",
            "with_attachments",
            "provider_options",
        ):
            assert expected in params, f"{name} is missing '{expected}'"
        assert "kwargs" in params, f"{name} must forward **kwargs"

    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    def test_message_and_recipients_are_first_two_positionals(self, name):
        notifications = _load_notifications()
        params = list(
            inspect.signature(getattr(notifications.NotificationMixin, name)).parameters
        )
        assert params[:3] == ["self", "message", "recipients"], (
            f"{name} positional order is {params[:3]}"
        )

    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    def test_legacy_alias_still_accepted(self, name):
        _, alias = WRAPPERS[name]
        if alias is None:
            pytest.skip("email has no legacy recipient alias")
        notifications = _load_notifications()
        params = inspect.signature(
            getattr(notifications.NotificationMixin, name)
        ).parameters
        assert alias in params
        assert params[alias].kind is inspect.Parameter.KEYWORD_ONLY


# ===================================================================
# Delegation
# ===================================================================

class TestDelegation:
    """Wrappers delegate to send_notification with the right provider."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_delegates_with_provider(self, name):
        notifications = _load_notifications()
        owner = _owner()

        await getattr(owner, name)(message="hello", recipients="target")

        owner.send_notification.assert_awaited_once()
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["provider"] is notifications.NotificationProvider(
            WRAPPERS[name][0]
        )
        assert kwargs["message"] == "hello"
        assert kwargs["recipients"] == "target"
        assert kwargs["with_attachments"] is True
        assert kwargs["provider_options"] is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_positional_call_works(self, name):
        owner = _owner()
        await getattr(owner, name)("hello", "target")
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["message"] == "hello"
        assert kwargs["recipients"] == "target"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_recipient_alias_resolves(self, name):
        _, alias = WRAPPERS[name]
        if alias is None:
            pytest.skip("email has no legacy recipient alias")
        owner = _owner()
        await getattr(owner, name)(message="hi", **{alias: "legacy-target"})
        assert owner.send_notification.await_args.kwargs["recipients"] == "legacy-target"

    @pytest.mark.asyncio
    async def test_teams_card_payload_alias_resolves(self):
        owner = _owner()
        card = {"type": "AdaptiveCard"}
        await owner.send_teams_card(card=card, recipient="user@example.com")
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["message"] is card
        assert kwargs["recipients"] == "user@example.com"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_provider_options_and_kwargs_forwarded(self, name):
        owner = _owner()
        await getattr(owner, name)(
            message="hi",
            recipients="target",
            with_attachments=False,
            provider_options={"bot_token": "abc"},
            custom_flag=42,
        )
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["provider_options"] == {"bot_token": "abc"}
        assert kwargs["with_attachments"] is False
        assert kwargs["custom_flag"] == 42

    @pytest.mark.asyncio
    async def test_email_specific_parameters_forwarded(self):
        owner = _owner()
        await owner.send_email(
            message="body", recipients="a@b.com", subject="Subj", template="tpl"
        )
        kwargs = owner.send_notification.await_args.kwargs
        assert kwargs["subject"] == "Subj"
        assert kwargs["template"] == "tpl"

    @pytest.mark.asyncio
    async def test_telegram_disable_notification_forwarded(self):
        owner = _owner()
        await owner.send_telegram_message(
            message="body", recipients="123", disable_notification=True
        )
        assert owner.send_notification.await_args.kwargs["disable_notification"] is True

    @pytest.mark.asyncio
    async def test_teams_message_and_card_share_one_path(self):
        """The two Teams wrappers differ only in payload."""
        card = {"type": "AdaptiveCard"}
        text_owner, card_owner = _owner(), _owner()

        await text_owner.send_teams_message(message="plain", recipients="chan")
        await card_owner.send_teams_card(message=card, recipients="chan")

        text_kwargs = dict(text_owner.send_notification.await_args.kwargs)
        card_kwargs = dict(card_owner.send_notification.await_args.kwargs)
        assert text_kwargs.pop("message") == "plain"
        assert card_kwargs.pop("message") is card
        assert text_kwargs == card_kwargs


# ===================================================================
# Never-raise contract
# ===================================================================

class TestNeverRaises:
    """Every wrapper returns an error dict instead of propagating."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_missing_recipient_returns_error_dict(self, name):
        owner = _owner()
        result = await getattr(owner, name)(message="hi")
        assert result["status"] == "error"
        assert result["provider"] == WRAPPERS[name][0]
        assert "no recipient" in result["error"].lower()
        owner.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_send_failure_returns_error_dict(self, name):
        owner = _owner(AsyncMock(side_effect=RuntimeError("provider exploded")))
        result = await getattr(owner, name)(message="hi", recipients="target")
        assert result == {
            "status": "error",
            "error": "provider exploded",
            "provider": WRAPPERS[name][0],
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_conflicting_alias_returns_error_dict(self, name):
        _, alias = WRAPPERS[name]
        if alias is None:
            pytest.skip("email has no legacy recipient alias")
        owner = _owner()
        result = await getattr(owner, name)(
            message="hi", recipients="canonical", **{alias: "legacy"}
        )
        assert result["status"] == "error"
        assert "aliases" in result["error"]
        owner.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_conflicting_payload_alias_returns_error_dict(self):
        owner = _owner()
        result = await owner.send_teams_card(
            message={"type": "AdaptiveCard"},
            card={"type": "AdaptiveCard"},
            recipients="chan",
        )
        assert result["status"] == "error"
        assert "aliases" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_provider_string_does_not_raise(self):
        """Regression: the except block used to call .value on a raw str."""
        notifications = _load_notifications()

        class _Owner(notifications.NotificationMixin):
            def __init__(self):
                self.logger = logging.getLogger("test.notifications.wrappers")

        result = await _Owner().send_notification(
            message="hi", recipients="a@b.com", provider="carrier-pigeon"
        )
        assert result["status"] == "error"
        assert result["provider"] == "carrier-pigeon"


# ===================================================================
# Payload validation
# ===================================================================

class TestTeamsCardValidation:

    @pytest.mark.asyncio
    async def test_non_card_payload_warns_but_still_sends(self, caplog):
        owner = _owner()
        with caplog.at_level(logging.WARNING):
            result = await owner.send_teams_card(
                message="just text", recipients="chan"
            )
        assert result["status"] == "success"
        assert "not an Adaptive Card" in caplog.text

    @pytest.mark.asyncio
    async def test_card_payload_does_not_warn(self, caplog):
        owner = _owner()
        with caplog.at_level(logging.WARNING):
            await owner.send_teams_card(
                message={"type": "AdaptiveCard"}, recipients="chan"
            )
        assert "not an Adaptive Card" not in caplog.text


# ===================================================================
# Error-payload helper
# ===================================================================

class TestNotificationErrorHelper:

    def test_uniform_shape_for_enum_str_and_none(self):
        notifications = _load_notifications()
        mixin = notifications.NotificationMixin
        exc = ValueError("boom")
        assert mixin._notification_error(
            exc, notifications.NotificationProvider.SLACK
        ) == {"status": "error", "error": "boom", "provider": "slack"}
        assert mixin._notification_error(exc, "TELEGRAM")["provider"] == "telegram"
        assert mixin._notification_error(exc, None)["provider"] is None

    def test_resolve_alias(self):
        notifications = _load_notifications()
        resolve = notifications.NotificationMixin._resolve_alias
        assert resolve("recipients", "a", channel=None) == "a"
        assert resolve("recipients", None, channel="b") == "b"
        assert resolve("recipients", None, channel=None) is None
        with pytest.raises(ValueError, match="aliases"):
            resolve("recipients", "a", channel="b")


# ===================================================================
# Payload presence (regression: optional `message` must not send "None")
# ===================================================================

class TestPayloadPresence:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_no_payload_and_no_report_returns_error_dict(self, name):
        owner = _owner()
        result = await getattr(owner, name)(recipients="target")
        assert result["status"] == "error"
        assert "no payload" in result["error"]
        owner.send_notification.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", sorted(WRAPPERS))
    async def test_report_only_send_is_allowed(self, name):
        owner = _owner()
        report = object()
        result = await getattr(owner, name)(recipients="target", report=report)
        assert result["status"] == "success"
        assert owner.send_notification.await_args.kwargs["report"] is report

    def test_none_message_extracts_as_empty_not_the_string_none(self):
        """Regression: str(None) used to become the literal message body."""
        notifications = _load_notifications()

        class _Owner(notifications.NotificationMixin):
            def __init__(self):
                self.logger = logging.getLogger("test.notifications.wrappers")

        text, files = _Owner()._extract_message_content(None)
        assert text == ""
        assert files == []

    def test_none_message_falls_back_to_report_output(self):
        notifications = _load_notifications()

        class _Report:
            output = "report body"

        class _Owner(notifications.NotificationMixin):
            def __init__(self):
                self.logger = logging.getLogger("test.notifications.wrappers")

        text, _ = _Owner()._extract_message_content(None, _Report())
        assert text == "report body"
