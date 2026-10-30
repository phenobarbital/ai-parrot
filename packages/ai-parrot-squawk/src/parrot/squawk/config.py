"""Deployment settings for Squawk, read through ``parrot.conf.config`` (env / navconfig)."""

from __future__ import annotations

from pathlib import Path

from parrot.conf import config

#: "local" | "filemanager" — which SquawkBlobStore backend a deployment uses (spec Q8).
SQUAWK_BLOB_BACKEND: str = config.get("SQUAWK_BLOB_BACKEND", fallback="local")
SQUAWK_BLOB_ROOT: Path = Path(config.get("SQUAWK_BLOB_ROOT", fallback=".squawk/blobs"))
SQUAWK_BLOB_TTL_S: int = int(config.get("SQUAWK_BLOB_TTL_S", fallback=86_400))
SQUAWK_MAX_FRAME_BYTES: int = int(config.get("SQUAWK_MAX_FRAME_BYTES", fallback=4 * 1024 * 1024))
#: Root public key for Biscuit verification (issuance is navigator-auth's, spec Q4). None ⇒ tokens refused.
SQUAWK_BISCUIT_ROOT_PUBLIC_KEY: str | None = config.get("SQUAWK_BISCUIT_ROOT_PUBLIC_KEY", fallback=None)
#: YAML overriding DEFAULT_GATE_POLICIES per data class (spec Q5). None ⇒ built-in defaults only.
_gate = config.get("SQUAWK_GATE_POLICY_PATH", fallback=None)
SQUAWK_GATE_POLICY_PATH: Path | None = Path(_gate) if _gate else None
