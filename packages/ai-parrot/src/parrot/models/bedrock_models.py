"""Bedrock model-ID translator for AI-Parrot.

Translates public Anthropic/Amazon model IDs (e.g. ``claude-sonnet-4-6``,
``nova-2-sonic``) to the AWS Bedrock ID format (e.g.
``us.anthropic.claude-sonnet-4-5-20250929-v1:0``, ``amazon.nova-2-sonic-v1:0``).

Translation strategy (applied in order):
1. **Pass-through**: IDs that are already Bedrock-shaped (contain ``anthropic.``
   or ``amazon.``, start with ``arn:``, or begin with a known region prefix
   like ``us.`` / ``eu.`` / ``apac.``) are returned verbatim.
2. **Map**: public ID looked up in a static ``PUBLIC_TO_BEDROCK`` dict; the map
   values are the Bedrock base IDs (``anthropic.<id>-vN:0`` form).
3. **Region prefix**: when *region_prefix* is provided (e.g. ``"us"``), the
   prefix ``"<prefix>."`` is prepended to the mapped base ID to form a
   cross-region inference-profile ID.
4. **Unknown fallback**: IDs not in the map and not Bedrock-shaped are returned
   unchanged and a warning is logged — no exception is raised.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Known cross-region inference-profile prefixes.  IDs that already start with
# one of these are treated as already-translated (pass-through branch).
_REGION_PREFIXES: tuple[str, ...] = ("us.", "eu.", "apac.")

# Static map: public model ID → Bedrock base ID.
# Values follow the ``anthropic.<public-id>-vN:0`` convention; the exact suffix
# (``-v1:0``, ``-v2:0`` …) is per-model and hard-coded here so that the
# translator never needs to string-munge or guess it.
#
# Dated variants (with date suffix in the public ID, e.g. claude-sonnet-4-5-20250929)
# are also mapped directly.  Aliases (e.g. claude-sonnet-4-6 without a date) map to
# the most recent pinned Bedrock ID for that alias family; update this map when AWS
# publishes new inference-profile IDs.
PUBLIC_TO_BEDROCK: dict[str, str] = {
    # ── Claude 4.6 ─────────────────────────────────────────────────────────
    # NOTE: date suffix 20260115 is speculative for future models; update
    # when AWS Bedrock publishes the actual model version identifiers.
    "claude-sonnet-4-6": "anthropic.claude-sonnet-4-6-20260115-v1:0",
    "claude-opus-4-6":   "anthropic.claude-opus-4-6-20260115-v1:0",

    # ── Claude 4.5 ─────────────────────────────────────────────────────────
    "claude-sonnet-4-5-20250929": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5":          "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5-20251001":  "anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5":           "anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-5-20251101":   "anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-5":            "anthropic.claude-opus-4-5-20251101-v1:0",

    # ── Claude 4.1 ─────────────────────────────────────────────────────────
    "claude-opus-4-1-20250805":   "anthropic.claude-opus-4-1-20250805-v1:0",
    "claude-opus-4-1":            "anthropic.claude-opus-4-1-20250805-v1:0",

    # ── Claude Sonnet 4 ────────────────────────────────────────────────────
    "claude-sonnet-4-20250514":   "anthropic.claude-sonnet-4-20250514-v1:0",

    # ── Claude 3.x ─────────────────────────────────────────────────────────
    "claude-3-7-sonnet-20250219": "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "claude-3-5-haiku-20241022":  "anthropic.claude-3-5-haiku-20241022-v1:0",

    # ── Not yet available on Bedrock (will warn+passthrough) ──────────────
    # claude-fable-5, claude-opus-4-8, claude-opus-4-7 — Bedrock IDs TBD.

    # ── Amazon Nova (multi-provider, FEAT-302) ─────────────────────────────
    "nova-sonic":   "amazon.nova-sonic-v1:0",
    "nova-pro":     "amazon.nova-pro-v1:0",
    "nova-lite":    "amazon.nova-lite-v1:0",
    "nova-micro":   "amazon.nova-micro-v1:0",

    # ── Amazon Nova 2 ─────────────────────────────────────────────────────
    "nova-2-sonic": "amazon.nova-2-sonic-v1:0",
    "nova-2-lite":  "amazon.nova-2-lite-v1:0",
}


def _is_bedrock_id(model_id: str) -> bool:
    """Return True when *model_id* already looks like a Bedrock / ARN ID.

    Args:
        model_id: The model identifier string to test.

    Returns:
        ``True`` if the ID should be passed through verbatim.
    """
    if model_id.startswith("arn:"):
        return True
    if "anthropic." in model_id:
        return True
    if "amazon." in model_id:
        return True
    for prefix in _REGION_PREFIXES:
        if model_id.startswith(prefix):
            return True
    return False


def translate(public_id: str, region_prefix: str | None = None) -> str:
    """Translate a public Anthropic model ID to its AWS Bedrock equivalent.

    Args:
        public_id: A public model ID (e.g. ``"claude-sonnet-4-6"``) or an
            already-translated Bedrock ID / ARN — in which case it is
            returned verbatim.
        region_prefix: Optional cross-region inference-profile prefix, e.g.
            ``"us"``, ``"eu"``, or ``"apac"``.  When provided, the translated
            base ID is prefixed with ``"<region_prefix>."``.  Ignored when
            *public_id* is already Bedrock-shaped (pass-through branch).

    Returns:
        The corresponding Bedrock model ID string.

    Examples:
        >>> translate("claude-sonnet-4-6")
        'anthropic.claude-sonnet-4-6-20260115-v1:0'

        >>> translate("claude-sonnet-4-6", region_prefix="us")
        'us.anthropic.claude-sonnet-4-6-20260115-v1:0'

        >>> translate("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        'us.anthropic.claude-sonnet-4-5-20250929-v1:0'
    """
    # 1. Pass-through: already a Bedrock ID or ARN.
    if _is_bedrock_id(public_id):
        return public_id

    # 2. Map lookup.
    bedrock_id = PUBLIC_TO_BEDROCK.get(public_id)
    if bedrock_id is None:
        logger.warning(
            "bedrock_models.translate: unknown public model ID %r — "
            "returning unchanged. Add it to PUBLIC_TO_BEDROCK to suppress "
            "this warning.",
            public_id,
        )
        return public_id

    # 3. Region prefix.
    if region_prefix:
        return f"{region_prefix}.{bedrock_id}"

    return bedrock_id
