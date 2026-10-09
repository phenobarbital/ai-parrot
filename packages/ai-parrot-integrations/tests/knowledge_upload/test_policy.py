"""Unit tests for knowledge upload authorization."""
from unittest.mock import AsyncMock

from parrot.auth.userinfo import EmployeeProfile
from parrot.integrations.knowledge_upload import UploaderIdentity
from parrot.integrations.knowledge_upload.policy import UploadPolicy, resolve_profile


def _profile(username: str = "someone", groups: tuple[str, ...] = ()) -> EmployeeProfile:
    return EmployeeProfile(user_id=1, username=username, groups=list(groups))


class TestUploadPolicy:
    """Tests for username and group authorization."""

    def test_allowed_by_username_case_insensitive(self) -> None:
        assert UploadPolicy(["JLara"], []).is_allowed(_profile("jlara"))

    def test_allowed_by_group_case_insensitive(self) -> None:
        assert UploadPolicy([], ["curators"]).is_allowed(_profile(groups=("Curators",)))

    def test_deny_by_default(self) -> None:
        assert not UploadPolicy([], []).is_allowed(_profile("jlara", ("curators",)))

    def test_none_profile_denied(self) -> None:
        assert not UploadPolicy(["jlara"], ["curators"]).is_allowed(None)


async def test_resolve_profile_falls_back_to_email_after_missing_nav_user() -> None:
    """A missing navigator-id profile falls back to the verified email identity."""
    userinfo = AsyncMock()
    userinfo.get_profile.return_value = None
    userinfo.get_profile_by_email.return_value = _profile("jlara")
    identity = UploaderIdentity(platform="telegram", platform_user_id="9", nav_user_id="42", email="j@x.com")

    assert (await resolve_profile(identity, userinfo)).username == "jlara"
    userinfo.get_profile.assert_awaited_once_with("42")
    userinfo.get_profile_by_email.assert_awaited_once_with("j@x.com")


async def test_resolve_profile_lookup_error_is_none() -> None:
    """Database errors deny the upload instead of escaping into the chat handler."""
    userinfo = AsyncMock()
    userinfo.get_profile_by_email.side_effect = RuntimeError("db down")
    identity = UploaderIdentity(platform="slack", platform_user_id="U1", email="j@x.com")

    assert await resolve_profile(identity, userinfo) is None
