"""``ComplementaryResearchCoordinator`` — the shared research seam (FEAT-482 Module 4).

The single seam both ``IdeationNode`` (dev_flow) and ``ResearchNode``
(dev_loop) call to fan a complementary research partner out alongside
their own primary Claude dispatch. This is the feature's **soft-
degradation boundary**: its contract is narrow and absolute — it returns
``Optional[ComplementaryFindings]`` and **never raises into a caller**.
Every failure (disabled, timeout, credential error, Bedrock outage,
structured-output parse failure, empty/trivial output, artifact
write/commit failure) becomes ``None`` (or ``document_path=""`` for the
write/commit case alone) plus a warning log and a ``partner.degraded``
event — never an exception.

Mirrors the best-effort contract of
``parrot.flows.dev_loop.wiki_search.DevLoopWikiSearch.build_research_context``
(``wiki_search.py:91``): "returns None on ANY internal error, never
raises." The composition shape (fan a second seat out, merge) mirrors
``ParallelPerspectiveReviewDispatcher`` (``code_review.py:341``), though
this coordinator wraps a single partner call under a deadline rather than
an ``asyncio.gather`` of two review seats.

**Concurrency note**: the primary Claude dispatch itself needs the
partner's findings as *input* (they ride in the first dispatch's payload),
so it can never run concurrently with ``coordinator.research()`` — that
would be a race, not a fan-out. What each calling node DOES run this
coordinator concurrently with is its own other best-effort context-
gathering work (wiki search, graph memory) via ``asyncio.gather``, since
this coordinator's own deadline (``DEV_FLOW_RESEARCH_PARTNER_TIMEOUT``,
default 600s) can dominate those calls' latency if awaited sequentially
after them. See ``IdeationNode.execute()`` and ``ResearchNode.execute()``
for the two call sites.

See ``sdd/specs/devflow-complementary-research.spec.md`` §3 Module 4.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from parrot import conf
from parrot.flows.dev_flow.research_partner import (
    ComplementaryFindings,
    ResearchFindings,
    ResearchPartnerFactory,
    resolve_backend_model,
)
from parrot.flows.dev_loop.catalog import (
    resolve_research_partner_backend,
    validate_research_partner_model,
)
from parrot.flows.dev_loop.session_state import SessionHost

#: Character bound for `ComplementaryFindings.rendered` — the copy that
#: rides in the calling node's dispatch payload. The full, untruncated
#: markdown always goes to `sdd/proposals/<slug>.research.md`; only the
#: payload copy is bounded (spec §7 "Findings too large for the dispatch
#: payload"). No dedicated conf key exists for this — it is a local,
#: conservative default in the same order of magnitude as
#: `ReadOnlyRepoToolkit`'s own `search_budget_tokens=4_000` default.
_MAX_RENDERED_CHARS = 4_000

_TRUNCATION_MARKER = "\n\n... [truncated for dispatch payload; full text in the .research.md file] ...\n"

#: FEAT-486: valid values for an EXPLICIT ``backend=`` override. Kept equal
#: to ``catalog._RESEARCH_PARTNER_CHOICES`` without importing a private
#: name across modules; ``test_partner_passthrough.py`` pins the two equal.
_EXPLICIT_BACKEND_CHOICES: tuple[str, ...] = ("gpt", "nova")


class ComplementaryResearchCoordinator:
    """Shared research seam for `IdeationNode` and `ResearchNode` (FEAT-482).

    Resolves the configured research-partner backend, runs it under a
    deadline, renders + commits `sdd/proposals/<slug>.research.md` on
    success, and returns `ComplementaryFindings` — or `None` on ANY
    failure, including when the seat is disabled. Never raises.
    """

    def __init__(self, *, backend: str | None = None, model: str | None = None) -> None:
        """Initialize the coordinator.

        Args:
            backend: FEAT-486 — an explicit ``"gpt"``/``"nova"`` selection
                that bypasses the ``DEV_FLOW_RESEARCH_PARTNER`` config
                lookup in :meth:`research`. ``None`` (default) keeps the
                original conf-driven path byte-identical, INCLUDING the
                "unset ⇒ disabled" pure-addition guarantee.
            model: FEAT-486 — an explicit model id for the partner,
                forwarded to the constructed partner and used to stamp
                ``ComplementaryFindings.model``. ``None`` (default)
                resolves the per-backend conf key as before.

        Note:
            These exist so a caller holding its own configuration — a
            ``DevFlowModelPlan``'s ``research_partner`` group (FEAT-486
            TASK-2657) — can select this seat without an env var. Without
            them a plan-enabled partner would still resolve
            ``DEV_FLOW_RESEARCH_PARTNER`` (default ``""``) and silently
            return ``None``, i.e. an enable toggle that cannot enable.
            An explicit ``backend`` is validated in :meth:`research` just
            like a configured one, and an explicit ``model`` is validated
            by the partner's own family guard.
        """
        self.logger = logging.getLogger(__name__)
        self._backend = backend
        self._model = model

    async def research(
        self,
        *,
        brief: BaseModel,
        question: str,
        cwd: str,
        slug: str,
        run_id: str,
        node_id: str,
        session_host: SessionHost | None = None,
    ) -> ComplementaryFindings | None:
        """Run the complementary research partner, or degrade to `None`.

        Args:
            brief: The originating dev-flow/dev-loop brief, forwarded to
                the partner unchanged (never the primary seat's framing).
            question: The research question posed to the partner.
            cwd: The repo checkout — both the partner's read-only root and
                where `sdd/proposals/<slug>.research.md` is written/committed.
            slug: The feature/request slug; names the artifact file.
            run_id: The flow run id, logged for correlation only.
            node_id: The flow node id, logged for correlation only.
            session_host: The run's `SessionHost`, if any — forwarded to
                the partner, otherwise unused by this coordinator.

        Returns:
            `ComplementaryFindings` on success, or `None` when the seat is
            disabled, times out, fails, returns empty/trivial output, or
            any other error occurs. NEVER raises.
        """
        start = time.perf_counter()
        try:
            backend = self._resolve_backend()
            if not backend:
                # Disabled: no client built, no work performed — the
                # pure-addition guarantee, not a degradation.
                return None

            self._emit(
                "partner.started",
                backend=backend,
                run_id=run_id,
                node_id=node_id,
                slug=slug,
            )

            partner = ResearchPartnerFactory.create(backend, backend=backend, model=self._model)
            timeout = conf.DEV_FLOW_RESEARCH_PARTNER_TIMEOUT
            async with asyncio.timeout(timeout):
                findings = await partner.research(
                    brief=brief,
                    question=question,
                    cwd=cwd,
                    run_id=run_id,
                    node_id=node_id,
                    session_host=session_host,
                )

            if self._is_trivial(findings):
                self.logger.info(
                    "Complementary research (%s) returned trivial/empty "
                    "findings; treating as absent (run_id=%s node_id=%s)",
                    backend,
                    run_id,
                    node_id,
                )
                return None

            model = self._model or self._resolve_model_for_backend(backend)
            full_markdown = self._render_markdown(findings=findings, backend=backend, model=model, slug=slug)
            document_path = await self._write_and_commit(cwd=cwd, slug=slug, rendered=full_markdown)
            rendered = self._truncate_for_dispatch(full_markdown)
            duration_ms = (time.perf_counter() - start) * 1000

            self._emit(
                "partner.completed",
                backend=backend,
                run_id=run_id,
                node_id=node_id,
                slug=slug,
                document_path=document_path,
                duration_ms=duration_ms,
            )

            return ComplementaryFindings(
                backend=backend,
                model=model,
                findings=findings,
                document_path=document_path,
                rendered=rendered,
                duration_ms=duration_ms,
                degraded=False,
            )
        except Exception as exc:  # noqa: BLE001 — this IS the degradation boundary
            duration_ms = (time.perf_counter() - start) * 1000
            self.logger.warning(
                "Complementary research degraded (run_id=%s node_id=%s " "slug=%s): %s",
                run_id,
                node_id,
                slug,
                exc,
            )
            self._emit(
                "partner.degraded",
                run_id=run_id,
                node_id=node_id,
                slug=slug,
                reason=str(exc),
                duration_ms=duration_ms,
            )
            return None

    def _emit(self, event: str, **fields: Any) -> None:
        """Best-effort structured log for a partner lifecycle event.

        FEAT-482 emits `partner.started` / `partner.completed` /
        `partner.degraded` as log events only — no telemetry rendering.
        `usage_report.py` / `run_bundle.py` are untouched; FEAT-479 owns
        rendering and can pick these up from the log stream when it lands
        (spec §1 Non-Goals, §5).
        """
        self.logger.info("%s %s", event, fields)

    @staticmethod
    def _is_trivial(findings: ResearchFindings) -> bool:
        """True when `findings` carries no usable content.

        No individual findings AND no summary text means the partner
        effectively found nothing — treated as absent (no file written,
        no empty section in any merged document), not as a degradation.
        """
        return not findings.findings and not findings.summary.strip()

    def _resolve_backend(self) -> str:
        """Resolve the effective backend: explicit override > config.

        FEAT-486: an explicit ``backend`` passed to ``__init__`` is
        validated through the SAME two gates the config path uses — the
        ``("gpt", "nova")`` choice set and the Anthropic family guard on
        the resolved model — so injection is not a way around either.
        Raising here is safe and intended: ``research()`` wraps this call
        in its degradation boundary, so a misconfigured override degrades
        the seat (logged, ``partner.degraded``) instead of failing the run.

        Returns:
            ``""`` (disabled), ``"gpt"`` or ``"nova"``.

        Raises:
            ValueError: If an explicit backend is not ``"gpt"``/``"nova"``,
                or its effective model is an Anthropic model id.
        """
        if self._backend is None:
            return resolve_research_partner_backend()
        backend = self._backend
        if backend not in _EXPLICIT_BACKEND_CHOICES:
            raise ValueError(
                f"Invalid research-partner backend {backend!r}; must be one "
                f"of {_EXPLICIT_BACKEND_CHOICES} (gpt, nova). Pass backend="
                "None to fall back to DEV_FLOW_RESEARCH_PARTNER."
            )
        validate_research_partner_model(self._model or resolve_backend_model(backend))
        return backend

    @staticmethod
    def _resolve_model_for_backend(backend: str) -> str:
        """Return the model id the partner used for `backend`.

        Delegates to the shared :func:`resolve_backend_model` (also used
        by `BedrockResearchPartner._build_client()`) rather than
        duplicating the two-branch mapping here — code-review follow-up
        (the two copies had been kept in sync by hand until now).
        """
        return resolve_backend_model(backend)

    @staticmethod
    def _render_markdown(*, findings: ResearchFindings, backend: str, model: str, slug: str) -> str:
        """Render `findings` as the full `.research.md` markdown body.

        Args:
            findings: The partner's validated findings.
            backend: ``"gpt"`` or ``"nova"``.
            model: The resolved model id.
            slug: The feature/request slug, for the title.

        Returns:
            Complete markdown text (untruncated).
        """
        lines: list[str] = [
            f"# Complementary Research — {slug}",
            "",
            f"**Backend**: {backend} (`{model}`)",
            "",
            "## Summary",
            "",
            findings.summary,
            "",
        ]
        if findings.findings:
            lines.append("## Findings")
            lines.append("")
            for finding in findings.findings:
                lines.append(f"### {finding.id} — {finding.title} " f"(confidence: {finding.confidence})")
                lines.append("")
                lines.append(finding.detail)
                if finding.evidence:
                    lines.append("")
                    lines.append("Evidence:")
                    lines.extend(f"- {item}" for item in finding.evidence)
                lines.append("")
        if findings.options_considered:
            lines.append("## Options Considered")
            lines.append("")
            lines.extend(f"- {item}" for item in findings.options_considered)
            lines.append("")
        if findings.could_not_determine:
            lines.append("## Could Not Determine")
            lines.append("")
            lines.extend(f"- {item}" for item in findings.could_not_determine)
            lines.append("")
        if findings.sources_examined:
            lines.append("## Sources Examined")
            lines.append("")
            lines.extend(f"- {item}" for item in findings.sources_examined)
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _truncate_for_dispatch(rendered: str) -> str:
        """Bound `rendered` for the dispatch payload, marker on truncation."""
        if len(rendered) <= _MAX_RENDERED_CHARS:
            return rendered
        return rendered[:_MAX_RENDERED_CHARS] + _TRUNCATION_MARKER

    async def _write_and_commit(self, *, cwd: str, slug: str, rendered: str) -> str:
        """Write + commit `sdd/proposals/<slug>.research.md`, that path only.

        A write or `git` failure must NOT lose the findings — the caller
        already holds the in-memory `ResearchFindings`; this method's
        only job is to report `""` and let `research()` warn and continue
        with `document_path=""` (spec §7 Known Risks).

        Args:
            cwd: The repo root to write and commit into.
            slug: Names the artifact: `sdd/proposals/<slug>.research.md`.
            rendered: The full, untruncated markdown body.

        Returns:
            The repo-relative document path on success, or `""` on ANY
            failure.
        """
        repo_root = Path(cwd)
        rel_path = f"sdd/proposals/{slug}.research.md"
        try:
            target = repo_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_text, rendered, encoding="utf-8")
            await self._run_git(repo_root, "add", "--", rel_path)
            await self._run_git(
                repo_root,
                "commit",
                "-m",
                f"sdd: add complementary research for {slug}",
                "--",
                rel_path,
            )
            return rel_path
        except Exception as exc:  # noqa: BLE001 — write/commit must not lose findings
            self.logger.warning("Failed to write/commit %s: %s", rel_path, exc)
            return ""

    @staticmethod
    async def _run_git(repo_root: Path, *args: str) -> None:
        """Run one `git` subcommand in `repo_root`; raise on non-zero exit.

        Never uses a shell; never stages more than the explicit paths
        passed in `args` (SDD auto-commit rule — no `git add -A` / `git
        add .`, ever).

        Raises:
            RuntimeError: If the `git` process exits non-zero.
        """
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (exit {proc.returncode}): "
                f"{stderr.decode('utf-8', errors='replace')[:500]}"
            )


__all__ = ["ComplementaryResearchCoordinator"]
