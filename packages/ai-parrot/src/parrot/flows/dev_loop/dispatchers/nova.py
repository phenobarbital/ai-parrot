"""NovaCodeDispatcher — local coding-agent loop bound to bedrock-mantle.

The Nova dev seat is the only one of the three Nova seats (spec
``novaclient-dev-loop`` §2) that needs a tool loop, and the reason the
transport-split design works at all: AWS serves MiniMax M2.5 (and Kimi
K2.5/GLM-5) over the **OpenAI-compatible ``bedrock-mantle`` endpoint**
(``https://bedrock-mantle.{region}.api.aws/v1``), which is exactly the
shape :class:`~parrot.flows.dev_loop.dispatchers.llm.LLMCodeDispatcher`'s
loop already speaks.

This dispatcher does **NOT** drive the dev seat through :class:`NovaClient`/
Converse — ``BedrockConverseBase`` exposes no OpenAI-shaped
``_chat_completion``, so the base dispatcher's ``_chat_completion`` would
raise ``DispatchExecutionError("... does not expose chat completion")``
against it. Instead, the injected ``client_factory`` builds a
:class:`~parrot.clients.amazon.nova.mantle.BedrockMantleClient` pointed at the
bedrock-mantle base URL, reusing the inherited tool loop, Redis event
streaming, cwd-safety guard, and output validation unchanged.

FEAT-438 code-review fix: this used to construct a plain
:class:`~parrot.clients.openai.OpenAIClient` here instead of
``BedrockMantleClient``. Since ``OpenAIClient`` carries OpenAI-the-
provider's own ``gpt-*`` defaults (``_default_model``/``_fallback_model``/
``_lightweight_model``), a capacity-error fallback on this dispatcher's
client could have silently retried against a ``gpt-*`` model id on the
bedrock-mantle endpoint — the exact 404 class of bug FEAT-438 exists to
kill, just reached via direct instantiation instead of inheritance.
``BedrockMantleClient`` carries none of those defaults.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type, TYPE_CHECKING

from pydantic import BaseModel

from parrot import conf
from parrot.clients.factory import LLMFactory
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
)
from parrot.flows.dev_loop.dispatchers._shared import DispatchExecutionError, T
from parrot.flows.dev_loop.dispatchers.llm import LLMCodeDispatcher
from parrot.flows.dev_loop.models import (
    AdversarialFinding,
    CodeReviewFinding,
    CodeReviewVerdict,
    DispatchLabels,
    NovaAdversarialReviewProfile,
    NovaCodeDispatchProfile,
    NovaMechanicalProfile,
)
from parrot.flows.dev_loop.models.nova import effective_max_tokens
from parrot.flows.dev_loop.session_state import SessionHost

if TYPE_CHECKING:  # pragma: no cover - typing only
    # FEAT-523 (TASK-2846): type-check-only — core must not import a
    # provider module at module scope (AC-3); the real import is
    # deferred to the methods/functions that instantiate this client.
    from parrot.clients.amazon.nova import NovaClient


class NovaCodeDispatcher(LLMCodeDispatcher):
    """Local coding-agent loop bound to Bedrock via the bedrock-mantle endpoint.

    Extends ``LLMCodeDispatcher`` to reuse the inherited local tool loop,
    Redis event streaming, cwd-safety guard and output validation, while
    overriding the completion hooks so requests route through an
    OpenAI-compatible client pointed at
    ``https://bedrock-mantle.{region}.api.aws/v1`` instead of the default
    ``LLMFactory``-resolved client (which would resolve ``"nova:"`` to
    :class:`~parrot.clients.amazon.nova.client.NovaClient`, a Converse-only client
    with no chat-completion shape).
    """

    def __init__(
        self,
        *,
        max_concurrent: int,
        redis_url: str,
        stream_ttl_seconds: int,
    ) -> None:
        super().__init__(
            max_concurrent=max_concurrent,
            redis_url=redis_url,
            stream_ttl_seconds=stream_ttl_seconds,
            client_factory=self._create_mantle_client,
        )

    def _create_mantle_client(
        self,
        llm: str,
        *,
        model_args: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Any:
        """``client_factory`` hook — builds an OpenAI-compatible client bound
        to the bedrock-mantle endpoint instead of routing through
        ``LLMFactory``/``NovaClient``.

        Args:
            llm: The profile's ``llm`` string, e.g.
                ``"nova:minimax.minimax-m2.5"``.
            model_args: Optional dict with ``temperature``/``max_tokens``
                (matches the shape ``LLMCodeDispatcher._create_client``
                passes to the default ``LLMFactory.create`` factory).
            **kwargs: Forwarded to :class:`BedrockMantleClient`.

        Returns:
            A :class:`BedrockMantleClient` instance targeting bedrock-mantle.
            Deliberately NOT ``OpenAIClient`` — see the module docstring's
            FEAT-438 code-review-fix note; ``BedrockMantleClient`` carries no
            ``gpt-*`` model defaults, so a capacity-error fallback here can
            never retry against an OpenAI model id on this non-OpenAI
            endpoint.

        Raises:
            DispatchExecutionError: When the mantle base URL or the Bedrock
                API key cannot be resolved — names the missing config key.
        """
        # FEAT-523 (TASK-2846): lazy import — core must not import a
        # provider module at module scope (AC-3).
        from parrot.clients.amazon.nova.mantle import BedrockMantleClient

        _provider, model = LLMFactory.parse_llm_string(llm)
        init_params: Dict[str, Any] = {}
        if model:
            init_params["model"] = model
        if model_args:
            for key in ("temperature", "max_tokens"):
                value = model_args.get(key)
                if value is not None:
                    init_params[key] = value
        init_params.update(kwargs)
        return BedrockMantleClient(
            api_key=self._resolve_bedrock_api_key(),
            base_url=self._resolve_mantle_base_url(),
            **init_params,
        )

    @staticmethod
    def _resolve_bedrock_api_key() -> str:
        """Resolve the bedrock-mantle bearer token.

        Reuses ``conf.AWS_NOVA_API_KEY`` — the same Bedrock API key
        ``BedrockConverseBase`` uses for the Converse seats — rather than a
        duplicate secret.
        """
        api_key = conf.AWS_NOVA_API_KEY
        if not api_key:
            raise DispatchExecutionError(
                "AWS_NOVA_API_KEY is required for the nova dev seat "
                "(bedrock-mantle bearer token); set it in the environment "
                "or navconfig settings."
            )
        return api_key

    @staticmethod
    def _resolve_mantle_base_url() -> str:
        """Resolve the bedrock-mantle base URL from config."""
        base_url = conf.DEV_LOOP_NOVA_MANTLE_BASE_URL
        if base_url:
            return base_url
        region = conf.DEV_LOOP_NOVA_MANTLE_REGION
        if not region:
            raise DispatchExecutionError(
                "DEV_LOOP_NOVA_MANTLE_BASE_URL or DEV_LOOP_NOVA_MANTLE_REGION "
                "is required to resolve the bedrock-mantle endpoint for the "
                "nova dev seat."
            )
        return f"https://bedrock-mantle.{region}.api.aws/v1"

    def _completion_args(
        self,
        profile: NovaCodeDispatchProfile,
        tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build MiniMax/Kimi/GLM-appropriate completion args.

        Never emits ``extra_body``/``chat_template_kwargs`` — an Nvidia-only
        concept the base class's ``_completion_args`` also emits, but which
        the bedrock-mantle models do not use. Applies the per-model output
        clamp (TASK-2085's :func:`effective_max_tokens`) to the effective
        ``max_tokens``.
        """
        _provider, model = LLMFactory.parse_llm_string(profile.llm)
        args: Dict[str, Any] = {
            "tools": tools,
            "tool_choice": "auto",
            # Read from the profile (default True): one turn per tool call
            # is what made whole tasks die against `max_turns`.
            "parallel_tool_calls": getattr(profile, "parallel_tool_calls", True),
            "max_tokens": effective_max_tokens(model or profile.model, profile.max_tokens, self.logger),
        }
        if profile.temperature is not None:
            args["temperature"] = profile.temperature
        return args

    async def _chat_completion(
        self,
        *,
        client: Any,
        model: str,
        messages: List[Dict[str, Any]],
        args: Dict[str, Any],
    ) -> Any:
        """Route through the client's OpenAI-shaped ``_chat_completion``.

        No request-shape change is needed beyond the base implementation —
        the routing to bedrock-mantle happens at client construction
        (``_create_mantle_client``), not at call time. Overridden (rather
        than left purely inherited) to keep the two-hook override shape
        explicit and documented, mirroring
        ``MoonshotCodeDispatcher``/``ZaiCodeDispatcher``.
        """
        return await super()._chat_completion(
            client=client,
            model=model,
            messages=messages,
            args=args,
        )

    async def dispatch(
        self,
        *,
        brief: BaseModel,
        profile: NovaCodeDispatchProfile,
        output_model: Type[T],
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        labels: Optional[DispatchLabels] = None,
    ) -> T:
        return await super().dispatch(
            brief=brief,
            profile=profile,
            output_model=output_model,
            run_id=run_id,
            node_id=node_id,
            cwd=cwd,
            session_host=session_host,
            labels=labels,
        )


