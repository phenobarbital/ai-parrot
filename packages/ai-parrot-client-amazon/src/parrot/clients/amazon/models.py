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
2. **Repair**: an unprefixed Bedrock-shaped ID that is not usable as written
   is resolved by lookup instead of passed through — the vendor namespace glued
   onto a public ID (``anthropic.claude-haiku-4-5``) and a bare base ID for a
   model with no in-region access (``anthropic.claude-opus-5``) both produce
   ``The provided model identifier is invalid`` from the Converse API. Never
   guesses a ``-vN:0`` suffix: an ID absent from the maps is passed through.
3. **Map**: public ID looked up in a static ``PUBLIC_TO_BEDROCK`` dict; the map
   values are the Bedrock base IDs (``anthropic.<id>-vN:0`` form — except
   Claude Opus 5 / Fable 5, which carry no version suffix).
4. **Region prefix (explicit)**: when *region_prefix* is provided (e.g.
   ``"us"``), the prefix ``"<prefix>."`` is prepended to the mapped base ID to
   form a cross-region inference-profile ID. Applied unconditionally for any
   mapped model — the caller is trusted to know whether the model supports
   the requested prefix (unchanged from pre-FEAT-405 behaviour).
5. **Region prefix (default)**: when *region_prefix* is NOT provided and the
   public ID is present in :data:`REQUIRES_REGION_PREFIX` (an ALLOWLIST — see
   FEAT-405 [R6]), that model's declared default prefix is applied
   automatically. Models absent from the allowlist are NEVER auto-prefixed —
   this is the inversion that keeps ``NovaClient``'s ``region_prefix="us"``
   default from leaking onto prefix-less vendor models (e.g. MiniMax M2.5).
6. **Unknown fallback**: IDs not in the map and not Bedrock-shaped are returned
   unchanged and a warning is logged — no exception is raised.
