"""
WebSocket / token authentication infrastructure.

Shared, dependency-light auth primitives for any AI-Parrot service that needs
to authenticate connections — typically WebSocket transports that validate a
JWT from the ``Sec-WebSocket-Protocol`` subprotocol or a first ``auth`` message
(browsers cannot set an ``Authorization`` header on a WebSocket).

This module lives in ``parrot.core`` precisely so it carries **no hard
dependencies** on any concrete service (voice bots, form designer, etc.). It
imports only the standard library, ``navconfig.logging`` and — lazily, inside
``validate()`` — ``jwt`` / ``navigator_auth``. Consumers:

- ``parrot.voice.handler`` (VoiceChatHandler) — re-exports for backward compat.
- ``parrot_formdesigner`` audio-form WebSocket handler.
- any future WS service requiring authentication.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
)
from navconfig.logging import logging

__all__ = ["AuthenticatedUser", "TokenValidator"]


@dataclass
class AuthenticatedUser:
    """Represents an authenticated user from a JWT token."""
    user_id: str
    username: str
    email: str = ""
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    raw_payload: Dict[str, Any] = field(default_factory=dict)


class TokenValidator:
    """
    JWT Token validator.

    Supports multiple validation backends:
    - navigator_auth (production)
    - Custom validator function
    - Fallback for testing
    """

    def __init__(
        self,
        *,
        secret_key: Optional[str] = None,
        algorithm: str = "HS256",
        validator_func: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        allow_anonymous: bool = False,
    ):
        """
        Initialize token validator.

        Args:
            secret_key: JWT secret key (if not using navigator_auth)
            algorithm: JWT algorithm (default HS256)
            validator_func: Custom async validator function
            allow_anonymous: Allow connections without authentication
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.validator_func = validator_func
        self.allow_anonymous = allow_anonymous
        self.logger = logging.getLogger(f"{__name__}.TokenValidator")

    async def validate(self, token: str) -> Optional[AuthenticatedUser]:
        """
        Validate JWT token and return user info.

        Args:
            token: JWT bearer token

        Returns:
            AuthenticatedUser if valid, None otherwise
        """
        if not token:
            return None

        # Try custom validator first
        if self.validator_func:
            try:
                if asyncio.iscoroutinefunction(self.validator_func):
                    result = await self.validator_func(token)
                else:
                    result = self.validator_func(token)

                if result:
                    return AuthenticatedUser(
                        user_id=str(result.get('user_id', result.get('sub', ''))),
                        username=result.get('username', result.get('preferred_username', 'user')),
                        email=result.get('email', ''),
                        roles=result.get('roles', []),
                        permissions=result.get('permissions', []),
                        raw_payload=result,
                    )
            except Exception as e:
                self.logger.warning("Custom validator error: %s", e)
                return None

        # Try navigator_auth
        try:
            from navigator_auth.conf import SECRET_KEY, AUTH_JWT_ALGORITHM
            import jwt

            payload = jwt.decode(
                token,
                SECRET_KEY,
                algorithms=[AUTH_JWT_ALGORITHM]
            )
            return AuthenticatedUser(
                user_id=str(payload.get('user_id', payload.get('sub', ''))),
                username=payload.get('username', payload.get('preferred_username', 'user')),
                email=payload.get('email', ''),
                roles=payload.get('roles', []),
                permissions=payload.get('permissions', []),
                raw_payload=payload,
            )

        except ImportError:
            # navigator_auth not available, try with provided secret
            if self.secret_key:
                try:
                    import jwt
                    payload = jwt.decode(
                        token,
                        self.secret_key,
                        algorithms=[self.algorithm]
                    )
                    return AuthenticatedUser(
                        user_id=str(payload.get('user_id', payload.get('sub', ''))),
                        username=payload.get('username', 'user'),
                        email=payload.get('email', ''),
                        roles=payload.get('roles', []),
                        permissions=payload.get('permissions', []),
                        raw_payload=payload,
                    )
                except Exception as e:
                    self.logger.warning("JWT decode error: %s", e)
                    return None

            # Fallback for testing (accept any token)
            self.logger.warning(
                "No auth backend available, using fallback validation"
            )
            return AuthenticatedUser(
                user_id=f"test_{token[:8]}",
                username=f"user_{token[:8]}",
                email="test@example.com",
                roles=[],
            )

        except Exception as e:
            self.logger.warning("Token validation error: %s", e)
            return None
