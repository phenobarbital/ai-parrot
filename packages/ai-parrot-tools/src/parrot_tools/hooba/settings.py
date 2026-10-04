"""Hooba configuration from the environment (FEAT-602 M2)."""

from __future__ import annotations

import os
from typing import Dict, Mapping, Optional

from pydantic import BaseModel


class HoobaSettings(BaseModel):
    """Connection and account settings for api.hooba.com."""

    base_url: str = "https://api.hooba.com"
    account_id: int
    member_id: Optional[int] = None
    user_id: Optional[int] = None
    subscription_id: Optional[int] = None
    language: str = "es"
    origin: str = "https://app.hooba.com"
    catalog_dir: Optional[str] = None
    spec_path: Optional[str] = None
    include_tags: Optional[list[str]] = None
    credential_provider: str = "hooba"
    credential_user_id: str = "hooba"

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "HoobaSettings":
        """Build settings from ``HOOBA_*`` variables (default ``os.environ``).

        Raises:
            ValueError: ``HOOBA_ACCOUNT_ID`` is missing or not an integer (message names the variable).
        """
        env = os.environ if env is None else env

        account_value = env.get("HOOBA_ACCOUNT_ID", "").strip()
        if not account_value:
            raise ValueError("HOOBA_ACCOUNT_ID is required")
        try:
            account_id = int(account_value)
        except ValueError as exc:
            raise ValueError("HOOBA_ACCOUNT_ID must be an integer") from exc

        def optional_int(name: str) -> Optional[int]:
            value = env.get(name, "").strip()
            if not value:
                return None
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc

        include_value = env.get("HOOBA_INCLUDE_TAGS", "")
        include_tags = [tag.strip() for tag in include_value.split(",") if tag.strip()] or None
        return cls(
            base_url=env.get("HOOBA_BASE_URL", "https://api.hooba.com"),
            account_id=account_id,
            member_id=optional_int("HOOBA_MEMBER_ID"),
            user_id=optional_int("HOOBA_USER_ID"),
            subscription_id=optional_int("HOOBA_SUBSCRIPTION_ID"),
            language=env.get("HOOBA_LANGUAGE", "es"),
            origin=env.get("HOOBA_ORIGIN", "https://app.hooba.com"),
            catalog_dir=env.get("HOOBA_CATALOG_DIR") or None,
            spec_path=env.get("HOOBA_SPEC_PATH") or None,
            include_tags=include_tags,
        )

    def default_headers(self) -> Dict[str, str]:
        """Headers every Hooba API call carries (captured from the web app)."""
        return {
            "origin": self.origin,
            "x-hooba-language": self.language,
            "ngsw-bypass": "true",
            "accept": "application/json, text/plain, */*",
        }
