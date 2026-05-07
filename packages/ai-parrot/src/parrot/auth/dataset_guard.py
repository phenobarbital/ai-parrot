"""PBAC enforcement helper for DatasetManager.

This module provides ``DatasetPolicyGuard``, a wrapper around
``navigator-auth``'s ``PolicyEvaluator`` that exposes three async methods
tailored to dataset-level and column-level access control.

Architecture
------------
``DatasetPolicyGuard`` mirrors ``PBACPermissionResolver``
(``parrot/auth/resolver.py:247``) in shape and discipline:

- Same lazy-import pattern for ``navigator-auth`` types (fail-open on
  ``ImportError``).
- Same ``to_eval_context`` bridge from ``PermissionContext`` to
  ``EvalContext``.
- Same WARNING-on-deny log format for operator visibility.
- Same fail-closed semantics on any non-``ImportError`` runtime error.

It is a **sibling** of ``PBACPermissionResolver``, NOT a subclass.  Both
wrap the same ``PolicyEvaluator`` instance but expose different interfaces:

- ``PBACPermissionResolver`` → ``ResourceType.TOOL``, action ``tool:execute``
- ``DatasetPolicyGuard``      → ``ResourceType.DATASET``, actions
  ``dataset:read`` / ``dataset:column:read``

Usage example (wired at app startup after ``setup_pbac``)::

    pdp, evaluator, guardian = setup_pbac(app, policy_dir="policies")
    if evaluator is not None:
        dataset_guard = DatasetPolicyGuard(evaluator=evaluator)
        dataset_manager = DatasetManager(policy_guard=dataset_guard)

Resource naming convention
--------------------------
``DatasetPolicyGuard`` passes resource names to ``PolicyEvaluator`` using the
``"dataset:<name>"`` prefix for dataset-level checks and
``"dataset:<dataset>:<column>"`` for column-level checks.  This matches the
resource key format declared in YAML policy files::

    resources:
      - "dataset:financial_data"        # dataset:read
      - "dataset:sales:profit_margin"   # dataset:column:read
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from .permission import PermissionContext, to_eval_context

if TYPE_CHECKING:
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator


class DatasetPolicyGuard:
    """PBAC enforcement for DatasetManager.

    Wraps a shared ``PolicyEvaluator`` (the same instance used by
    ``Guardian`` and ``PBACPermissionResolver``) with dataset-specific
    resource type and actions.

    Failure semantics (mirrors ``PBACPermissionResolver``):

    - ``ImportError`` on ``navigator-auth`` → all methods return
      "all-allowed" (fail-open; preserves backwards compat when the SDK is
      absent).
    - Any *other* exception inside a filter/check → log WARNING with
      ``user_id`` + resource name + reason; return DENY for the affected
      subset (fail-closed).
    - ``PermissionContext.session`` is ``None`` or ``user_id`` is ``None``
      → DENY for every resource (fail-closed).

    Backwards-compatible opt-in: ``DatasetManager`` instantiated without
    a ``policy_guard`` argument performs no enforcement.  Datasets that
    have no matching YAML policy remain visible to all users.

    Args:
        evaluator: Shared ``PolicyEvaluator`` instance (injected by app
            bootstrap after ``setup_pbac()``).
        logger: Optional logger; defaults to
            ``logging.getLogger(__name__)``.

    Example::

        guard = DatasetPolicyGuard(evaluator=evaluator)
        allowed = await guard.filter_datasets(ctx, ["sales", "finance"])
        # → {"sales"}  (if "finance" is denied for this user)
    """

    def __init__(
        self,
        evaluator: "PolicyEvaluator",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """Initialize the guard with a shared ``PolicyEvaluator``.

        Args:
            evaluator: A ``PolicyEvaluator`` instance shared with Guardian
                and ``PBACPermissionResolver``.
            logger: Optional logger; defaults to module-level logger.
        """
        self._evaluator = evaluator
        self.logger = logger or logging.getLogger(__name__)

    # ──────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────

    def _get_user_id(self, context: PermissionContext) -> Optional[str]:
        """Extract user_id safely from context.

        Args:
            context: The permission context to inspect.

        Returns:
            ``user_id`` string when available, ``None`` otherwise.
        """
        session = getattr(context, "session", None)
        if session is None:
            return None
        return getattr(session, "user_id", None)

    # ──────────────────────────────────────────────────────────────────────
    # Public async interface
    # ──────────────────────────────────────────────────────────────────────

    async def filter_datasets(
        self,
        context: PermissionContext,
        dataset_names: list[str],
    ) -> set[str]:
        """Return the subset of datasets the user is permitted to read.

        Performs a single batch ``filter_resources`` call against the
        ``PolicyEvaluator`` using ``resource_type=ResourceType.DATASET`` and
        ``action="dataset:read"``.

        Failure semantics:

        - Empty input → returns empty set immediately (no evaluator call).
        - Missing session / user_id → returns empty set (fail-closed).
        - ``ImportError`` for ``navigator-auth`` → returns all names
          (fail-open; SDK absent → no enforcement).
        - Any other exception → logs WARNING and returns empty set
          (fail-closed).

        Args:
            context: Request-scoped permission context carrying user identity.
            dataset_names: Full list of candidate dataset names.

        Returns:
            Subset of ``dataset_names`` that the policy allows this user to
            read.  Returns all names when ``navigator-auth`` is not installed.
        """
        if not dataset_names:
            return set()

        # Fail-closed: no session or user → deny everything.
        user_id = self._get_user_id(context)
        if user_id is None:
            self.logger.warning(
                "PBAC dataset deny (no identity): resource=<all> reason=missing session"
            )
            return set()

        try:
            from navigator_auth.abac.policies.resources import ResourceType
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            # navigator-auth not installed — fail open.
            return set(dataset_names)

        eval_ctx = to_eval_context(context)
        env = Environment()

        try:
            # Prefix names to match YAML resource key format: "dataset:<name>"
            prefixed = [f"dataset:{name}" for name in dataset_names]
            filtered = self._evaluator.filter_resources(
                ctx=eval_ctx,
                resource_type=ResourceType.DATASET,
                resource_names=prefixed,
                action="dataset:read",
                env=env,
            )
            # Strip the "dataset:" prefix from the allowed list to recover bare names.
            return {
                name[len("dataset:"):] for name in filtered.allowed
                if name.startswith("dataset:")
            }
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "PBAC dataset deny (error): user=%s resource=<batch> reason=%s",
                user_id,
                exc,
            )
            return set()

    async def filter_columns(
        self,
        context: PermissionContext,
        dataset_name: str,
        columns: list[str],
    ) -> list[str]:
        """Return allowed columns in their original input order.

        Calls ``filter_resources`` with composite resource names
        ``"<dataset_name>:<column>"`` and ``action="dataset:column:read"``.
        The returned list preserves the original column order — it is a
        filtered subsequence of ``columns``, not a reordering.

        Drop-silent semantics: denied columns are simply absent from the
        output.  The caller (``DatasetManager``) must NOT add any marker,
        metadata field, or warning that exposes the redaction to the LLM.

        Failure semantics mirror ``filter_datasets``.

        Args:
            context: Request-scoped permission context.
            dataset_name: Name of the dataset owning these columns.
            columns: Full list of column names to evaluate.

        Returns:
            Allowed columns in original input order.  Returns all columns
            when ``navigator-auth`` is not installed.
        """
        if not columns:
            return []

        user_id = self._get_user_id(context)
        if user_id is None:
            self.logger.warning(
                "PBAC column deny (no identity): dataset=%s resource=<all columns> "
                "reason=missing session",
                dataset_name,
            )
            return []

        try:
            from navigator_auth.abac.policies.resources import ResourceType
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return list(columns)

        eval_ctx = to_eval_context(context)
        env = Environment()

        # Composite resource names: "dataset:<dataset>:<column>"
        # Matches the YAML resource key format: "dataset:sales:profit_margin"
        resource_names = [f"dataset:{dataset_name}:{col}" for col in columns]

        try:
            filtered = self._evaluator.filter_resources(
                ctx=eval_ctx,
                resource_type=ResourceType.DATASET,
                resource_names=resource_names,
                action="dataset:column:read",
                env=env,
            )
            # Strip "dataset:<dataset>:" prefix to recover bare column names.
            prefix = f"dataset:{dataset_name}:"
            allowed_set = {
                name[len(prefix):] for name in filtered.allowed
                if name.startswith(prefix)
            }
            # Preserve original order.
            return [col for col in columns if col in allowed_set]
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "PBAC column deny (error): user=%s dataset=%s reason=%s",
                user_id,
                dataset_name,
                exc,
            )
            return []

    async def can_read_dataset(
        self,
        context: PermissionContext,
        dataset_name: str,
    ) -> bool:
        """Single-resource check — can the user read this dataset?

        Used by ``DatasetManager._pre_execute`` as a Layer-2 defence-in-depth
        check after the dataset has already been removed from the tool list by
        ``get_tools_filtered``.

        Logs a WARNING on denial (same format as ``PBACPermissionResolver``
        at ``resolver.py:331–337``) to provide an audit trail for callers
        that bypass the Layer-1 filter.

        Failure semantics:

        - Missing session / user_id → returns ``False`` (fail-closed).
        - ``ImportError`` for ``navigator-auth`` → returns ``True`` (fail-open).
        - Any other exception → logs WARNING and returns ``False``
          (fail-closed).

        Args:
            context: Request-scoped permission context.
            dataset_name: Name of the dataset to check.

        Returns:
            ``True`` when the policy allows this user to read the dataset,
            ``False`` otherwise.
        """
        user_id = self._get_user_id(context)
        if user_id is None:
            self.logger.warning(
                "PBAC dataset deny (no identity): resource=%s reason=missing session",
                dataset_name,
            )
            return False

        try:
            from navigator_auth.abac.policies.resources import ResourceType
            from navigator_auth.abac.policies.environment import Environment
        except ImportError:
            return True

        eval_ctx = to_eval_context(context)
        env = Environment()

        try:
            # Prefix to match YAML resource key format: "dataset:<name>"
            result = self._evaluator.check_access(
                ctx=eval_ctx,
                resource_type=ResourceType.DATASET,
                resource_name=f"dataset:{dataset_name}",
                action="dataset:read",
                env=env,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "PBAC dataset deny (error): user=%s resource=%s reason=%s",
                user_id,
                dataset_name,
                exc,
            )
            return False

        if not result.allowed:
            self.logger.warning(
                "PBAC Layer 2 DENY: dataset=%s user=%s policy=%s reason=%s",
                dataset_name,
                user_id,
                result.matched_policy,
                result.reason,
            )

        return result.allowed
