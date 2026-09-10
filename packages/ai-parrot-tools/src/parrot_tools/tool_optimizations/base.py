"""Shared toolkit base for the tool-optimizations toolkits (FEAT-543).

:class:`OptimizationToolkitBase` is the single validation seam for all three
toolkits. It exists because MCP input does **not** pass through
``AbstractTool.execute()``: ``MCPToolAdapter.execute()`` calls
``tool._execute(**arguments)`` directly, so schema validation never runs.
``ToolkitTool._execute()`` does still invoke ``toolkit._pre_execute()`` with
the *raw* kwargs, before unknown keys are stripped — which makes
:meth:`OptimizationToolkitBase._pre_execute` the enforcement point for
untrusted ``tools/call`` arguments.

Direct Python calls must be safe too, so the public toolkit methods validate
their own arguments as well; this seam is defence in depth, not a substitute.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
from typing import Any, Optional

from parrot.tools.abstract import ToolResult
from parrot.tools.toolkit import AbstractToolkit
from pydantic import BaseModel, ValidationError

from .models import OperationError, OperationResult, StepResult
from .policy import OptimizationPolicy, fit_to_budget, relative_posix, resolve_operand

__all__ = ("OptimizationToolkitBase",)


class OptimizationToolkitBase(AbstractToolkit):
    """Common policy, validation and result-shaping for optimization toolkits.

    Subclasses declare :attr:`arg_models`, mapping each public method name to
    its Pydantic argument model, and implement public ``async`` methods that
    return Pydantic models.

    Attributes:
        arg_models: Method name -> argument model. Every exposed tool must
            have an entry; an unmapped tool name is rejected outright.
    """

    arg_models: dict[str, type[BaseModel]] = {}

    def __init__(
        self,
        *,
        repo_root: str | Path,
        policy: Optional[OptimizationPolicy] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the toolkit and build its policy.

        Any :class:`OptimizationPolicy` field passed as a keyword argument is
        consumed as a policy override; everything else is forwarded to
        ``AbstractToolkit.__init__``.

        Args:
            repo_root: The repository checkout this toolkit is confined to.
            policy: A fully built policy, overriding per-field keyword
                arguments when supplied.
            **kwargs: Policy overrides plus normal toolkit keyword arguments.
        """
        overrides = {key: kwargs.pop(key) for key in list(kwargs) if key in OptimizationPolicy.model_fields}
        overrides.pop("repo_root", None)
        super().__init__(**kwargs)
        self.policy = policy or OptimizationPolicy(repo_root=Path(repo_root), **overrides)
        # Capture the serializable constructor kwargs so build_envelope_from_tool
        # can reconstruct this toolkit for remote/off-process execution.
        self._init_kwargs.update(
            {
                "repo_root": str(self.policy.repo_root),
                **self.policy.model_dump(mode="json", exclude={"repo_root"}),
            }
        )
        self.logger = logging.getLogger(__name__)

    # ----------------------------------------------------------------- #
    # Lifecycle hooks
    # ----------------------------------------------------------------- #
    async def _pre_execute(self, tool_name: str, /, **kwargs: Any) -> None:
        """Validate raw tool arguments before any subprocess, model or write.

        Args:
            tool_name: The tool being invoked. Equal to the method name,
                because these toolkits never set ``tool_prefix``.
            **kwargs: The raw arguments, plus the injected permission context.

        Raises:
            ValueError: The tool is unknown or its arguments are invalid.
        """
        assert self.tool_prefix is None, "optimization toolkits must not set tool_prefix"
        kwargs.pop("_permission_context", None)
        model = self.arg_models.get(tool_name)
        if model is None:
            raise ValueError(f"unknown tool {tool_name!r}")
        try:
            model.model_validate(kwargs)
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first.get("loc", ())) or "<root>"
            raise ValueError(f"invalid arguments for {tool_name}: {location}: {first['msg']}") from exc

    async def _post_execute(self, tool_name: str, result: Any, /, **kwargs: Any) -> Any:
        """Serialize a Pydantic result into a JSON-safe ``ToolResult``.

        A domain failure is still ``status="success"`` at the ``ToolResult``
        level, carrying ``result["status"] == "error"`` — the MCP ``isError``
        flag is reserved for argument rejection and crashes. ``metadata`` stays
        empty so the adapter does not append a "Metadata:" text block.

        Args:
            tool_name: The tool that produced the result.
            result: The value returned by the toolkit method.
            **kwargs: The (filtered) tool arguments; unused.

        Returns:
            A ``ToolResult`` wrapping a JSON-compatible dict, or ``result``
            unchanged when it is already a ``ToolResult`` or a plain dict.
        """
        if isinstance(result, ToolResult):
            return result
        if isinstance(result, BaseModel):
            return ToolResult(status="success", result=result.model_dump(mode="json"), metadata={})
        return result

    # ----------------------------------------------------------------- #
    # Result helpers
    # ----------------------------------------------------------------- #
    def _ok(
        self,
        operation: str,
        data: Optional[dict[str, Any]] = None,
        steps: Optional[list[StepResult]] = None,
        started: Optional[float] = None,
        truncated: bool = False,
    ) -> OperationResult:
        """Build a bounded successful :class:`OperationResult`.

        Args:
            operation: The tool/method name.
            data: The operation payload.
            steps: Per-step outcomes, in execution order.
            started: A ``perf_counter()`` reading taken at operation start.
            truncated: True when the caller already dropped content.

        Returns:
            A result guaranteed to fit ``policy.max_result_bytes``.
        """
        return fit_to_budget(
            OperationResult(
                status="ok",
                operation=operation,
                data=data or {},
                steps=steps or [],
                truncated=truncated,
                elapsed_ms=self._elapsed_ms(started),
            ),
            self.policy.max_result_bytes,
        )

    def _error(
        self,
        operation: str,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
        steps: Optional[list[StepResult]] = None,
        started: Optional[float] = None,
        status: str = "error",
    ) -> OperationResult:
        """Build a bounded failed (or uncertain) :class:`OperationResult`.

        Args:
            operation: The tool/method name.
            code: A snake_case error code.
            message: A short human-readable explanation.
            details: Structured context for the caller.
            steps: Per-step outcomes recorded before the failure.
            started: A ``perf_counter()`` reading taken at operation start.
            status: ``error`` (default) or ``uncertain`` when the outcome of a
                remote effect is genuinely unknown.

        Returns:
            A result guaranteed to fit ``policy.max_result_bytes``.
        """
        return fit_to_budget(
            OperationResult(
                status="uncertain" if status == "uncertain" else "error",
                operation=operation,
                error=OperationError(code=code, message=message, details=details or {}),
                steps=steps or [],
                elapsed_ms=self._elapsed_ms(started),
            ),
            self.policy.max_result_bytes,
        )

    @staticmethod
    def _elapsed_ms(started: Optional[float]) -> int:
        """Return elapsed milliseconds since ``started``.

        Args:
            started: A ``perf_counter()`` reading, or None.

        Returns:
            The elapsed milliseconds, or 0 when ``started`` is None.
        """
        if started is None:
            return 0
        return max(0, int((perf_counter() - started) * 1000))

    def _repo_relative(self, candidate: str, *, readable: bool) -> str:
        """Resolve ``candidate`` under policy and return its relative path.

        Args:
            candidate: A caller-supplied path.
            readable: When True, the path must already exist.

        Returns:
            The repo-relative POSIX path.

        Raises:
            PathOutsideRootError: The path escapes the repository root.
            SecretFileError: The path matches the secret deny-list.
            SymlinkRejectedError: A component below the root is a symlink.
            PolicyError: ``readable`` is True and the path does not exist.
        """
        target = resolve_operand(self.policy, candidate, must_exist=readable)
        return relative_posix(self.policy.repo_root, target)
