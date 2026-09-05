"""Configuration constants for the Fireflies → Obsidian LLM-Wiki
Knowledge-Base agent (FEAT-481, spec Module 1).

**Self-contained.** This subsystem's config lives here, NOT in
``parrot/agents/conf.py`` — additive-only (spec G11): no existing config
file is touched. The one exception is :data:`FIREFLIES_SYNC_OVERLAP_DAYS`,
which is *reused* (imported, never redefined) from FEAT-472's
``parrot.agents.conf`` so the fetch-gate watermark stays consistent with
the rest of the Fireflies family.

Every value is resolved once, at import time, via ``navconfig.config``'s
typed accessors (``get``/``getint``/``getboolean``) — same pattern as
``parrot/agents/conf.py`` — so ``@schedule``'s decoration-time evaluation
sees plain module-level constants and the deployment surface stays
greppable (``rtk grep WIKI_KB_``).
"""

from __future__ import annotations

from navconfig import config

# Reused, not redefined (spec Module 1 / G11) — FEAT-472's overlap-days
# knob for MeetingRegistry.suggest_from_date().
from parrot.agents.conf import FIREFLIES_SYNC_OVERLAP_DAYS

__all__ = (
    "FIREFLIES_SYNC_OVERLAP_DAYS",
    "FIREFLIES_WIKI_EMAIL_ENABLED",
    "WIKI_KB_ACTIVE_WINDOW_DAYS",
    "WIKI_KB_INGEST_CRON",
    "WIKI_KB_INGEST_LIMIT",
    "WIKI_KB_INGEST_PROFILE",
    "WIKI_KB_LLM_CHEAP",
    "WIKI_KB_LLM_STRONG",
    "WIKI_KB_MAX_CATCHUP_DAYS",
    "WIKI_KB_MAX_NEW_PER_RUN",
    "WIKI_KB_MAX_REPROCESS_ATTEMPTS",
    "WIKI_KB_PARTICIPANTS",
    "WIKI_KB_RAW_ROOT",
    "WIKI_KB_VAULT_PATH",
)


def _participants(key: str) -> list[str]:
    """Read a comma-separated participant-email allowlist, stripped.

    Mirrors ``parrot.agents.conf._recipients`` — ``config.getlist`` splits
    on ``","`` but does not strip whitespace around each entry.

    Args:
        key: navconfig / environment variable name.

    Returns:
        Stripped, non-empty entries (empty list when the key is unset —
        meaning "no participant filter", i.e. fetch for every meeting).
    """
    return [item.strip() for item in config.getlist(key) if item.strip()]


# ---------------------------------------------------------------------------
# Vault + fetch scope
# ---------------------------------------------------------------------------

#: Absolute path to the user's existing contract-structured Obsidian vault
#: (external to the repo). No default — must be configured.
WIKI_KB_VAULT_PATH: str = config.get("WIKI_KB_VAULT_PATH", fallback="")

#: Participant email allowlist applied to the Fireflies fetch
#: (``FirefliesFilters.participants``). Empty means no participant filter.
WIKI_KB_PARTICIPANTS: list[str] = _participants("WIKI_KB_PARTICIPANTS")


# ---------------------------------------------------------------------------
# Model tiers (G7) — provider-agnostic "provider:model" strings resolved
# through LLMFactory, never a provider SDK directly.
# ---------------------------------------------------------------------------

#: Strong tier — reconciliation, ambiguous classification, contradiction
#: reasoning. Default Google/Gemini; may be set to ``anthropic:…`` or
#: ``openai-codex:…`` (any ``SUPPORTED_CLIENTS`` provider).
WIKI_KB_LLM_STRONG: str = config.get("WIKI_KB_LLM_STRONG", fallback="google:gemini-2.5-pro")

#: Cheap tier — bulk extraction, summary-first reads.
WIKI_KB_LLM_CHEAP: str = config.get("WIKI_KB_LLM_CHEAP", fallback="google:gemini-2.5-flash")


