"""Error types for the shared Jira read interface (FEAT-454, M1).

Mirrors the plain-``RuntimeError``-subclass style used by
``parrot.interfaces.obsidian.abstract.VaultAccessError``.
"""


class JiraInterfaceError(RuntimeError):
    """Base class for all `JiraInterface` errors."""


class JiraAuthError(JiraInterfaceError):
    """Raised when Jira authentication is missing, unresolved, or rejected.

    Covers both the "no auth configured" case (unresolved ``auth_type``)
    and the Jira Cloud silent-auth-failure case (200 + empty result +
    ``X-Seraph-Loginreason: AUTHENTICATED_FAILED``).
    """


class JiraDependencyError(JiraInterfaceError):
    """Raised when the optional `jira` distribution is not installed."""
