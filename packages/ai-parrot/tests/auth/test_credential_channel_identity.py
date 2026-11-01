"""FEAT-775 M1: explicit channel identity on PermissionContext."""

from parrot.auth.credentials import credential_channel_user_id
from parrot.auth.permission import PermissionContext, UserSession


def _ctx(
    channel: str | None,
    user_id: str = "42",
    channel_user_id: str | None = None,
) -> PermissionContext:
    return PermissionContext(
        session=UserSession(user_id=user_id, tenant_id="t-1", roles=frozenset()),
        channel=channel,
        channel_user_id=channel_user_id,
    )


def test_teams_uses_explicit_channel_identity() -> None:
    assert credential_channel_user_id(_ctx("msteams", channel_user_id="aad-1")) == "aad-1"


def test_teams_missing_identity_fails_closed() -> None:
    assert credential_channel_user_id(_ctx("msteams")) is None
    assert credential_channel_user_id(_ctx("msteams", channel_user_id="")) is None
    assert credential_channel_user_id(_ctx("msteams", channel_user_id="   ")) is None


def test_other_channels_keep_user_id() -> None:
    for channel in ("telegram", "web", None):
        assert credential_channel_user_id(_ctx(channel, channel_user_id="ignored")) == "42"


def test_field_defaults_to_none_and_is_positional_safe() -> None:
    session = UserSession(user_id="42", tenant_id="t-1", roles=frozenset())

    context = PermissionContext(session, "req", "web")

    assert context.channel_user_id is None
    assert context.request_id == "req"
    assert context.channel == "web"
