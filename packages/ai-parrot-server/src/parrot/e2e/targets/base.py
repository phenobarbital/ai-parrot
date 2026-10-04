"""Target adapter protocol and launch contract (FEAT-581, M4).

This module defines the two pieces spec §3 "M4: Target registry and fixture
entry points" fixes as a normative contract, independent of both the M3
supervisor and every concrete target module:

- :class:`LaunchSpec` — the nonpersisted, secret-safe description of one
  child-process launch (``argv``/``env``/``cwd``/``stdio``), always meant to
  be executed via direct ``argv`` invocation (``shell=False``), never a
  shell string. Its ``env`` is redacted from ``repr``/``str`` (hence any
  ``self.logger`` call) and from ``model_dump()``/``model_dump_json()``.
- :class:`TargetAdapter` — the ``typing.Protocol`` every target kind's
  concrete adapter implements: ``prepare()`` returns a validated
  :class:`LaunchSpec` (or raises :class:`parrot.e2e.errors.
  E2EPrerequisiteError` before any subprocess is spawned), ``ready()``
  verifies the configured protocol endpoint and child identity.

Nothing here imports ``parrot.e2e.supervisor`` (M3) or any concrete target
module (``parrot.e2e.targets.mcp``/``botmanager``/``ui``/``browser``/
``redis``, M4's own later deliverables) — only the M2 schema surface
(:class:`parrot.e2e.models.TargetConfig`, :class:`parrot.e2e.models.RunState`)
that both sides already depend on. This resolves the M3/M4 cycle spec §3
calls out: the supervisor depends on this protocol, this protocol never
depends back on the supervisor or on any one adapter's implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from parrot.e2e.models import RunState, TargetConfig

__all__ = ["LaunchSpec", "TargetAdapter"]

_REDACTED = "***REDACTED***"


class LaunchSpec(BaseModel):
    """One validated, secret-safe child-process launch (spec §3 "M4").

    Always intended for direct ``argv`` execution (e.g.
    ``asyncio.create_subprocess_exec(*argv, ...)`` or
    ``subprocess.run(argv, shell=False, ...)``) — never a shell string, so
    no argument is ever subject to shell metacharacter expansion.

    Attributes:
        argv: The literal command and its arguments, in execution order.
            Never empty; every element is a nonempty string token — the
            structural shape a shell-less ``exec`` call requires (a single
            "space-joined command" string is rejected, since it would only
            make sense to a shell).
        env: Environment variables to set for the child process, merged by
            the caller over (or in place of) the parent environment. Never
            included verbatim in ``repr()``/``str()`` (so an accidental
            ``self.logger.info(str(spec))`` cannot leak a secret) nor in
            :meth:`model_dump`/:meth:`model_dump_json` — every value is
            replaced by a fixed redaction marker; only key names survive.
        cwd: Working directory the child process is started in.
        stdio: Whether the supervisor retains persistent stdio pipes to this
            child (spec §2 "Process Lifecycle": stdio targets are mediated
            through a private Unix control socket, never a raw pipe/PID
            file). ``False`` for targets that are only polled over HTTP.
    """

    model_config = ConfigDict(extra="forbid")

    argv: list[str]
    env: dict[str, str] = Field(default_factory=dict, repr=False)
    cwd: Path
    stdio: bool = False

    @field_validator("argv")
    @classmethod
    def _validate_argv(cls, value: list[str]) -> list[str]:
        """Reject anything that is not a nonempty list of nonempty tokens.

        Args:
            value: The candidate ``argv``.

        Returns:
            The validated ``argv``, unchanged.

        Raises:
            ValueError: If ``argv`` is empty, or any element is an empty
                string (a bare, unnamed executable makes no sense for a
                direct ``exec`` call).
        """
        if not value:
            raise ValueError("argv must be nonempty — a shell-less exec call needs at least one token")
        if any(not token for token in value):
            raise ValueError(f"argv must not contain empty tokens: {value!r}")
        return value

    @field_serializer("env")
    def _serialize_env(self, value: dict[str, str]) -> dict[str, str]:
        """Redact every environment value before serialization.

        Args:
            value: The raw ``env`` mapping.

        Returns:
            The same keys, every value replaced by a fixed redaction
            marker — applies to both :meth:`model_dump` and
            :meth:`model_dump_json` (Pydantic v2 field serializers run for
            both).
        """
        return dict.fromkeys(value, _REDACTED)

    def __repr__(self) -> str:
        """Redacted ``repr`` — never includes a raw environment value."""
        return (
            f"LaunchSpec(argv={self.argv!r}, env=<redacted:{len(self.env)} keys>, "
            f"cwd={self.cwd!r}, stdio={self.stdio!r})"
        )

    def __str__(self) -> str:
        """Same redacted form as :meth:`__repr__`, so ``self.logger`` calls stay safe."""
        return self.__repr__()


@runtime_checkable
class TargetAdapter(Protocol):
    """Target-specific launch, readiness and identity checks (spec §3 "M4").

    Every concrete adapter (``mcp-toolkit``/``mcp-stdio``/``mcp-agent``/
    ``botmanager``/``ui``/``browser``) implements this protocol; the M3
    supervisor only ever calls through it, never a concrete class directly.
    """

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return validated argv/env/cwd for this target; never spawns anything.

        Args:
            config: The target's own :class:`TargetConfig` (kind/profile/
                timeouts/options); ``options`` keys are validated by the
                concrete adapter, not by this protocol.
            run_id: The stable ID of the run this launch belongs to.
            worktree: The canonical worktree root the child must be started
                relative to (never an arbitrary filesystem path).

        Returns:
            A validated :class:`LaunchSpec`, ready for direct ``argv``
            execution (``shell=False``).

        Raises:
            parrot.e2e.errors.E2EPrerequisiteError: If a required external
                binary, installed extra or service is unavailable — raised
                before any subprocess is spawned.
            parrot.e2e.errors.E2EConfigError: If ``config.options`` contains
                an unsupported key/value for this target kind.
        """
        ...

    async def ready(self, state: RunState) -> bool:
        """Verify the configured protocol endpoint and child identity.

        Args:
            state: The current :class:`RunState` for the launched target,
                including its verified :class:`parrot.e2e.models.
                ProcessIdentity` and (once known) ``endpoint``.

        Returns:
            ``True`` once the target's own protocol readiness check (spec
            §2 "Target and Authentication Design" — HTTP polling,
            stdio handshake, etc.) succeeds; ``False`` while still starting.
        """
        ...
