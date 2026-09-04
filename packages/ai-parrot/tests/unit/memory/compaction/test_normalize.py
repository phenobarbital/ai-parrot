"""Unit + property tests for FEAT-525 Stage 0 normalization."""

import copy

from hypothesis import given, settings, strategies as st

from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import ToolInvocation
from parrot.memory.compaction.normalize import (
    NORM_VERSION,
    canonical_json_text,
    condense_traceback,
    normalize_text,
    normalize_turn,
)


def test_rule_nfc_and_ansi_and_whitespace():
    raw = "é\x1b[31mred\x1b[0m  \r\nline\n\n\n\n\nend  "
    assert normalize_text(raw) == "éred\nline\n\n\nend"


def test_rule_canonical_json():
    assert canonical_json_text('{"b": 1, "a": [2, 1]}') == '{"a":[2,1],"b":1}'
    assert canonical_json_text("42") == "42"
    assert canonical_json_text("not json") == "not json"


def test_rule_traceback_condensed_keeps_exception_line():
    tb = "Traceback (most recent call last):\n" + "".join(
        f'  File "f{i}.py", line {i}, in fn\n    call()\n' for i in range(10)
    ) + "ValueError: bad\n"
    out = condense_traceback(tb, keep_frames=3)
    assert out.count('File "') == 3 and out.rstrip().endswith("ValueError: bad")


text_st = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200)


@st.composite
def turns(draw):
    inv = ToolInvocation(
        tool_name=draw(st.text(min_size=1, max_size=10)),
        # Bounded to orjson's supported signed-64-bit range: real tool-call
        # arguments are JSON-schema-validated and never carry arbitrary
        # precision integers.
        input={draw(st.text(max_size=5)): draw(st.integers(min_value=-(2**63), max_value=2**63 - 1))},
        output=draw(st.one_of(st.none(), text_st)),
        error=draw(st.one_of(st.none(), text_st)),
    )
    return ConversationTurn(
        turn_id="t",
        user_id="u",
        user_message=draw(text_st),
        assistant_response=draw(text_st),
        tool_invocations=[inv],
    )


@settings(max_examples=200)
@given(turns())
def test_normalize_idempotent_and_pure(turn):
    before = copy.deepcopy(turn)
    once = normalize_turn(turn)
    assert turn == before
    assert normalize_turn(once) == once
    assert once.norm_version == NORM_VERSION