@CodeReviewDispatcherFactory.register("nova-adversarial")
class NovaAdversarialReviewDispatcher(AbstractCodeReviewDispatcher):
    """Read-only adversarial second-opinion reviewer on a Bedrock Converse model.

    Defaults to Amazon's own ``us.amazon.nova-2-lite-v1:0`` (see
    ``NOVA_DEFAULT_CONVERSE_MODEL``) rather than a ``us.anthropic.*`` id,
    which Bedrock gates behind a per-account Anthropic use-case form;
    override with ``DEV_LOOP_NOVA_REVIEW_MODEL``.

    Read-only BY CONSTRUCTION: no tools are ever passed to the model. The
    diff, acceptance criteria and review question go directly in the
    prompt; the model returns the verdict as structured output over a
    single :meth:`NovaClient.ask` call (Converse — neither Nova nor
    Anthropic models on Bedrock expose Chat Completions, so unlike the dev
    seat this reviewer does NOT use bedrock-mantle). Findings are advisory
    and must be triaged
    (CONFIRM/REJECT/ESCALATE) by the primary worker downstream, mirroring
    ``CodexAdversarialReviewDispatcher`` (``code_review.py:266-337``).

    Unlike every other review dispatcher, there is no underlying
    ``DevLoopCodeDispatcher`` to delegate to — :meth:`review` drives
    ``NovaClient.ask()`` directly and reproduces
    ``AbstractCodeReviewDispatcher.review()``'s degrade-on-infra-error
    contract locally (an outage degrades to a *passing* verdict with a
    nit-level finding — a known, intentionally inherited property, not a
    bug).
    """

    agent_name = "nova-adversarial"
    advisory = True

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        review_scope: str = "uncommitted",
        review_base: str = "",
        review_commit: str = "",
        max_diff_chars: Optional[int] = None,
        client: Optional[NovaClient] = None,
    ) -> None:
        self._model = model or conf.DEV_LOOP_NOVA_REVIEW_MODEL
        self._review_scope = review_scope
        self._review_base = review_base
        self._review_commit = review_commit
        self._max_diff_chars = max_diff_chars
        # FEAT-523 (TASK-2846): lazy import — core must not import a
        # provider module at module scope (AC-3).
        from parrot.clients.amazon.nova import NovaClient

        self._client = client or NovaClient()
        self.logger = logging.getLogger(__name__)

    def build_review_profile(self) -> NovaAdversarialReviewProfile:
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "review_scope": self._review_scope,
            "review_base": self._review_base,
            "review_commit": self._review_commit,
        }
        if self._max_diff_chars is not None:
            kwargs["max_diff_chars"] = self._max_diff_chars
        return NovaAdversarialReviewProfile(**kwargs)

    async def review(
        self,
        *,
        brief: BaseModel,
        run_id: str,
        node_id: str,
        cwd: str,
        session_host: Optional[SessionHost] = None,
        round: str = "",
        labels: Optional[DispatchLabels] = None,
    ) -> CodeReviewVerdict:
        """Run the advisory review directly against ``NovaClient.ask()``.

        No tools are passed (``use_tools=False`` explicit, no ``tools``
        kwarg). Any exception — diff collection, the Bedrock call itself,
        or a structured-output parse failure — degrades to a passing
        verdict with a nit-level finding, reproducing
        ``AbstractCodeReviewDispatcher.review()``'s contract (this class
        cannot call ``super().review()`` — there is no underlying
        dispatcher to delegate to).

        Args:
            labels: FEAT-496 — accepted for protocol parity with the ABC's
                now-updated signature (code-review finding: this seat has
                no dispatch payload/usage-attribution seat to fold a
                `judge_id` into, unlike `MantleAdversarialReviewDispatcher`,
                so it is unused beyond satisfying the contract).
        """
        try:
            profile = self.build_review_profile()
            diff_text = await self._collect_diff(cwd, profile)
            prompt = self._build_prompt(brief, diff_text)
            ai_message = await self._client.ask(
                prompt,
                model=profile.model,
                max_tokens=profile.max_tokens,
                use_tools=False,
                structured_output=CodeReviewVerdict,
            )
            verdict = ai_message.structured_output
            if not isinstance(verdict, CodeReviewVerdict):
                raise ValueError(
                    "nova-adversarial reviewer did not return a valid "
                    f"CodeReviewVerdict (got {type(verdict).__name__})"
                )
        except Exception as exc:  # noqa: BLE001 - degrade-on-infra-error, mirrors code_review.py:145-157
            self.logger.warning("%s code-review dispatch failed: %s", self.agent_name, exc)
            return CodeReviewVerdict(
                passed=True,
                findings=[
                    CodeReviewFinding(
                        message=f"code-review could not run: {exc}",
                        severity="nit",
                    )
                ],
            )

        tagged_findings = [
            (
                finding
                if isinstance(finding, AdversarialFinding)
                else AdversarialFinding(**finding.model_dump(), source=self.agent_name)
            )
            for finding in verdict.findings
        ]
        return verdict.model_copy(update={"files_modified": [], "findings": tagged_findings})

    async def _collect_diff(self, cwd: str, profile: NovaAdversarialReviewProfile) -> str:
        """Compute the review diff for ``profile.review_scope``, truncated
        deterministically at ``profile.max_diff_chars``.
        """
        if profile.review_scope == "commit":
            argv = ["git", "show", "--patch", "--no-color", profile.review_commit]
        elif profile.review_scope == "base":
            argv = ["git", "diff", "--no-color", f"{profile.review_base}...HEAD"]
        else:  # "uncommitted" (default)
            argv = ["git", "diff", "--no-color", "HEAD"]

        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await process.communicate()
        if process.returncode != 0:
            raise DispatchExecutionError(
                f"git diff failed (exit {process.returncode}): " f"{stderr_b.decode('utf-8', errors='replace')[:2000]}"
            )
        diff_text = stdout_b.decode("utf-8", errors="replace")
        return self._truncate_diff(diff_text, profile.max_diff_chars)

    @staticmethod
    def _truncate_diff(diff_text: str, max_diff_chars: int) -> str:
        """Deterministically truncate ``diff_text``, never silently."""
        if len(diff_text) <= max_diff_chars:
            return diff_text
        return diff_text[:max_diff_chars] + f"\n\n[... diff truncated at {max_diff_chars} characters ...]"

    @staticmethod
    def _build_prompt(brief: BaseModel, diff_text: str) -> str:
        return (
            "You are an adversarial code reviewer. Review the diff below "
            "against the acceptance criteria in the brief. Report every "
            "genuine issue as a finding. You have NO tools and cannot "
            "modify any files — this is a read-only review.\n\n"
            f"Brief:\n{brief.model_dump_json()}\n\n"
            f"Diff:\n{diff_text}\n\n"
            "Return your verdict as the requested structured output."
        )


