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


_KEY_WHITESPACE_RE = re.compile(r"\s+")


def article_key(boe_id: str, article: str) -> str:
    """Build the composite key used as ``articulo.key_field``.

    Article designators can contain whitespace (e.g. ``"5 bis"``,
    ``"10 ter"``), which ArangoDB's ``_key`` grammar does not allow —
    only letters, digits, and ``_ - : . @ ( ) + , = ; $ ! * ' %``. Runs of
    whitespace in ``article`` are collapsed to a single underscore so the
    composite key is always a valid ``_key`` value once it is written as
    a vertex's ``_key`` (see ``OntologyGraphStore.upsert_nodes``).

    Args:
        boe_id: The canonical BOE identifier of the parent norm, e.g.
            ``"BOE-A-2015-10566"``.
        article: The article designator within the norm, e.g. ``"5"`` or
            ``"5 bis"``.

    Returns:
        The composite key in ``{norma}:{art}`` form, e.g.
        ``"BOE-A-2015-10566:5"`` or ``"BOE-A-2015-10566:5_bis"``.
    """
    safe_article = _KEY_WHITESPACE_RE.sub("_", article.strip())
    return f"{boe_id}:{safe_article}"
