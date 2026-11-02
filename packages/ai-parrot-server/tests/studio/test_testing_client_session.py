"""Conversations the client names on the Studio test chat: the id and the sid, with no database or runtime."""

import re

import pytest
from pydantic import ValidationError

from parrot.handlers.studio.testing._models import (
    CLIENT_SESSION_PATTERN,
    TestAskRequest,
    client_session_id,
    client_session_owner,
)

GOOD = ("conv-aaaa-1111", "a" * 8, "Z" * 64, "under_score-9", "0123456789abcdef0123456789abcdef")
BAD = ("short", "x" * 65, "has space in it", "semi;colon-id", "dot.ted-id", "colon:id-1", "trailing-nl\n", "")


@pytest.mark.parametrize("conversation", GOOD)
def test_a_valid_id_is_accepted_on_the_body_and_the_query(conversation):
    assert TestAskRequest(query="q", session_id=conversation).session_id == conversation
    assert re.fullmatch(CLIENT_SESSION_PATTERN, conversation)


@pytest.mark.parametrize("conversation", BAD)
def test_an_invalid_id_is_refused_on_the_body_and_the_query(conversation):
    with pytest.raises(ValidationError):
        TestAskRequest(query="q", session_id=conversation)
    assert not re.fullmatch(CLIENT_SESSION_PATTERN, conversation)


def test_without_an_id_the_request_is_unchanged():
    assert TestAskRequest(query="q").session_id is None


def test_the_sid_is_scoped_to_the_caller():
    assert client_session_id("u1", "conv-aaaa-1111") == "c.u1.conv-aaaa-1111"
    assert client_session_id("u1", "conv-aaaa-1111") != client_session_id("u2", "conv-aaaa-1111")


@pytest.mark.parametrize(
    "a, b",
    [
        (("1", "2-aaaaaaaa"), ("1-2", "aaaaaaaa")),  # "-" is in both parts: the old separator collided here
        (("1", "2_aaaaaaaa"), ("1_2", "aaaaaaaa")),
        (("a.b", "cccccccc"), ("a", "bbcccccccc")),  # a "." in the user id never reads as the separator
    ],
)
def test_no_two_callers_and_conversations_share_a_sid(a, b):
    assert client_session_id(*a) != client_session_id(*b)


@pytest.mark.parametrize("user_id", ["u1", "1-2", "a.b", "36522", "x:y"])
def test_the_owner_of_a_sid_is_its_caller_whatever_the_user_id_holds(user_id):
    assert client_session_owner(client_session_id(user_id, "conv-aaaa-1111")) == f"c.{user_id}"


def test_a_user_id_with_a_dot_is_not_the_owner_of_a_shorter_one():
    # the cap per caller groups sessions by owner: "c.1" must not take in the sessions of user "1.2"
    assert client_session_owner(client_session_id("1.2", "conv-aaaa-1111")) != "c.1"


@pytest.mark.parametrize("sid", ["deadbeefcafe", "studio_test:x", "c", "c.nodot", "x.u1.conv-aaaa-1111"])
def test_other_sids_have_no_owner(sid):
    assert client_session_owner(sid) is None