# ---------------------------------------------------------------------------
# Mechanical seat (FEAT-405 Module 8) — PR-body enrichment.
#
# NOT a third dispatcher: a small, stateless helper the handoff nodes call
# directly. "Enrich, never replace" ([R2]): the deterministic template
# stays the skeleton *and* the fallback; this contributes only a short
# "Summary of changes" section, and NEVER raises — any failure, timeout, or
# absent config must fall back silently to the template alone.
# ---------------------------------------------------------------------------


def _has_nova_credentials() -> bool:
    """Best-effort, local, synchronous check for a Nova/Bedrock opt-in.

    Deliberately conservative: recognizes only the ``AWS_NOVA_API_KEY``
    bearer token, a credential this feature itself introduces and that is
    never consumed for any purpose other than Nova/Bedrock. It does NOT
    treat the conf-wide ``AWS_ACCESS_KEY``/``AWS_SECRET_KEY`` keypair as
    sufficient, and it does NOT probe the full boto3 SDK credential chain
    (shared credentials file, SSO, instance role) — that cannot be checked
    without attempting a real call.

    This mirrors a precedent already established in
    ``BedrockConverseBase.__init__`` (``clients/bedrock.py``, "Code-review
    fix (post-FEAT-315)"): falling back to the generic, multi-purpose
    ``AWS_ACCESS_KEY``/``AWS_SECRET_KEY`` conf values made unrelated
    features (e.g. the existing Bedrock-hosted Claude client, S3 access)
    silently opt a deployment into new Bedrock traffic it never asked for.
    A deployment that wants mechanical-seat enrichment via the SigV4
    keypair path must configure a named ``aws_id`` credentials profile
    explicitly (or set ``AWS_NOVA_API_KEY``, even a placeholder its own
    IAM policy still honours) — otherwise this degrades to the
    deterministic template every time, which is the correct,
    byte-identical, pre-FEAT-405 fallback ([R3]: "a run that configures no
    Nova settings behaves identically to pre-feature").

    Returns:
        ``True`` when a real network attempt looks worthwhile.
    """
    return bool(conf.AWS_NOVA_API_KEY)


