"""Agent-level execution policy: declarative tool → executor routing.

Instead of wiring an ``executor=`` kwarg into every tool constructor,
an :class:`ExecutionPolicy` lets an agent (or a bot config file)
declare *which* tools/toolkits run remotely and *through which*
executor::

    agent = Agent(
        tools=[PythonREPLTool(), weather_toolkit],
        execution_policy={
            "rules": {
                "python_repl": {"name": "docker",
                                "options": {"network_mode": "none"}},
                "WeatherToolkit": "local",
                "shell_*": {"name": "docker",
                            "options": {"mode": "ephemeral"}},
            }
        },
    )

Rule keys match, in precedence order:

1. Exact tool name (``"python_repl"``).
2. Exact toolkit class name or ``tool_prefix`` (``"WeatherToolkit"``) —
   applies to every tool the toolkit generates.
3. ``fnmatch`` wildcard against the tool name (``"shell_*"``), in rule
   declaration order.
4. Wildcard against the toolkit class name / prefix.
5. The catch-all ``"*"`` rule, when present.

Rule values are :class:`ExecutorSpec`s — a registry name plus
constructor options — or, for code-only use, a live
:class:`AbstractToolExecutor` instance. Specs are instantiated at most
once per rule, so every tool sharing a rule shares one executor (one
warm container, not N).

The policy never overrides a tool that already carries an explicit
``executor=`` from its constructor.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from .abstract import AbstractToolExecutor

logger = logging.getLogger(__name__)

# Registry of executor names → "<module>:<class>" import paths. Lazy —
# the module is only imported when a rule actually resolves to it, so
# optional dependencies (aiodocker, kubernetes_asyncio) stay optional.
EXECUTOR_REGISTRY: Dict[str, str] = {
    "local": "parrot.tools.executors.local:LocalToolExecutor",
    "docker": "parrot.tools.executors.docker:DockerToolExecutor",
    "k8s": "parrot.tools.executors.k8s:K8sToolExecutor",
    "qworker": "parrot.tools.executors.qworker:QworkerToolExecutor",
    # Reserved for the Docker Sandboxes (sbx microVM) executor once the
    # sbx CLI grows a scriptable API. Resolving it raises for now.
    "docker-sandbox": "",
}

_WILDCARD_CHARS = ("*", "?", "[")


def _has_wildcard(key: str) -> bool:
    return any(ch in key for ch in _WILDCARD_CHARS)


class ExecutorSpec(BaseModel):
    """One executor target: a registry name + constructor options.

    Attributes:
        name: Key in :data:`EXECUTOR_REGISTRY` (``"local"``,
            ``"docker"``, ``"k8s"``, ``"qworker"``).
        options: Constructor kwargs for the executor class.
        remote_timeout_seconds: When set, overrides the matched tool's
            ``remote_timeout_seconds``.
        webhook_callback_url: When set, overrides the matched tool's
            ``webhook_callback_url``.
        instance: A pre-built executor (code-only shorthand). When set,
            ``name``/``options`` are ignored and the instance is used
            as-is; its lifecycle belongs to whoever created it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = ""
    options: Dict[str, Any] = Field(default_factory=dict)
    remote_timeout_seconds: Optional[int] = None
    webhook_callback_url: Optional[str] = None
    instance: Optional[AbstractToolExecutor] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_shorthand(cls, value: Any) -> Any:
        """Accept ``"docker"`` and live executor instances as shorthand."""
        if isinstance(value, str):
            return {"name": value}
        if isinstance(value, AbstractToolExecutor):
            return {"instance": value}
        return value

    @model_validator(mode="after")
    def _require_target(self) -> "ExecutorSpec":
        if self.instance is None and not self.name:
            raise ValueError(
                "ExecutorSpec needs either a registry 'name' or a live "
                "'instance'."
            )
        return self


def build_executor(spec: "ExecutorSpec | str") -> AbstractToolExecutor:
    """Instantiate an executor from *spec* using :data:`EXECUTOR_REGISTRY`.

    Raises:
        KeyError: Unknown executor name.
        NotImplementedError: Reserved-but-unimplemented name
            (``"docker-sandbox"``).
    """
    if isinstance(spec, str):
        spec = ExecutorSpec(name=spec)
    if spec.instance is not None:
        return spec.instance
    try:
        import_path = EXECUTOR_REGISTRY[spec.name]
    except KeyError:
        raise KeyError(
            f"Unknown executor name {spec.name!r}. Known executors: "
            f"{sorted(EXECUTOR_REGISTRY)}"
        ) from None
    if not import_path:
        raise NotImplementedError(
            f"Executor {spec.name!r} is reserved but not implemented yet."
        )
    module_path, class_name = import_path.split(":", 1)
    module = importlib.import_module(module_path)
    executor_cls = getattr(module, class_name)
    return executor_cls(**spec.options)


