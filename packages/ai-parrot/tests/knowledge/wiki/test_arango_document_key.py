"""Key-encoding contract for the ArangoDB wiki store.

Regression cover for the ``~`` leak: :func:`urllib.parse.quote` treats ``~``
as unreserved (RFC 3986), so it sits in urllib's own always-safe set and no
``safe`` argument can take it out. ArangoDB rejects it in a ``_key`` with
``[ERR 1221] illegal document key``, and :func:`sym_concept_id` puts one in
every repeated-qualname symbol id — so a repo with two same-named qualnames
in one file aborted its whole ingest.
"""

import string

from urllib.parse import unquote

import pytest

from parrot.knowledge.wiki.arango_store import (
    _KEY_MAX_BYTES,
    document_key,
    edge_key,
)
from parrot.knowledge.wiki.symbols import sym_concept_id


#: Every character ArangoDB accepts in a ``_key``. Percent is legal, which is
#: what makes percent-encoding a valid encoding here in the first place.
LEGAL_KEY_CHARS = frozenset(string.ascii_letters + string.digits + "_-:.@()+,=;$!*'%")


def illegal_chars(key: str) -> set[str]:
    """Return the characters in ``key`` ArangoDB would reject."""
    return set(key) - LEGAL_KEY_CHARS


def test_repeated_qualname_symbol_id_has_no_tilde():
    """The regression: ordinal-suffixed symbol ids must not leak ``~``."""
    concept_id = sym_concept_id("app.py", "Foo.handle", 2)
    assert "~" in concept_id, "sym_concept_id no longer uses ~; update this test"

    key = document_key(concept_id)

    assert "~" not in key
    assert not illegal_chars(key)


@pytest.mark.parametrize(
    "identity",
    [
        "file:src/main.py",
        "dir:packages/ai-parrot",
        "sym:app.py#Foo.handle",
        "sym:app.py#Foo.handle~2",
        "sym:x.py#f~10",
        "file:a~b/c%d.py",
        "file:ñandú/áéíóú.py",
        "file:with space/and+plus.py",
    ],
)
def test_key_uses_only_legal_characters(identity):
    """No identity shape may produce a character ArangoDB rejects."""
    assert not illegal_chars(document_key(identity))


@pytest.mark.parametrize(
    "identity",
    [
        "file:src/main.py",
        "sym:app.py#Foo.handle~2",
        "file:a~b/c%d.py",
        "file:ñandú/áéíóú.py",
    ],
)
def test_short_keys_round_trip(identity):
    """Encoding is reversible while the key fits the byte budget."""
    key = document_key(identity)
    assert len(key.encode("utf-8")) <= _KEY_MAX_BYTES
    assert unquote(key) == identity


def test_long_identity_is_truncated_within_the_byte_budget():
    """A path too long to encode keeps a digest and stays under the limit."""
    identity = "file:" + "muy/largo/" * 40 + "z.py"

    key = document_key(identity)

    assert len(key.encode("utf-8")) <= _KEY_MAX_BYTES
    assert not illegal_chars(key)
    assert "$" in key, "truncated keys carry a $<digest> suffix"


def test_long_identities_stay_unique_after_truncation():
    """Two paths sharing a long prefix must not collide."""
    prefix = "file:" + "muy/largo/" * 40
    assert document_key(prefix + "a.py") != document_key(prefix + "b.py")


def test_edge_key_inherits_the_same_contract():
    """Edge keys concatenate two identities and must stay legal too."""
    key = edge_key("file:a~b.py", "sym:c.py#d~2", "references")

    assert "~" not in key
    assert not illegal_chars(key)
    assert len(key.encode("utf-8")) <= _KEY_MAX_BYTES