#: Bedrock error codes that are *permanent* for the configured model —
#: retrying the same call on the next PR will fail identically until an
#: operator changes AWS-side state (model access / use-case form / region
#: availability) or points the seat at a different model. Logged as a
#: single actionable line instead of a stack trace, because the fallback
#: to the deterministic template is the designed behaviour, not an
#: incident.
_NON_RETRYABLE_BEDROCK_CODES = frozenset(
    {
        "ResourceNotFoundException",
        "AccessDeniedException",
        "ValidationException",
        "UnrecognizedClientException",
    }
)


def _bedrock_error_code(error: Exception) -> Optional[str]:
    """Return the Bedrock/botocore error code for ``error``, if any.

    Recognises both a real ``botocore.exceptions.ClientError`` (via its
    ``response["Error"]["Code"]`` shape) and the dynamically generated
    ``client.exceptions.*`` classes, which are matched by class name
    since they are not import-stable across botocore versions — the same
    two-pronged detection ``BedrockConverseBase._is_capacity_error()``
    uses.

    Args:
        error: The exception raised by the Converse call.

    Returns:
        The error code string, or ``None`` when the exception carries no
        recognizable botocore error shape.
    """
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    name = type(error).__name__
    return name if name.endswith("Exception") else None


async def summarize_pr_changes(
    context: str,
    *,
    profile: Optional[NovaMechanicalProfile] = None,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Return a short "Summary of changes" markdown block, or ``""`` on any failure.

    Issues exactly one no-tools ``NovaClient.ask()`` call on the model
    resolved from ``DEV_LOOP_NOVA_MECHANICAL_MODEL`` (default:
    ``us.amazon.nova-2-lite-v1:0``). Never raises — the caller (``_build_body_async`` on the handoff
    nodes) falls back to the deterministic template alone when this
    returns an empty string. Short-circuits (no network attempt at all)
    when no Nova/Bedrock credential is configured (code-review fix: a
    fully unconfigured deployment must not pay a real connection/DNS
    attempt — up to ``timeout_seconds`` — on every single PR; see
    :func:`_has_nova_credentials`).

    Args:
        context: The deterministic PR body text already assembled by the
            node's own ``_build_body`` (files changed, QA evidence,
            synthesis) — the mechanical seat summarizes already-known
            structured facts into prose; it is not given raw git access.
        profile: The mechanical-seat profile (model, ``max_tokens``,
            ``timeout_seconds``). Defaults to
            :class:`NovaMechanicalProfile`'s own defaults when omitted.
        logger: Logger used to warn on failure. Defaults to this module's
            logger.

    Returns:
        The summary text (no heading — the caller supplies
        ``## Summary of changes``), or ``""`` on any exception, timeout,
        missing credentials, or empty model response.
    """
    # FEAT-523 (TASK-2846): lazy import — core must not import a
    # provider module at module scope (AC-3).
    from parrot.clients.amazon.nova import NovaClient

    log = logger or logging.getLogger(__name__)
    # code-review fix: DEV_LOOP_NOVA_MECHANICAL_MODEL was declared in
    # conf.py but never actually consumed anywhere — wire it into the
    # default profile here (an explicit `profile=` still wins, matching
    # every other config-vs-explicit-override precedent in this feature).
    resolved_profile = profile or NovaMechanicalProfile(model=conf.DEV_LOOP_NOVA_MECHANICAL_MODEL)
    if not _has_nova_credentials():
        log.debug("PR summary enrichment skipped — no Nova/Bedrock opt-in " "configured (AWS_NOVA_API_KEY).")
        return ""
    # NOTE: construction stays *inside* the try — ``NovaClient()`` itself
    # can raise (bad/absent credentials), and this helper must never raise.
    client: Optional[NovaClient] = None
    try:
        client = NovaClient()
        async with asyncio.timeout(resolved_profile.timeout_seconds):
            ai_message = await client.ask(
                "Summarize the following pull-request description in 2-4 "
                "concise bullet points highlighting what changed. Output "
                "markdown bullets only — no heading, no preamble, no "
                "code fences.\n\n"
                f"{context}",
                model=resolved_profile.model,
                max_tokens=resolved_profile.max_tokens,
                use_tools=False,
            )
        summary = str(ai_message.output or "").strip()
        return summary
    except Exception as exc:  # noqa: BLE001 - enrichment must never break handoff
        code = _bedrock_error_code(exc)
        if code in _NON_RETRYABLE_BEDROCK_CODES:
            # Permanent, operator-actionable AWS-side condition (model not
            # enabled for the account/region, Anthropic use-case form not
            # submitted, bad model id). A stack trace on every single PR is
            # pure noise — name the model and the remedy on one line instead.
            log.warning(
                "PR summary enrichment unavailable for model %r (%s: %s); "
                "using template only. Enable the model for this account/"
                "region in the Bedrock console, or point "
                "DEV_LOOP_NOVA_MECHANICAL_MODEL at a model this account can "
                "call (e.g. an Amazon Nova id).",
                resolved_profile.model,
                code,
                exc,
            )
        else:
            log.warning(
                "PR summary enrichment failed; using template only.",
                exc_info=True,
            )
        return ""
    finally:
        # The per-call client owns an aioboto3/aiohttp session+connector
        # opened lazily by BedrockConverseBase.get_client(); without this
        # every PR leaked one ("Unclosed client session" / "Unclosed
        # connector" at interpreter shutdown).
        if client is not None and hasattr(client, "close"):
            try:
                await client.close()
            except Exception as close_exc:  # noqa: BLE001 - teardown is best-effort
                log.debug("Failed to close Nova mechanical client: %s", close_exc)
