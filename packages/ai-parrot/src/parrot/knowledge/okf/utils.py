"""Shared filesystem utilities for the OKF package.

Functions here are domain-agnostic helpers used by both PageIndex and
GraphIndex projection layers.  They live in ``okf`` (the neutral shared
package) rather than in either index's sub-package to avoid cross-domain
import dependencies.
"""

import hashlib

# Maximum length for a flattened concept-id filename stem (all hierarchy
# levels joined with "--").  Must stay safely under NodeContentStore's
# 64-char node-id limit.  Distinct from concept_id._MAX_SLUG_LENGTH (80),
# which caps individual slug segments before levels are combined.
_MAX_FLAT_ID_LENGTH = 60


def flatten_concept_id_for_filename(concept_id: str) -> str:
    """Convert a slash-containing concept_id to a flat filename stem.

    Slashes in ``concept_id`` are replaced with ``--`` (double-dash) for
    filesystem compatibility.  ``NodeContentStore._NODE_ID_RE`` only allows
    ``[A-Za-z0-9_-]{1,64}``; slashes are not in that set.

    If the resulting string exceeds ``_MAX_FLAT_ID_LENGTH`` characters, a
    deterministic SHA-1 hash suffix is appended to preserve uniqueness.

    Args:
        concept_id: OKF concept_id (may contain ``/`` path separators).

    Returns:
        Flat filename stem safe for both the local filesystem and
        ``NodeContentStore.save()``.

    Examples:
        >>> flatten_concept_id_for_filename("aws-ir")
        'aws-ir'
        >>> flatten_concept_id_for_filename("playbooks/aws-incident-response")
        'playbooks--aws-incident-response'
    """
    flat = concept_id.replace("/", "--")
    if len(flat) <= _MAX_FLAT_ID_LENGTH:
        return flat
    # Deterministically truncate + append short hash suffix for uniqueness.
    digest = hashlib.sha1(flat.encode()).hexdigest()[:8]
    return flat[: _MAX_FLAT_ID_LENGTH - 9] + "-" + digest


__all__ = ["flatten_concept_id_for_filename"]
