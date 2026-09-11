"""Strict-qualification registry for Bedrock/Mantle question budgets (FEAT-550, spec §2.5).

Ships EMPTY on purpose: on the inspected environment (botocore 1.35.36, openai 3.3.1)
no model/route/SDK combination is qualified for strict admission. Records are only
added after an opt-in live probe (see examples/clients/smoke/smoke_token_budget_qualification.py).
"""
from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QualificationKey:
    """Exact tuple that must match for strict admission — no wildcards (spec §2.5)."""

    model: str
    endpoint: str            # region or Mantle base_url host
    route: str               # "converse" | "invoke_model" | "chat_completions"
    tools: bool
    schema: bool
    cache: bool
    thinking: bool
    stream: bool
    sdk_versions: tuple[tuple[str, str], ...]   # (("botocore","1.35.36"), ("aiobotocore","2.15.2")) — sorted by name
    count_method: str
    output_cap_semantics: str


@dataclass(frozen=True)
class QualificationRecord:
    """A passing probe record; `evidence_ref` points at the committed artifacts/logs entry."""

    key: QualificationKey
    qualification_id: str
    evidence_ref: str


STRICT_QUALIFICATIONS: tuple[QualificationRecord, ...] = ()


def installed_sdk_versions(*names: str) -> tuple[tuple[str, str], ...]:
    """Return sorted (name, version) pairs for installed distributions; missing → "absent"."""
    out = []
    for n in sorted(names):
        try:
            out.append((n, importlib.metadata.version(n)))
        except importlib.metadata.PackageNotFoundError:
            out.append((n, "absent"))
    return tuple(out)


def match_qualification(key: QualificationKey, *, registry: tuple[QualificationRecord, ...] = STRICT_QUALIFICATIONS) -> Optional[QualificationRecord]:
    """Exact-match lookup; returns None when unqualified."""
    for rec in registry:
        if rec.key == key:
            return rec
    return None


def probe_count_tokens_support() -> bool:
    """True only if the INSTALLED botocore service model exposes Runtime CountTokens (no network, no credentials)."""
    try:
        import botocore.session
        model = botocore.session.get_session().get_service_model("bedrock-runtime")
        return "CountTokens" in set(model.operation_names)
    except Exception as exc:  # noqa: BLE001 — absence of the SDK is "unsupported", not an error
        logger.debug("CountTokens probe failed: %s", exc)
        return False


__all__ = ["QualificationKey", "QualificationRecord", "STRICT_QUALIFICATIONS", "installed_sdk_versions", "match_qualification", "probe_count_tokens_support"]
