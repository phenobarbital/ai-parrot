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
an ``asyncio.gather`` of two review seats — the concurrent-with-the-
primary-seat composition happens one layer up, in the calling node
(``asyncio.gather(primary_dispatch, coordinator.research(...))``), not
inside this class.

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
)
from parrot.flows.dev_loop.catalog import resolve_research_partner_backend
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


class ComplementaryResearchCoordinator:
    """Shared research seam for `IdeationNode` and `ResearchNode` (FEAT-482).

    Resolves the configured research-partner backend, runs it under a
    deadline, renders + commits `sdd/proposals/<slug>.research.md` on
    success, and returns `ComplementaryFindings` — or `None` on ANY
    failure, including when the seat is disabled. Never raises.
    """

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

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
            backend = resolve_research_partner_backend()
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

            partner = ResearchPartnerFactory.create(backend, backend=backend)
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

            model = self._resolve_model_for_backend(backend)
            full_markdown = self._render_markdown(
                findings=findings, backend=backend, model=model, slug=slug
            )
            document_path = await self._write_and_commit(
                cwd=cwd, slug=slug, rendered=full_markdown
            )
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
                "Complementary research degraded (run_id=%s node_id=%s "
                "slug=%s): %s",
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

    @staticmethod
    def _resolve_model_for_backend(backend: str) -> str:
        """Return the model id the partner used for `backend`.

        Mirrors `BedrockResearchPartner._build_client()`'s model
        resolution (`research_partner.py`, TASK-2631) — duplicated
        deliberately rather than reading a private attribute off the
        partner instance, since both read the same two conf keys and stay
        trivially easy to keep in sync.
        """
        if backend == "gpt":
            return conf.DEV_FLOW_RESEARCH_PARTNER_GPT_MODEL
        return conf.DEV_FLOW_RESEARCH_PARTNER_NOVA_MODEL

    @staticmethod
    def _render_markdown(
        *, findings: ResearchFindings, backend: str, model: str, slug: str
    ) -> str:
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
                lines.append(
                    f"### {finding.id} — {finding.title} "
                    f"(confidence: {finding.confidence})"
                )
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
            self.logger.warning(
                "Failed to write/commit %s: %s", rel_path, exc
            )
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
