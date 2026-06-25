"""ShellTool Security — re-export shim (FEAT-252).

The generic security engine (``CommandSanitizer`` / ``SecurityPolicy`` /
``SecurityLevel`` / ``ValidationResult`` / ``CommandVerdict`` /
``CommandRule`` / ``CommandSecurityError``) has been relocated into core
``parrot.security.command_sanitizer`` so that ``PythonCodeSanitizer`` and
``OutputScrubber`` can depend on it without creating an upward import.

All public names are re-exported verbatim here so every existing import of
the form ``from parrot_tools.shell_tool.security import ...`` keeps working
without any change at the call-site.
"""
from __future__ import annotations

from typing import Optional

from parrot.security.command_sanitizer import (  # re-exported for backward compatibility (FEAT-252)
    SecurityLevel,
    CommandVerdict,
    ValidationResult,
    CommandRule,
    CommandSecurityError,
    SecurityPolicy,
    CommandSanitizer,
)

__all__ = [
    "SecurityLevel",
    "CommandVerdict",
    "ValidationResult",
    "CommandRule",
    "CommandSecurityError",
    "SecurityPolicy",
    "CommandSanitizer",
    # Shell-specific helpers below
    "SecureShellMixin",
]


# =============================================================================
# SecureShellMixin  (shell-specific — stays in shell_tool)
# =============================================================================


class SecureShellMixin:
    """Mixin that adds security validation to ShellTool via composition.

    Provides three public methods:

    - ``set_security_policy(policy)`` — attach a ``SecurityPolicy``; creates
      a ``CommandSanitizer`` internally.
    - ``validate_command(command)`` — return a ``ValidationResult``.
    - ``assert_command_safe(command)`` — raise ``CommandSecurityError`` if the
      command is denied or requires review.

    Backward-compatible design: if no policy has been set (``_sanitizer`` is
    ``None``), ``validate_command`` returns ALLOWED for every command, matching
    the old no-security behaviour.

    Example:
        >>> class MyShell(SecureShellMixin):
        ...     pass
        >>> shell = MyShell()
        >>> shell.set_security_policy(SecurityPolicy.moderate())
        >>> shell.assert_command_safe("rm -rf /")  # raises CommandSecurityError
    """

    _sanitizer: Optional[CommandSanitizer] = None

    def set_security_policy(self, policy: SecurityPolicy) -> None:
        """Attach a security policy, replacing any previously set policy.

        Args:
            policy: The ``SecurityPolicy`` to enforce on subsequent calls.
        """
        self._sanitizer = CommandSanitizer(policy)

    def validate_command(self, command: str) -> ValidationResult:
        """Validate a command string against the active security policy.

        If no policy has been set, every command is ALLOWED (backward compat).

        Args:
            command: The raw command string to validate.

        Returns:
            A ``ValidationResult`` with the verdict, reasons, and risk score.
        """
        if self._sanitizer is None:
            return ValidationResult(
                verdict=CommandVerdict.ALLOWED,
                command=command,
                risk_score=0.0,
            )
        return self._sanitizer.validate(command)

    def assert_command_safe(self, command: str) -> None:
        """Validate and raise if the command is denied or needs review.

        ``NEEDS_REVIEW`` is treated as ``DENIED`` in automated contexts
        (per Open Q1 resolution in FEAT-038 spec).

        Args:
            command: The raw command string to validate.

        Raises:
            CommandSecurityError: If the command verdict is DENIED or
                NEEDS_REVIEW.
        """
        result = self.validate_command(command)
        if result.is_denied:
            raise CommandSecurityError(
                f"Command denied: {command!r}",
                result=result,
            )
        if result.verdict == CommandVerdict.NEEDS_REVIEW:
            raise CommandSecurityError(
                f"Command requires review (treated as denied): {command!r}",
                result=result,
            )
