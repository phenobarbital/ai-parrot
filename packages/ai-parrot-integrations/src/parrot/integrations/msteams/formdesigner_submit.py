"""Pure helpers for forwarding FormDesigner Teams-card submissions (FEAT-551 M4).

No botbuilder import here on purpose: everything is unit-testable without the ``msteams`` extra.
The wrapper (``wrapper.py``) owns the aiohttp session and calls these in order:
parse_envelope -> verify_envelope -> RecentActivityCache.seen -> extract_answers -> post_submission -> build_reply_card.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import time
from typing import Any
from urllib.parse import urlparse

import aiohttp
from pydantic import BaseModel, ValidationError

from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION  # verified: cards/spec.py:12
from parrot_formdesigner.renderers.teams import ENVELOPE_KEY, RESERVED_CONTROL_KEYS, TeamsSubmitEnvelope  # TASK-3147

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES: int = 1_048_576


class EnvelopeRejected(Exception):
    """User-facing reason why a card submission was refused."""


def parse_envelope(submitted_data: dict[str, Any]) -> TeamsSubmitEnvelope:
    """Validate ``submitted_data["_formdesigner"]``; raise EnvelopeRejected when missing/malformed."""
    raw = submitted_data.get(ENVELOPE_KEY)
    if not isinstance(raw, dict):
        raise EnvelopeRejected("This card does not carry a valid FormDesigner envelope.")
    try:
        return TeamsSubmitEnvelope.model_validate(raw)
    except ValidationError as exc:
        logger.warning("formdesigner envelope rejected: %s", exc.error_count())
        raise EnvelopeRejected("This card's FormDesigner envelope is malformed.") from exc


def verify_envelope(
    env: TeamsSubmitEnvelope,
    *,
    allowed_hosts: list[str],
    secret: str | None,
    api_base_path: str = "/api/v1",
    require_signature: bool = True,
) -> None:
    """SSRF guard (spec S3). Order: https -> host allowlist -> path/tenant/uid -> signature.

    ``tenant`` and ``form_uid`` inside the envelope are client-supplied card data, so an
    unsigned envelope is unauthenticated routing. Raises ``EnvelopeRejected`` when
    ``require_signature`` is True and ``secret`` is None; pass ``require_signature=False``
    only where unsigned submissions were explicitly allowed.
    """
    url = urlparse(str(env.submit_url))
    if url.scheme != "https":
        raise EnvelopeRejected("Submission target must use https.")
    if (url.hostname or "").lower() not in {h.lower() for h in allowed_hosts}:
        raise EnvelopeRejected("Submission target host is not allowed for this bot.")
    expected_path = f"{api_base_path.rstrip('/')}/{env.tenant}/forms/{env.form_uid}/data"
    if url.path != expected_path:
        raise EnvelopeRejected("Submission target does not match the form in the envelope.")
    if secret is None:
        if require_signature:
            logger.warning("formdesigner envelope refused: no signing secret configured (tenant=%s)", env.tenant)
            raise EnvelopeRejected("Submission envelope signature is invalid.")
    elif not env.verify(secret):
        raise EnvelopeRejected("Submission envelope signature is invalid.")


def resolve_submit_tenant(
    env: TeamsSubmitEnvelope,
    *,
    asserted_tenant_id: str | None,
    tenant_map: dict[str, str] | None,
    api_base_path: str = "/api/v1",
) -> tuple[TeamsSubmitEnvelope, bool]:
    """Return ``(envelope, overridden)``. A mapped ``asserted_tenant_id`` wins over ``env.tenant``.

    ``asserted_tenant_id`` is the Bot Framework-asserted Azure AD tenant GUID; ``tenant_map``
    maps it to a FormDesigner tenant slug. On override the ``submit_url`` path is REBUILT from
    ``api_base_path``/tenant/``form_uid`` — never string-replaced. Returns the envelope
    unchanged with ``False`` when the id is None, unmapped, or already agrees.
    """
    if not asserted_tenant_id or not tenant_map:
        return env, False
    resolved = tenant_map.get(asserted_tenant_id)
    if not resolved or resolved == env.tenant:
        return env, False
    url = urlparse(str(env.submit_url))
    path = f"{api_base_path.rstrip('/')}/{resolved}/forms/{env.form_uid}/data"
    submit_url = url._replace(path=path).geturl()
    return env.model_copy(update={"tenant": resolved, "submit_url": submit_url}), True


def extract_answers(submitted_data: dict[str, Any]) -> dict[str, Any]:
    """Raw card values minus exactly the reserved control keys (spec S5/S6 — no coercion here)."""
    return {k: v for k, v in submitted_data.items() if k not in RESERVED_CONTROL_KEYS}


class SubmitOutcome(BaseModel):
    """Result of the forwarding POST. ``status == 0`` means the request never completed."""

    status: int
    body: dict[str, Any] | None = None
    error: str | None = None


async def post_submission(
    session: aiohttp.ClientSession,
    env: TeamsSubmitEnvelope,
    answers: dict[str, Any],
    *,
    bearer_token: str | None,
    timeout: float,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> SubmitOutcome:
    """POST the legacy JSON body to ``env.submit_url`` (no redirects, bounded timeout and body size)."""
    headers = {"Accept": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    try:
        async with session.post(
            str(env.submit_url),
            json=answers,
            headers=headers,
            allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            # aiohttp's StreamReader.read(n) returns whatever is currently buffered once it
            # has waited once — it does NOT guarantee n bytes or EOF in a single call. A slow
            # network, chunked transfer, or proxy can deliver the body across several reads,
            # so a single read() risks silently truncating it. Loop until EOF or the cap.
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = await resp.content.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_response_bytes:
                    return SubmitOutcome(status=resp.status, error="response too large")
            raw = b"".join(chunks)
            body = None
            if raw:
                try:
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        body = None
                except Exception:
                    pass
            return SubmitOutcome(status=resp.status, body=body)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return SubmitOutcome(status=0, error=type(exc).__name__)


def build_reply_card(outcome: SubmitOutcome, env: TeamsSubmitEnvelope) -> dict[str, Any]:
    """Map the outcome to an Adaptive Card dict (spec §3 M4 mapping: 200 / 422 / 401-403 / 404 / 0-5xx)."""
    body_elements = []

    if outcome.status == 200:
        sub_id = ""
        if outcome.body and isinstance(outcome.body, dict):
            sub_id = outcome.body.get("submission_id", "")
        text = "Thank you! Your submission has been received successfully."
        if sub_id:
            text += f"\n\n**Submission ID:** {sub_id}"
        body_elements.append({"type": "TextBlock", "text": text, "wrap": True, "color": "Good"})
    elif outcome.status == 422:
        body_elements.append(
            {
                "type": "TextBlock",
                "text": "Your submission contains validation errors. Please correct them and try again:",
                "wrap": True,
                "weight": "Bolder",
                "color": "Attention",
            }
        )
        errors = {}
        if outcome.body and isinstance(outcome.body, dict):
            errors = outcome.body.get("errors", {})
        if isinstance(errors, dict) and errors:
            for field_id, msgs in errors.items():
                if isinstance(msgs, list):
                    msg_str = ", ".join(str(m) for m in msgs)
                else:
                    msg_str = str(msgs)
                body_elements.append(
                    {"type": "TextBlock", "text": f"- **{field_id}**: {msg_str}", "wrap": True, "isSubtle": True}
                )
        else:
            body_elements.append(
                {"type": "TextBlock", "text": "Unknown validation error occurred.", "wrap": True, "isSubtle": True}
            )
    elif outcome.status in (401, 403):
        body_elements.append(
            {
                "type": "TextBlock",
                "text": "Submission failed: You do not have permission to submit this private form.",
                "wrap": True,
                "color": "Attention",
                "weight": "Bolder",
            }
        )
    elif outcome.status == 404:
        body_elements.append(
            {
                "type": "TextBlock",
                "text": "Submission failed: The target form could not be found.",
                "wrap": True,
                "color": "Attention",
                "weight": "Bolder",
            }
        )
    else:
        # status == 0 or 5xx or other unhandled status
        err_msg = outcome.error or f"HTTP {outcome.status}"
        body_elements.append(
            {
                "type": "TextBlock",
                "text": f"Submission failed: Could not reach the submission server ({err_msg}). Please try again later.",
                "wrap": True,
                "color": "Attention",
                "weight": "Bolder",
            }
        )

    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": DEFAULT_ADAPTIVE_CARD_VERSION,
        "body": body_elements,
    }


class RecentActivityCache:
    """Best-effort in-process TTL set of Bot Framework activity ids (spec S9)."""

    def __init__(self, ttl_seconds: float = 300.0, max_items: int = 2048) -> None:
        self._ttl = ttl_seconds
        self._max = max_items
        self._seen: collections.OrderedDict[str, float] = collections.OrderedDict()

    def seen(self, activity_id: str) -> bool:
        """Return True if ``activity_id`` was recorded within the TTL; otherwise record it and return False."""
        now = time.time()
        # Evict expired items
        while self._seen:
            first_key = next(iter(self._seen))
            if now - self._seen[first_key] > self._ttl:
                self._seen.pop(first_key)
            else:
                break

        if activity_id in self._seen:
            # Update timestamp to keep it fresh or just return True?
            # Spec S9: "Return True if activity_id was recorded within the TTL; otherwise record it and return False."
            # Let's just return True.
            return True

        # Evict oldest if we exceed max_items
        if len(self._seen) >= self._max:
            self._seen.popitem(last=False)

        self._seen[activity_id] = now
        return False