# ---------------------------------------------------------------------------
# Scheduling + catch-up (G10)
# ---------------------------------------------------------------------------

#: 5-field cron expression (minute hour day month day_of_week), hourly by
#: default so each iteration processes a small batch (G10).
WIKI_KB_INGEST_CRON: str = config.get("WIKI_KB_INGEST_CRON", fallback="0 * * * *")

#: Cost/fidelity profile for an ingest run. ``"full"`` (default) runs the whole
#: contract pipeline at full fidelity for steady-state. ``"backfill"`` trades
#: fidelity for cost on a one-time historical import — summary-only classify
#: (no strong-tier transcript fallback), primary-project reconcile only (no
#: per-additional-project reconcile), no contradiction detection, no per-run
#: overview update; entities/concepts are still resolved (batched, cheap tier).
#: Also passable per-call via ``ingest(profile="backfill")``.
WIKI_KB_INGEST_PROFILE: str = config.get("WIKI_KB_INGEST_PROFILE", fallback="full")

#: Per-run cap on the number of meetings processed (bounded chunks — spec
#: Module 6). ``None`` (unset) means no cap.
WIKI_KB_INGEST_LIMIT: int | None = config.getint("WIKI_KB_INGEST_LIMIT", fallback=0) or None

#: Per-run cap on the number of NEW meetings fetched+compiled (the backfill
#: chunk size). Distinct from ``WIKI_KB_INGEST_LIMIT``: that bounds the listing
#: examined (steady-state throughput), whereas this bounds actual NEW meetings
#: while the fetch-gate pages PAST already-known ones — which is what lets a
#: chunked backfill progress instead of re-listing the newest (already-done)
#: meetings and stalling. It also bounds per-run Fireflies calls (~2×this) and
#: per-run LLM cost. ``0``/unset means no cap (process every new meeting in the
#: window in one run). Also passable per-call via ``ingest(max_new=…)``.
WIKI_KB_MAX_NEW_PER_RUN: int | None = config.getint("WIKI_KB_MAX_NEW_PER_RUN", fallback=0) or None

#: Large-backlog guard: a manual wide-window ``ingest(lookback_days=…)``
#: is bounded by this many days to avoid an unbounded catch-up run.
WIKI_KB_MAX_CATCHUP_DAYS: int = config.getint("WIKI_KB_MAX_CATCHUP_DAYS", fallback=90)

#: Module 17 quarantine auto-retry cap. A meeting the LLM cannot compile is
#: quarantined to ``Raw/Failed/<source-id>/`` and auto-retried on subsequent
#: ingests up to this many total attempts; after the cap it is parked as
#: ``reprocess-exhausted`` for a human (no infinite retry).
WIKI_KB_MAX_REPROCESS_ATTEMPTS: int = config.getint("WIKI_KB_MAX_REPROCESS_ATTEMPTS", fallback=3)


# ---------------------------------------------------------------------------
# Archive / active window (D7)
# ---------------------------------------------------------------------------

#: Rolling "active" window (days) used by §18 project meeting indexes and
#: the §31 archive workflow. Default 14 (D7).
WIKI_KB_ACTIVE_WINDOW_DAYS: int = config.getint("WIKI_KB_ACTIVE_WINDOW_DAYS", fallback=14)


# ---------------------------------------------------------------------------
# Raw capture root (§13/§14)
# ---------------------------------------------------------------------------

#: Vault-relative root for the immutable raw-bundle capture
#: (``Raw/Incoming/`` and ``Raw/Processed/…`` live under this root).
WIKI_KB_RAW_ROOT: str = config.get("WIKI_KB_RAW_ROOT", fallback="Raw")


# ---------------------------------------------------------------------------
# Email digests (G9) — retained but shipped disabled.
# ---------------------------------------------------------------------------

FIREFLIES_WIKI_EMAIL_ENABLED: bool = config.getboolean(
    "FIREFLIES_WIKI_EMAIL_ENABLED",
    fallback=False,
)
