"""Bedrock model-ID translator for AI-Parrot.

Translates public Anthropic/Amazon model IDs (e.g. ``claude-sonnet-4-6``,
``nova-2-sonic``) to the AWS Bedrock ID format (e.g.
``us.anthropic.claude-sonnet-4-5-20250929-v1:0``, ``amazon.nova-2-sonic-v1:0``).

Translation strategy (applied in order):
1. **Pass-through**: IDs that are already Bedrock-shaped (contain ``anthropic.``
   or ``amazon.``, start with ``arn:``, begin with a known region prefix like
   ``us.`` / ``eu.`` / ``apac.`` / ``au.`` / ``global.``, or begin with a
   vendor namespace served natively on Bedrock — ``minimax.`` / ``zai.`` /
   ``moonshotai.`` — FEAT-405) are returned verbatim. If the caller also
   passed an explicit *region_prefix* for one of these, and the id is not in
   :data:`REQUIRES_REGION_PREFIX`, the prefix is ignored and a warning is
   logged (never silently discarded).
2. **Map**: public ID looked up in a static ``PUBLIC_TO_BEDROCK`` dict; the map
   values are the Bedrock base IDs (``anthropic.<id>-vN:0`` form — except
   Claude Opus 5 / Fable 5, which carry no version suffix).
3. **Region prefix (explicit)**: when *region_prefix* is provided (e.g.
   ``"us"``), the prefix ``"<prefix>."`` is prepended to the mapped base ID to
   form a cross-region inference-profile ID. Applied unconditionally for any
   mapped model — the caller is trusted to know whether the model supports
   the requested prefix (unchanged from pre-FEAT-405 behaviour).
4. **Region prefix (default)**: when *region_prefix* is NOT provided and the
   public ID is present in :data:`REQUIRES_REGION_PREFIX` (an ALLOWLIST — see
   FEAT-405 [R6]), that model's declared default prefix is applied
   automatically. Models absent from the allowlist are NEVER auto-prefixed —
   this is the inversion that keeps ``NovaClient``'s ``region_prefix="us"``
   default from leaking onto prefix-less vendor models (e.g. MiniMax M2.5).
5. **Unknown fallback**: IDs not in the map and not Bedrock-shaped are returned
   unchanged and a warning is logged — no exception is raised.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Known cross-region inference-profile prefixes.  IDs that already start with
# one of these are treated as already-translated (pass-through branch).
_REGION_PREFIXES: tuple[str, ...] = ("us.", "eu.", "apac.", "au.", "global.")

# Vendor namespaces served natively on Bedrock (2026 generation, FEAT-405).
# These models have NO geo/global inference profiles — ids are used verbatim,
# never prefixed. IDs containing one of these are treated as already
# Bedrock-shaped (pass-through branch), same as ``anthropic.``/``amazon.``.
_VENDOR_NAMESPACES: tuple[str, ...] = ("minimax.", "zai.", "moonshotai.")

# Allowlist of public model IDs that support (or require) a cross-region
# inference-profile prefix, mapped to their DEFAULT prefix when the caller
# supplies none (FEAT-405 [R6]). Models absent from this map are NEVER
# auto-prefixed by default; an explicit region_prefix passed for a mapped
# model still applies unconditionally (see translate() step 3) — this map
# only governs (a) the default-when-omitted case and (b) whether an explicit
# prefix on an already-Bedrock-shaped/vendor id is honoured or warned away.
REQUIRES_REGION_PREFIX: dict[str, str] = {
    "claude-opus-5": "us",       # no in-region access in us-west-2/us-east-2
    "claude-fable-5": "global",  # geo IDs not published; global only
    "claude-haiku-4-5": "us",    # geo access only via "us."
}

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

    # ── Claude 5 (2026 generation, FEAT-405) ───────────────────────────────
    # NOTE: Opus 5 / Fable 5 carry NO ``-vN:0`` suffix — breaks the
    # ``anthropic.<id>-vN:0`` convention used by every model above.
    "claude-opus-5":  "anthropic.claude-opus-5",
    "claude-fable-5": "anthropic.claude-fable-5",

    # ── Not yet available on Bedrock (will warn+passthrough) ──────────────
    # claude-opus-4-8, claude-opus-4-7 — Bedrock IDs TBD.

    # ── Amazon Nova (multi-provider, FEAT-302) ─────────────────────────────
    "nova-sonic":   "amazon.nova-sonic-v1:0",
    "nova-pro":     "amazon.nova-pro-v1:0",
    "nova-lite":    "amazon.nova-lite-v1:0",
    "nova-micro":   "amazon.nova-micro-v1:0",
    # Nova Premier is geo-inference-only (needs a "us." region_prefix at call
    # time, e.g. via NovaClient); Legacy on Bedrock, EOL 2026-09-14 (FEAT-315).
    "nova-premier": "amazon.nova-premier-v1:0",
    # Nova Canvas/Reel are in-region only (no inference profiles) — the base
    # IDs below are the only valid ones; do NOT prefix them. Legacy on
    # Bedrock, EOL 2026-09-30 (FEAT-315, spec §6 Verified AWS Facts).
    "nova-canvas":  "amazon.nova-canvas-v1:0",
    "nova-reel":    "amazon.nova-reel-v1:0",

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
    for namespace in _VENDOR_NAMESPACES:
        if namespace in model_id:
            return True
    for prefix in _REGION_PREFIXES:
        if model_id.startswith(prefix):
            return True
    return False


def translate(public_id: str, region_prefix: str | None = None) -> str:
    """Translate a public Anthropic model ID to its AWS Bedrock equivalent.

    Args:
        public_id: A public model ID (e.g. ``"claude-sonnet-4-6"``) or an
            already-translated Bedrock ID / ARN / vendor-namespaced id (e.g.
            ``"minimax.minimax-m2.5"``) — in which case it is returned
            verbatim.
        region_prefix: Optional cross-region inference-profile prefix, e.g.
            ``"us"``, ``"eu"``, ``"apac"``, ``"au"``, or ``"global"``. When
            provided, the translated base ID is prefixed with
            ``"<region_prefix>."``. For an already Bedrock-shaped/vendor id
            NOT present in :data:`REQUIRES_REGION_PREFIX`, the prefix is
            ignored and a warning is logged instead of being applied. When
            omitted, a default prefix is applied automatically ONLY for
            models present in :data:`REQUIRES_REGION_PREFIX` — models absent
            from that allowlist are NEVER prefixed (FEAT-405 [R6]).

    Returns:
        The corresponding Bedrock model ID string.

    Examples:
        >>> translate("claude-sonnet-4-6")
        'anthropic.claude-sonnet-4-6-20260115-v1:0'

        >>> translate("claude-sonnet-4-6", region_prefix="us")
        'us.anthropic.claude-sonnet-4-6-20260115-v1:0'

        >>> translate("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        'us.anthropic.claude-sonnet-4-5-20250929-v1:0'

        >>> translate("minimax.minimax-m2.5", region_prefix="us")
        'minimax.minimax-m2.5'
    """
    # 1. Pass-through: already a Bedrock ID, ARN, or native vendor namespace.
    if _is_bedrock_id(public_id):
        # An id that already carries a region/global prefix (or is a full
        # ARN) is already fully resolved — a redundant region_prefix arg
        # is harmless, not a mistake, so it must NOT warn (code-review fix:
        # this branch previously warned even for a model's own verified
        # default id, e.g. NovaAdversarialReviewProfile's
        # "us.amazon.nova-2-lite-v1:0", spamming a false-positive on every
        # call). Only warn for a genuinely never-prefix id (vendor
        # namespaces, or a bare "anthropic."/"amazon." id with no prefix
        # applied) that isn't in the allowlist.
        already_resolved = public_id.startswith("arn:") or any(
            public_id.startswith(prefix) for prefix in _REGION_PREFIXES
        )
        if region_prefix and not already_resolved and public_id not in REQUIRES_REGION_PREFIX:
            logger.warning(
                "bedrock_models.translate: region_prefix=%r requested for "
                "%r, which is not in REQUIRES_REGION_PREFIX — the model is "
                "already Bedrock-shaped or has no inference profile. "
                "Ignoring the prefix.",
                region_prefix,
                public_id,
            )
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

    # 3. Region prefix — explicit. Applied unconditionally for any mapped
    # model; the caller is trusted here (unchanged from pre-FEAT-405
    # behaviour — translate() has no per-model in-region-only knowledge).
    if region_prefix:
        return f"{region_prefix}.{bedrock_id}"

    # 4. Region prefix — default, ALLOWLIST-gated (FEAT-405 [R6]). Only
    # models declared in REQUIRES_REGION_PREFIX get an automatic prefix when
    # the caller omits one; everything else returns the bare base ID.
    default_prefix = REQUIRES_REGION_PREFIX.get(public_id)
    if default_prefix:
        return f"{default_prefix}.{bedrock_id}"

    return bedrock_id
