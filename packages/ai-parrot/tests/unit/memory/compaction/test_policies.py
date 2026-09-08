"""Unit tests for FEAT-525 prune policies."""

import re

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import Limit, ToolInvocation, ToolStatus
from parrot.memory.compaction.omission import content_id
from parrot.memory.compaction import policies as p

NOTICE = re.compile(r'<tool-output-omitted tool="(\w+)" chars="(\d+)" id="(om_[0-9a-f]{16})"( wm="[^"]+")?/>')


def test_policy_registry_and_default():
    assert isinstance(p.get_policy("query_database"), p.QueryPolicy)
    assert isinstance(p.get_policy("nope"), p.DefaultPolicy)
    custom = p.DefaultPolicy()
    p.register_policy("nope", custom)
    assert p.get_policy("nope") is custom


def test_policies_keep_errors_and_notice_shape():
    inv = ToolInvocation(
        tool_name="fetch_url",
        input={"url": "https://x"},
        output="body",
        status=ToolStatus.ERROR,
        error="HTTPError 503",
        elapsed_ms=3000,
        wm_key="__tee__:fetch_url:t:1",
    )
    for policy in (
        p.DefaultPolicy(),
        p.FileWritePolicy(),
        p.FileReadPolicy(),
        p.ShellPolicy(),
        p.SubAgentPolicy(),
        p.QueryPolicy(),
    ):
        out = policy.prune(inv, turn_id="t", limit=Limit())
        assert "error=HTTPError 503" in out.notice and out.notice.startswith("- fetch_url error 3.0s in=")
        m = NOTICE.search(out.notice)
        assert m and m.group(4) == ' wm="__tee__:fetch_url:t:1"'


def test_prune_turn_reuses_offloaded_id():
    inv = ToolInvocation(
        tool_name="q", input={}, output="preview …", omitted={"output": "om_0123456789abcdef"}, output_chars=48213
    )
    turn = ConversationTurn(turn_id="t1", user_id="u", user_message="q", assistant_response="a", tool_invocations=[inv])
    suffix, omissions = p.prune_turn(turn)
    assert omissions == () and 'id="om_0123456789abcdef" chars="48213"' in suffix.replace(
        'chars="48213" id="om_0123456789abcdef"', 'id="om_0123456789abcdef" chars="48213"'
    )
    assert suffix.startswith("\n\n<tool-activity>\n") and 'read_omitted_content(turn_id="t1")' in suffix


def test_prune_turn_fresh_output_and_empty():
    big = "x" * 5000
    turn = ConversationTurn(
        turn_id="t2",
        user_id="u",
        user_message="q",
        assistant_response="a",
        tool_invocations=[ToolInvocation(tool_name="q", input={"b": 1, "a": 2}, output=big)],
    )
    suffix, (om,) = p.prune_turn(turn)
    assert om.content_id == content_id(big) and om.content == big and om.turn_id == "t2" and om.field == "output"
    assert 'in={"a":2,"b":1}' in suffix and p.prune_turn(turn) == (suffix, (om,))
    assert p.prune_turn(ConversationTurn(turn_id="t3", user_id="u", user_message="q", assistant_response="a")) == (
        "",
        (),
    )
