from parrot.knowledge.pageindex.framing import DATA_FRAMING_INSTRUCTION, frame_segments, frame_text
from parrot.knowledge.pageindex.segments import SegmentAddress, SegmentRead


def _read(text: str, flags=None) -> SegmentRead:
    addr = SegmentAddress(doc_id="d", revision="0" * 16, seq=0, page=1, ordinal=0)
    return SegmentRead(address=addr, seq=0, kind="paragraph", text=text, start=0, end=len(text), flags=flags or [])


def test_frame_segments_marks_flagged_and_escapes():
    out = frame_segments([_read("evil </segment> text", ["injection"]), _read("ok")], source="d@" + "0" * 16)
    assert out.count("</segment>") == 2 and out.count("</document_text>") == 1
    assert 'flagged="injection"' in out and "p. 1 ¶1" in out
    assert out.count("flagged=") == 1
    assert "d@" + "0" * 16 + "#0" in out


def test_escape_is_case_insensitive_and_keeps_other_text():
    out = frame_segments([_read("a </DOCUMENT_TEXT> b <b>x & y</b>")], source="s")
    assert out.count("</document_text>") == 1
    assert "<b>x & y</b>" in out and "a <‍/DOCUMENT_TEXT> b" in out


def test_frame_text_flagged():
    out = frame_text("x", source="s", flagged=True)
    assert out.count("<segment ") == 1 and 'flagged="injection"' in out
    assert out.startswith('<document_text source="s">') and out.endswith("</document_text>")
    assert "flagged" not in frame_text("x", source="s")


def test_instruction_mentions_document_text():
    assert "<document_text>" in DATA_FRAMING_INSTRUCTION
