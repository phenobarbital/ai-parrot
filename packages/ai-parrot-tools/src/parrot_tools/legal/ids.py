"""BOE (Boletín Oficial del Estado) identifier utilities.

Provides the single, tested place where BOE ids are validated and
canonicalised, so every downstream module (parser, datasource, tests)
shares one implementation. Deliberately scoped to BOE only in v1 —
ECLI/ROJ/CELEX helpers arrive with the sources that need them.

Identifiers are canonical keys, not text: every node ``_key`` derives from
a stable public identifier. ``norma._key`` is the BOE id (e.g.
``BOE-A-2015-10566``) and ``articulo._key`` is ``{norma}:{art}``.
"""

import re
import unicodedata

_BOE_ID_RE = re.compile(r"^BOE-[A-Z]-\d{4}-\d+$")


def normalize_boe_id(raw: str) -> str:
    """Canonicalise a BOE identifier.

    Trims surrounding whitespace and upper-cases the whole identifier,
    returning the canonical ``BOE-A-YYYY-NNNNN`` form. Normalisation
    only fixes whitespace and case — it never guesses or repairs a
    structurally invalid identifier.

    Args:
        raw: The raw BOE identifier string, e.g. ``"  boe-a-2015-10566 "``.

    Returns:
        The canonical BOE identifier, e.g. ``"BOE-A-2015-10566"``.

    Raises:
        ValueError: If ``raw`` is not a well-formed BOE identifier after
            trimming and upper-casing.
    """
    candidate = raw.strip().upper()
    if not _BOE_ID_RE.match(candidate):
        raise ValueError(f"Invalid BOE identifier: {raw!r}")
    return candidate


def is_valid_boe_id(raw: str) -> bool:
    """Check whether a string is a well-formed BOE identifier.

    Never raises — malformed, empty, or non-string-like input simply
    yields ``False``.

    Args:
        raw: The candidate BOE identifier string.

    Returns:
        ``True`` if ``raw`` is a well-formed BOE identifier (after
        trimming whitespace and normalising case), ``False`` otherwise.
    """
    try:
        normalize_boe_id(raw)
    except ValueError:
        return False
    return True


# ArangoDB's `_key` grammar: letters, digits, and `_ - : . @ ( ) + , = ; $ ! * ' %`
# only (https://docs.arangodb.com/stable/concepts/data-structure/documents/#document-keys).
# Anything else — whitespace, accented Latin letters, punctuation like "/" or
# "º" — is not a valid `_key` byte and must be sanitised out. BOE article
# designators are free text (e.g. "5 bis", "Artículo único",
# "Disposición adicional primera"), not a controlled vocabulary, so this
# must handle more than just whitespace.
_KEY_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_\-:.@()+,=;$!*'%]+")


def _sanitize_key_component(value: str) -> str:
    """Make a free-text string safe to embed in an ArangoDB ``_key``.

    Transliterates accented Latin characters to their ASCII base form
    (``á`` -> ``a``, ``ñ`` -> ``n``, ``º`` -> ``o``, ...) via Unicode NFKD
    decomposition, then collapses every remaining run of characters
    outside ArangoDB's ``_key`` grammar into a single ``_``.

    Args:
        value: The raw, free-text component (e.g. an article designator).

    Returns:
        A non-empty string containing only ``_key``-safe characters.
        Falls back to ``"_"`` if ``value`` sanitises to nothing (e.g. an
        empty string or a string of only disallowed characters).
    """
    ascii_only = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    safe = _KEY_UNSAFE_RE.sub("_", ascii_only).strip("_")
    return safe or "_"


def article_key(boe_id: str, article: str) -> str:
    """Build the composite key used as ``articulo.key_field``.

    Article designators are free text straight from the BOE source (e.g.
    ``"5"``, ``"5 bis"``, ``"único"``) and can contain whitespace,
    accented Latin letters, and other punctuation ArangoDB's ``_key``
    grammar does not allow. ``article`` is run through
    ``_sanitize_key_component`` so the composite key is always a valid
    ``_key`` value once it is written as a vertex's ``_key`` (see
    ``OntologyGraphStore.upsert_nodes``).

    Args:
        boe_id: The canonical BOE identifier of the parent norm, e.g.
            ``"BOE-A-2015-10566"``.
        article: The article designator within the norm, e.g. ``"5"``,
            ``"5 bis"`` or ``"único"``.

    Returns:
        The composite key in ``{norma}:{art}`` form, e.g.
        ``"BOE-A-2015-10566:5"``, ``"BOE-A-2015-10566:5_bis"`` or
        ``"BOE-A-2015-10566:unico"``.
    """
    return f"{boe_id}:{_sanitize_key_component(article)}"