"""

from __future__ import annotations

import logging
from enum import Enum

logger = logging.getLogger(__name__)

# Known cross-region inference-profile prefixes.  IDs that already start with
# one of these are treated as already-translated (pass-through branch).
_REGION_PREFIXES: tuple[str, ...] = ("us.", "eu.", "apac.", "au.", "global.")

# Vendor namespaces served natively on Bedrock (2026 generation, FEAT-405).
# These models have NO geo/global inference profiles — ids are used verbatim,
# never prefixed. IDs containing one of these are treated as already
# Bedrock-shaped (pass-through branch), same as ``anthropic.``/``amazon.``.
_VENDOR_NAMESPACES: tuple[str, ...] = (
    "minimax.",
    "zai.",
    "moonshotai.",
    "qwen.",
)

# Vendor namespaces that DO publish geo inference profiles, so a bare
# ``<vendor>.<id>`` may still need a region prefix (unlike _VENDOR_NAMESPACES
# above). Recognised as Bedrock-shaped, then run through the repair step.
_PREFIXABLE_NAMESPACES: tuple[str, ...] = ("anthropic.", "amazon.", "meta.")

# Allowlist of public model IDs that support (or require) a cross-region
# inference-profile prefix, mapped to their DEFAULT prefix when the caller
# supplies none (FEAT-405 [R6]). Models absent from this map are NEVER
# auto-prefixed by default; an explicit region_prefix passed for a mapped
# model still applies unconditionally (see translate() step 3) — this map
# only governs (a) the default-when-omitted case and (b) whether an explicit
# prefix on an already-Bedrock-shaped/vendor id is honoured or warned away.
REQUIRES_REGION_PREFIX: dict[str, str] = {
    "claude-opus-5": "global",  # no regional inference profile — global only
    "claude-sonnet-5": "global",  # same tier as Opus 5
    "claude-fable-5": "global",  # geo IDs not published; global only
    "claude-fable-5-1": "global",  # same tier as Fable 5
    "claude-haiku-4-5": "us",  # geo access only via "us."
    # Meta Llama 4 Maverick has NO in-region access in any US region — the
    # "us." geo inference profile is the only way to call it.
    "llama4-maverick-17b-instruct": "us",
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
    "claude-opus-4-6": "anthropic.claude-opus-4-6-20260115-v1:0",
    # ── Claude 4.5 ─────────────────────────────────────────────────────────
    "claude-sonnet-4-5-20250929": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5": "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5-20251001": "anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5": "anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-5-20251101": "anthropic.claude-opus-4-5-20251101-v1:0",
    "claude-opus-4-5": "anthropic.claude-opus-4-5-20251101-v1:0",
    # ── Claude 4.1 ─────────────────────────────────────────────────────────
    "claude-opus-4-1-20250805": "anthropic.claude-opus-4-1-20250805-v1:0",
    "claude-opus-4-1": "anthropic.claude-opus-4-1-20250805-v1:0",
    # ── Claude Sonnet 4 ────────────────────────────────────────────────────
    "claude-sonnet-4-20250514": "anthropic.claude-sonnet-4-20250514-v1:0",
    # ── Claude 3.x ─────────────────────────────────────────────────────────
    "claude-3-7-sonnet-20250219": "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "claude-3-5-haiku-20241022": "anthropic.claude-3-5-haiku-20241022-v1:0",
    # ── Claude 5 (2026 generation, FEAT-405) ───────────────────────────────
    # NOTE: Claude 5 family models carry NO ``-vN:0`` suffix — breaks the
    # ``anthropic.<id>-vN:0`` convention used by every model above.
    "claude-opus-5": "anthropic.claude-opus-5",
    "claude-sonnet-5": "anthropic.claude-sonnet-5",
    "claude-fable-5": "anthropic.claude-fable-5",
    "claude-fable-5-1": "anthropic.claude-fable-5-1",
    # ── Not yet available on Bedrock (will warn+passthrough) ──────────────
    # claude-opus-4-8, claude-opus-4-7 — Bedrock IDs TBD.
    # ── Third-party models served on Bedrock ───────────────────────────────
    # Meta Llama 4 (Converse/Invoke only — NOT served on bedrock-mantle).
    "llama4-maverick-17b-instruct": "meta.llama4-maverick-17b-instruct-v1:0",
    # Qwen3 Coder — in-region only, no geo/global profile. This is the
    # bedrock-runtime id; the bedrock-mantle id is the suffix-less
    # "qwen.qwen3-coder-480b-a35b-instruct", which passes through untouched.
    "qwen3-coder-480b-a35b": "qwen.qwen3-coder-480b-a35b-v1:0",
    # Z.AI GLM 5 — same id on both endpoints, never prefixed.
    "glm-5": "zai.glm-5",
    # Moonshot AI Kimi K2.5 — same id on both endpoints, never prefixed.
    "kimi-k2.5": "moonshotai.kimi-k2.5",
    # ── Amazon Nova (multi-provider, FEAT-302) ─────────────────────────────
    "nova-sonic": "amazon.nova-sonic-v1:0",
    "nova-pro": "amazon.nova-pro-v1:0",
    "nova-lite": "amazon.nova-lite-v1:0",
    "nova-micro": "amazon.nova-micro-v1:0",
    # Nova Premier is geo-inference-only (needs a "us." region_prefix at call
    # time, e.g. via NovaClient); Legacy on Bedrock, EOL 2026-09-14 (FEAT-315).
    "nova-premier": "amazon.nova-premier-v1:0",
    # Nova Canvas/Reel are in-region only (no inference profiles) — the base
    # IDs below are the only valid ones; do NOT prefix them. Legacy on
    # Bedrock, EOL 2026-09-30 (FEAT-315, spec §6 Verified AWS Facts).
    "nova-canvas": "amazon.nova-canvas-v1:0",
    "nova-reel": "amazon.nova-reel-v1:0",
    # ── Amazon Nova 2 ─────────────────────────────────────────────────────
    "nova-2-sonic": "amazon.nova-2-sonic-v1:0",
    "nova-2-lite": "amazon.nova-2-lite-v1:0",
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
    for namespace in _PREFIXABLE_NAMESPACES:
        if namespace in model_id:
            return True
    for namespace in _VENDOR_NAMESPACES:
        if namespace in model_id:
            return True
    for prefix in _REGION_PREFIXES:
        if model_id.startswith(prefix):
            return True
    return False


def _public_ids_for(bedrock_id: str) -> list[str]:
    """Return the public IDs that map to *bedrock_id*.

    Aliases share a Bedrock ID (e.g. ``claude-haiku-4-5`` and
    ``claude-haiku-4-5-20251001``), so the allowlisted alias is returned
    first — it is the one that carries the default region prefix.

    Args:
        bedrock_id: A Bedrock base ID to reverse-look-up.

    Returns:
        Matching public IDs, allowlisted ones first (possibly empty).
    """
    matches = [k for k, v in PUBLIC_TO_BEDROCK.items() if v == bedrock_id]
    return sorted(matches, key=lambda k: k not in REQUIRES_REGION_PREFIX)


def _repair_unprefixed_id(model_id: str, region_prefix: str | None) -> str | None:
    """Resolve a Bedrock-shaped ID that is not actually usable as written.

    Two spellings look Bedrock-shaped but are rejected by the Converse API
    with ``The provided model identifier is invalid``:

    * ``anthropic.<public-id>`` — the vendor namespace glued onto a public ID,
      so the ``-vN:0`` suffix and region prefix are both missing (e.g.
      ``anthropic.claude-haiku-4-5``).
    * a bare base ID from :data:`PUBLIC_TO_BEDROCK` whose model is in
      :data:`REQUIRES_REGION_PREFIX` and therefore has no in-region access
      (e.g. ``anthropic.claude-opus-5``).

    Both are repaired by lookup only — never by string-munging a version
    suffix — so an ID this function cannot resolve from the maps is left
    alone for the caller's pass-through branch.

    Args:
        model_id: A Bedrock-shaped ID carrying no region prefix.
        region_prefix: Optional caller-supplied prefix, honoured only for
            models in :data:`REQUIRES_REGION_PREFIX` (same rule as
            :func:`translate` step 3).

    Returns:
        The repaired Bedrock ID, or ``None`` when there is nothing to repair.
    """
    # Vendor-namespaced models (minimax./zai./moonshotai.) have no inference
    # profiles and are never in the map — nothing to repair.
    if any(namespace in model_id for namespace in _VENDOR_NAMESPACES):
        return None

    # (a) vendor namespace glued onto a public ID -> re-run the map path.
    for namespace in _PREFIXABLE_NAMESPACES:
        if model_id.startswith(namespace):
            candidate = model_id[len(namespace) :]
            if candidate in PUBLIC_TO_BEDROCK:
                logger.debug(
                    "bedrock_models: %r is a public ID under the %r namespace "
                    "— resolving it through PUBLIC_TO_BEDROCK.",
                    model_id,
                    namespace,
                )
                return translate(candidate, region_prefix=region_prefix)

    # (b) exact base ID whose model has no in-region access.
    for public in _public_ids_for(model_id):
        default_prefix = REQUIRES_REGION_PREFIX.get(public)
        if default_prefix:
            return f"{region_prefix or default_prefix}.{model_id}"

    return None


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
        # An unprefixed Bedrock-shaped id may still be unusable: a public id
        # glued to the vendor namespace, or a base id for a model with no
        # in-region access. Repair those by lookup before passing through.
        if not already_resolved:
            repaired = _repair_unprefixed_id(public_id, region_prefix)
            if repaired is not None:
                return repaired
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


# ---------------------------------------------------------------------------
# AmazonModel (FEAT-523, TASK-2845)
# ---------------------------------------------------------------------------
# `grep -n '^class '` on this module (as `models/bedrock_models.py`, verified
# 2026-09-04) returned nothing — the file exposes constants/dicts, not a
# single catalogue Enum, because `translate()` accepts ANY public model ID
# string and passes unknown ones through unchanged (see module docstring
# step 6). This thin Enum is a documented, non-load-bearing convenience
# wrapper over the public IDs that ARE in `PUBLIC_TO_BEDROCK` today, so
# `BedrockConverseClient` / `NovaClient` / `BedrockMantleClient` have a
# `models` class attribute per the folder convention. It is NOT the
# authoritative catalogue (`PUBLIC_TO_BEDROCK` is, and `translate()` never
# consults this Enum); members are string-valued so `AmazonModel.X.value`
# round-trips to the exact public ID used as a `PUBLIC_TO_BEDROCK` key.


class AmazonModel(str, Enum):
    """Public model IDs known to :data:`PUBLIC_TO_BEDROCK` (documentation
    convenience only — see module note above; ``translate()`` accepts any
    string, not just these members)."""

    # Claude 4.6
    CLAUDE_SONNET_4_6 = "claude-sonnet-4-6"
    CLAUDE_OPUS_4_6 = "claude-opus-4-6"
    # Claude 4.5
    CLAUDE_SONNET_4_5_20250929 = "claude-sonnet-4-5-20250929"
    CLAUDE_SONNET_4_5 = "claude-sonnet-4-5"
    CLAUDE_HAIKU_4_5_20251001 = "claude-haiku-4-5-20251001"
    CLAUDE_HAIKU_4_5 = "claude-haiku-4-5"
    CLAUDE_OPUS_4_5_20251101 = "claude-opus-4-5-20251101"
    CLAUDE_OPUS_4_5 = "claude-opus-4-5"
    # Claude 4.1
    CLAUDE_OPUS_4_1_20250805 = "claude-opus-4-1-20250805"
    CLAUDE_OPUS_4_1 = "claude-opus-4-1"
    # Claude Sonnet 4
    CLAUDE_SONNET_4_20250514 = "claude-sonnet-4-20250514"
    # Claude 3.x
    CLAUDE_3_7_SONNET_20250219 = "claude-3-7-sonnet-20250219"
    CLAUDE_3_5_HAIKU_20241022 = "claude-3-5-haiku-20241022"
    # Claude 5 (2026 generation, FEAT-405)
    CLAUDE_OPUS_5 = "claude-opus-5"
    CLAUDE_SONNET_5 = "claude-sonnet-5"
    CLAUDE_FABLE_5 = "claude-fable-5"
    CLAUDE_FABLE_5_1 = "claude-fable-5-1"
    # Third-party models served on Bedrock
    LLAMA4_MAVERICK_17B_INSTRUCT = "llama4-maverick-17b-instruct"
    QWEN3_CODER_480B_A35B = "qwen3-coder-480b-a35b"
    GLM_5 = "glm-5"
    KIMI_K2_5 = "kimi-k2.5"
    # Amazon Nova (multi-provider, FEAT-302)
    NOVA_SONIC = "nova-sonic"
    NOVA_PRO = "nova-pro"
    NOVA_LITE = "nova-lite"
    NOVA_MICRO = "nova-micro"
    NOVA_PREMIER = "nova-premier"
    NOVA_CANVAS = "nova-canvas"
    NOVA_REEL = "nova-reel"
    # Amazon Nova 2
    NOVA_2_SONIC = "nova-2-sonic"
    NOVA_2_LITE = "nova-2-lite"


__all__ = [
    "translate",
    "PUBLIC_TO_BEDROCK",
    "REQUIRES_REGION_PREFIX",
    "AmazonModel",
]