class ExecutionPolicy(BaseModel):
    """Declarative mapping of tool/toolkit names to executors.

    See the module docstring for rule syntax and precedence. Apply with
    :meth:`apply_to_tool` (done automatically by ``ToolManager`` at
    registration time) and release pooled resources with :meth:`close`
    when the owning bot shuts down.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rules: Dict[str, ExecutorSpec] = Field(default_factory=dict)

    _instances: Dict[str, AbstractToolExecutor] = PrivateAttr(
        default_factory=dict
    )

    # -- matching ------------------------------------------------------

    @staticmethod
    def _toolkit_keys(tool: Any) -> List[str]:
        """Names under which the tool's parent toolkit can be addressed."""
        bound_method = getattr(tool, "bound_method", None)
        toolkit = (
            getattr(bound_method, "__self__", None) if bound_method else None
        )
        if toolkit is None:
            return []
        keys = [toolkit.__class__.__name__]
        prefix = getattr(toolkit, "tool_prefix", None)
        if prefix:
            keys.append(prefix)
        return keys

    def match(self, tool: Any) -> Optional[Tuple[str, ExecutorSpec]]:
        """Return the ``(rule_key, spec)`` that governs *tool*, if any."""
        tool_name = getattr(tool, "name", "") or ""
        toolkit_keys = self._toolkit_keys(tool)

        if tool_name in self.rules:
            return tool_name, self.rules[tool_name]
        for key in toolkit_keys:
            if key in self.rules:
                return key, self.rules[key]
        for key, spec in self.rules.items():
            if key == "*" or not _has_wildcard(key):
                continue
            if fnmatchcase(tool_name, key):
                return key, spec
        for key, spec in self.rules.items():
            if key == "*" or not _has_wildcard(key):
                continue
            if any(fnmatchcase(tk, key) for tk in toolkit_keys):
                return key, spec
        if "*" in self.rules:
            return "*", self.rules["*"]
        return None

    # -- resolution / application -------------------------------------

    def resolve(self, tool: Any) -> Optional[AbstractToolExecutor]:
        """Return the executor for *tool*, instantiating (and caching)
        the matched spec on first use so all tools sharing a rule share
        one executor instance."""
        matched = self.match(tool)
        if matched is None:
            return None
        rule_key, spec = matched
        if spec.instance is not None:
            return spec.instance
        executor = self._instances.get(rule_key)
        if executor is None:
            executor = build_executor(spec)
            self._instances[rule_key] = executor
        return executor

    def apply_to_tool(self, tool: Any) -> bool:
        """Assign an executor to *tool* if a rule matches.

        Explicit per-tool configuration always wins: a tool whose
        constructor already received ``executor=`` is left untouched.

        Returns:
            True when the policy attached an executor to the tool.
        """
        if getattr(tool, "executor", None) is not None:
            return False
        matched = self.match(tool)
        if matched is None:
            return False
        rule_key, spec = matched
        tool.executor = self.resolve(tool)
        if spec.remote_timeout_seconds is not None:
            tool.remote_timeout_seconds = int(spec.remote_timeout_seconds)
        if spec.webhook_callback_url is not None:
            tool.webhook_callback_url = spec.webhook_callback_url
        logger.debug(
            "ExecutionPolicy: tool %r routed via rule %r → %s",
            getattr(tool, "name", tool),
            rule_key,
            type(tool.executor).__name__,
        )
        return True

    # -- lifecycle -----------------------------------------------------

    async def close(self) -> None:
        """Close every executor this policy instantiated.

        Idempotent. Executors passed in as live ``instance`` values are
        NOT closed — their lifecycle belongs to whoever created them.
        """
        instances, self._instances = self._instances, {}
        results = await asyncio.gather(
            *(executor.close() for executor in instances.values()),
            return_exceptions=True,
        )
        for exc in results:
            if isinstance(exc, Exception):
                logger.warning("ExecutionPolicy close error: %s", exc)
