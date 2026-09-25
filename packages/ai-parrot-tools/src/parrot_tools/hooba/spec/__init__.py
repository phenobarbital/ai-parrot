"""The pinned Hooba OpenAPI document (FEAT-602 M3)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

PINNED_VERSION = "2026.6.17"
PINNED_FILE = Path(__file__).with_name("hooba-api-2026.6.17.pruned.json")
PINNED_SHA256 = "78a3f87c28fbcd00124eacc864d264d60196558af9477982c5b9bc0d882ef147"
REQUIRED_PATHS: tuple[str, ...] = (
    "/auth/login",
    "/auth/check",
    "/accounts/{accountId}/member",
    "/accounts/{accountId}/invoices",
    "/accounts/{accountId}/invoices/{invoiceId}/invoice-lines",
    "/accounts/{accountId}/purchase-invoices",
    "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}/purchase-invoice-lines",
    "/accounts/{accountId}/contacts",
    "/taxes",
    "/income-taxes",
    "/accounts/{accountId}/invoice-series",
    "/accounts/{accountId}/document-types",
    "/accounts/{accountId}/documents/{documentTypeId}/{entityRecordId}",
    "/accounts/{accountId}/invoices/{invoiceId}:download",
)


class HoobaSpecError(ValueError):
    """The Hooba OpenAPI document is missing, tampered with, or lacks a required path."""


def load_pinned_spec(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and validate the pinned (or overriding) Hooba OpenAPI document.

    Args:
        path: An explicit path to an OpenAPI document. When ``None``, falls back to the
            ``HOOBA_SPEC_PATH`` environment variable; when neither is set, loads the
            committed, SHA-256-pinned document bundled with this package.

    Returns:
        The decoded OpenAPI document.

    Raises:
        HoobaSpecError: bundled file hash mismatch, not OpenAPI 3.x, or a REQUIRED_PATHS entry missing.
    """
    override_path = path or os.environ.get("HOOBA_SPEC_PATH")
    is_override = bool(override_path)
    target = Path(override_path) if is_override else PINNED_FILE

    try:
        raw = target.read_bytes()
    except OSError as exc:
        raise HoobaSpecError(f"Hooba OpenAPI document not found at {target}") from exc

    if is_override:
        logger.warning(
            "Loading Hooba OpenAPI document from override path %s (skipping SHA-256 pin check)", target
        )
    else:
        digest = hashlib.sha256(raw).hexdigest()
        if digest != PINNED_SHA256:
            raise HoobaSpecError(
                f"Hooba OpenAPI document at {target} does not match the pinned SHA-256 "
                f"({digest} != {PINNED_SHA256}); refusing to load a tampered/stale spec"
            )

    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HoobaSpecError(f"Hooba OpenAPI document at {target} is not valid JSON") from exc

    openapi_version = doc.get("openapi")
    if not isinstance(openapi_version, str) or not openapi_version.startswith("3."):
        raise HoobaSpecError(
            f"Hooba OpenAPI document at {target} is not an OpenAPI 3.x document (openapi={openapi_version!r})"
        )

    doc_version = (doc.get("info") or {}).get("version")
    if is_override:
        logger.warning(
            "Hooba OpenAPI override document at %s reports version %s (pinned=%s)",
            target, doc_version, PINNED_VERSION,
        )
    if doc_version != PINNED_VERSION:
        logger.warning(
            "Hooba OpenAPI document version %s does not match pinned version %s", doc_version, PINNED_VERSION
        )

    paths = doc.get("paths") or {}
    missing = [required_path for required_path in REQUIRED_PATHS if required_path not in paths]
    if missing:
        raise HoobaSpecError(f"Hooba OpenAPI document at {target} is missing required paths: {missing}")

    return doc
