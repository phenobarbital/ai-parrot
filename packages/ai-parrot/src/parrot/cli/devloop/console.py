"""Console engine — session, slash commands, gates for ``parrot devloop``.

``DevLoopConsole`` orchestrates: wizard → dispatch → Rich Live rendering →
interactive gate resolution → slash commands. Modal terminal discipline:
one writer at a time (pause/resume Live around prompts).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from parrot.cli.devloop.renderer import RunView

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a heavy runtime import
    from parrot.cli.devloop.intake import FeatureDraft
    from parrot.flows.dev_loop.catalog import BackendInfo
    from parrot.flows.dev_loop.models import DevAgentSpec, JudgePanelConfig

logger = logging.getLogger(__name__)

_GATE_POLL_INTERVAL = 0.25  # seconds
_KIND_CHOICES: tuple[str, ...] = ("bug", "enhancement", "feature")

#: Backends ``JudgeSpec`` actually accepts. Duplicated (not imported) from
#: ``models.base.JudgeBackend`` because this module keeps
#: ``parrot.flows.dev_loop.models`` behind ``TYPE_CHECKING`` to avoid a
#: heavy runtime import; the two are pinned equal by test — the same
#: idiom ``conf.py`` uses for ``DEV_LOOP_MANTLE_REVIEW_MODEL``.
#:
#: The previous value drifted from the model and offered rows
#: (``google_coding``, then ``gemini``) that ``JudgeSpec`` rejects with a
#: ``pydantic.ValidationError``; the pinning test exists so that cannot
#: recur silently.
_JUDGE_REVIEW_CAPABLE_BACKENDS: tuple[str, ...] = ("claude-code", "codex", "mantle")


class DevLoopConsole:
    """Interactive console session for dev-loop flows."""

    def __init__(
        self,
        *,
        console: Optional[Console] = None,
        session: Optional[PromptSession] = None,
    ) -> None:
        self.console = console or Console()
        self._session = session or PromptSession()
        self._runtime: Any = None  # DevLoopRuntime
        self._runs: Dict[str, asyncio.Task] = {}
        self._views: Dict[str, RunView] = {}
        self._active_view: Optional[RunView] = None
        self._active_run_id: Optional[str] = None
        self._stop = False
        self.logger = logging.getLogger(__name__)

    async def start(
        self,
        *,
        brief_file: str | None = None,
        revision: bool = False,
        dev_agents: list[DevAgentSpec] | None = None,
        intake_text: str | None = None,
        skip_confirm: bool = False,
    ) -> int:
        """Run the interactive console session.

        Args:
            brief_file: Optional path to a YAML/JSON brief file.
            revision: Whether to collect a ``RevisionBrief`` instead.
            dev_agents: Optional ``--dev-agent`` pool rows (FEAT-388 G2).
                Merges into whichever brief is built; a ``--brief`` file's
                own ``dev_agents`` (if set) wins over this.
            intake_text: Optional ``--text`` free-text feature request
                (FEAT-388 G4) — non-interactive intake, skipping the kind
                picker and the multiline prompt.
            skip_confirm: ``--yes`` — skip the intake accept/edit/redo/
                cancel confirm loop (FEAT-388 G5); only meaningful with
                ``intake_text``.

        Returns:
            Exit code (0 = success, 1 = preflight failure or invalid brief).
        """
        self.console.print(
            Panel(
                "[bold]parrot devloop[/bold] — Interactive Dev-Loop Console\n"
                "Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit.",
                border_style="blue",
            )
        )

        # Bootstrap runtime
        try:
            from parrot.cli.devloop.bootstrap import build_runtime  # noqa: PLC0415
            self._runtime = await build_runtime(console=self.console)
        except SystemExit:
            return 1

        # Load or collect brief, then dispatch
        try:
            await self._dispatch_initial(
                brief_file=brief_file,
                revision=revision,
                dev_agents=dev_agents,
                intake_text=intake_text,
                skip_confirm=skip_confirm,
            )
        except (EOFError, KeyboardInterrupt):
            self.console.print("\n[dim]Cancelled.[/dim]")
            return 0
        except (FileNotFoundError, ValueError) as exc:
            # FEAT-378: pydantic.ValidationError subclasses ValueError, so
            # this also catches an invalid FeatureBrief (e.g. unreadable
            # document_path) / WorkBrief / malformed JSON fallback — a
            # friendly message + non-zero exit, never a raw traceback.
            self.console.print(f"[bold red]Brief error:[/bold red] {exc}")
            return 1

        # Main command loop
        return await self._command_loop()

    async def _dispatch_initial(
        self,
        *,
        brief_file: str | None = None,
        revision: bool = False,
        dev_agents: list[DevAgentSpec] | None = None,
        intake_text: str | None = None,
        skip_confirm: bool = False,
    ) -> None:
        """Collect a brief and dispatch the first run."""
        if revision:
            brief = await self._collect_revision_brief(brief_file)
            await self._dispatch_revision(brief)
        else:
            # Byte-identical call shape when none of the FEAT-388 additions
            # are in play (G7) — keeps test doubles that patch
            # `_collect_work_brief` with the pre-FEAT-388, single-arg
            # signature working unchanged.
            if dev_agents or intake_text is not None or skip_confirm:
                brief = await self._collect_work_brief(
                    brief_file,
                    dev_agents=dev_agents,
                    intake_text=intake_text,
                    skip_confirm=skip_confirm,
                )
            else:
                brief = await self._collect_work_brief(brief_file)
            await self._dispatch_run(brief)

    async def _collect_work_brief(
        self,
        brief_file: str | None = None,
        *,
        dev_agents: list[DevAgentSpec] | None = None,
        intake_text: str | None = None,
        skip_confirm: bool = False,
    ) -> Any:
        """Collect a WorkBrief or FeatureBrief — FEAT-378, homologated FEAT-388.

        Loading from a file routes through the ``Brief`` union
        (:func:`parse_brief`, TASK-1918): ``kind: feature`` files load as
        a :class:`~parrot.flows.dev_loop.models.FeatureBrief`; every
        other file (or one with no ``kind`` at all) loads as a
        ``WorkBrief`` — byte-identical to the pre-FEAT-378 behavior.

        Interactively (no ``brief_file``), a kind picker
        (``bug / enhancement / feature?``) routes ``bug``/``enhancement``
        to the existing WorkBrief wizard (byte-identical fields/order,
        FEAT-388 G7) and ``feature`` to the free-text intake path
        (:meth:`_collect_feature_brief`) — no Jira ticket, no log
        sources (G3). ``intake_text`` (``--text``) bypasses the picker
        and goes straight to intake, non-interactively.

        Args:
            brief_file: Optional path to a YAML/JSON brief file.
            dev_agents: Optional ``--dev-agent`` pool rows (G2). Merges
                into whichever brief is built; a brief file's own
                ``dev_agents`` (if already set) wins over this.
            intake_text: Optional ``--text`` free-text feature request (G4).
            skip_confirm: ``--yes`` — skip the intake accept/edit/redo/
                cancel confirm loop (G5). Applies to the feature path
                regardless of how it was entered (``--text``, or picking
                ``feature`` at the interactive kind picker).
        """
        if brief_file:
            brief = self._load_brief(brief_file)
            return self._merge_dev_agents_flag(brief, dev_agents)

        if intake_text is not None:
            return await self._collect_feature_brief(
                text=intake_text, skip_confirm=skip_confirm, dev_agents_flag=dev_agents
            )

        kind = await self._prompt_kind()
        if kind == "feature":
            return await self._collect_feature_brief(
                dev_agents_flag=dev_agents, skip_confirm=skip_confirm
            )
        return await self._collect_workbrief_wizard(kind, dev_agents_flag=dev_agents)

    @staticmethod
    def _merge_dev_agents_flag(
        brief: Any, dev_agents_flag: list[DevAgentSpec] | None
    ) -> Any:
        """Merge ``--dev-agent`` flags into a file-loaded brief (G2).

        The brief file wins for fields it already sets: if it already
        declares a ``dev_agents`` pool, the flags are ignored.

        Args:
            brief: The already-validated ``WorkBrief``/``FeatureBrief``.
            dev_agents_flag: Parsed ``--dev-agent`` rows, if any.

        Returns:
            ``brief``, unchanged, or a copy with ``dev_agents`` filled in.
        """
        if not dev_agents_flag or getattr(brief, "dev_agents", None):
            return brief
        return brief.model_copy(update={"dev_agents": dev_agents_flag})

    async def _prompt_kind(self) -> str:
        """Ask ``bug / enhancement / feature?`` (FEAT-388 Module 3 kind picker).

        Returns:
            One of ``"bug"``, ``"enhancement"``, ``"feature"``. Defaults
            to ``"bug"`` on EOF/empty input — byte-identical to the
            pre-FEAT-388 implicit WorkBrief default (``WorkBrief.kind``
            defaults to ``"bug"``).
        """
        table = Table(show_header=False, box=None, padding=(0, 1))
        for i, choice in enumerate(_KIND_CHOICES, 1):
            table.add_row(f"  {i}.", choice)
        self.console.print("\n[bold]What kind of work is this?[/bold]")
        self.console.print(table)

        while True:
            try:
                raw = (await self._session.prompt_async("  Choice [1]: ")).strip()
            except EOFError:
                return _KIND_CHOICES[0]
            if not raw:
                return _KIND_CHOICES[0]
            try:
                idx = int(raw)
                if 1 <= idx <= len(_KIND_CHOICES):
                    return _KIND_CHOICES[idx - 1]
            except ValueError:
                if raw.lower() in _KIND_CHOICES:
                    return raw.lower()
            self.console.print(
                f"[red]Choose 1-{len(_KIND_CHOICES)}, or type "
                f"{'/'.join(_KIND_CHOICES)}[/red]"
            )

    async def _collect_workbrief_wizard(
        self, kind: str, *, dev_agents_flag: list[DevAgentSpec] | None = None
    ) -> Any:
        """Collect a ``WorkBrief`` via the wizard — byte-identical fields/order (G7).

        The kind picker only pre-fills ``kind`` (skipping that one
        field's own prompt) and appends the optional dev-agent pool step
        at the end; every other field, prompt, and order is unchanged
        from the pre-FEAT-388 wizard.

        Args:
            kind: ``"bug"`` or ``"enhancement"`` — pre-fills ``WorkBrief.kind``.
            dev_agents_flag: Optional ``--dev-agent`` rows; when given,
                the interactive pool step is skipped and these are used
                directly.

        Returns:
            The validated ``WorkBrief``.
        """
        from parrot.cli.wizard import (
            PydanticWizard,
            WizardConfig,
            WizardFieldOverride,
        )
        from parrot.flows.dev_loop.models import WorkBrief

        config = WizardConfig(
            overrides={
                "description": WizardFieldOverride(file_loadable=True),
                "reporter": WizardFieldOverride(
                    prompt="Reporter (Jira accountId or email)",
                ),
                "escalation_assignee": WizardFieldOverride(
                    prompt="Escalation assignee (Jira accountId or email)",
                ),
            }
        )

        defaults: dict[str, Any] = {"kind": kind}
        if self._runtime:
            if self._runtime.reporter:
                defaults["reporter"] = self._runtime.reporter
            if self._runtime.escalation_assignee:
                defaults["escalation_assignee"] = self._runtime.escalation_assignee

        wizard = PydanticWizard(
            WorkBrief, config=config, console=self.console, session=self._session
        )
        brief = await wizard.collect(initial=defaults)

        dev_agents = dev_agents_flag or await self._collect_dev_agent_pool()
        if dev_agents:
            brief = brief.model_copy(update={"dev_agents": dev_agents})
        return brief

    async def _collect_feature_brief(
        self,
        *,
        text: str | None = None,
        skip_confirm: bool = False,
        dev_agents_flag: list[DevAgentSpec] | None = None,
    ) -> Any:
        """Free-text feature intake path (FEAT-388 Module 3; G3/G4/G5).

        Never asks for a Jira ticket or log sources (G3). Draft →
        review → confirm: ``accept / edit <field> / redo <guidance> /
        cancel`` — never auto-dispatches without an explicit accept
        unless ``skip_confirm`` (``--yes``) is set (G5).

        Args:
            text: Free-text request. When ``None``, prompted
                interactively (multiline — empty line to finish).
            skip_confirm: ``--yes`` — accept the first draft without the
                confirm loop, and skip the interactive pool/judge steps.
            dev_agents_flag: Optional ``--dev-agent`` rows; when given,
                the interactive pool step is skipped and these are used
                directly.

        Returns:
            The assembled ``FeatureBrief``.

        Raises:
            ValueError: Empty free-text request.
            EOFError: The user chose ``cancel`` (propagates so the
                caller's existing "Cancelled." handling applies).
        """
        from parrot.cli.devloop.intake import FeatureIntake

        intake = FeatureIntake()

        if text is None:
            self.console.print(
                "\n[bold]Describe the feature or enhancement you want[/bold] "
                "(multiple lines; empty line to finish):"
            )
            text = await self._prompt_multiline()
        if not text.strip():
            raise ValueError("Feature intake requires a non-empty description.")

        draft = await intake.generate(text)

        if not skip_confirm:
            while True:
                self._print_draft_summary(draft)
                action = (
                    await self._session.prompt_async(
                        "  accept / edit <field> / redo <guidance> / cancel: "
                    )
                ).strip()
                lowered = action.lower()
                if lowered in ("accept", "a", "y", "yes"):
                    break
                if lowered in ("cancel", "c", "no", "n"):
                    raise EOFError
                if lowered.startswith("redo"):
                    guidance = action[len("redo"):].strip() or "(no additional guidance given)"
                    draft = await intake.regenerate(text, guidance)
                    continue
                if lowered.startswith("edit"):
                    draft = await self._edit_draft_field(draft, action[len("edit"):].strip())
                    continue
                self.console.print(
                    "[yellow]Please enter accept, edit <field>, redo <guidance>, "
                    "or cancel.[/yellow]"
                )

        document_path = intake.write_document(draft)
        self.console.print(f"[green]Draft written to {document_path}[/green]")

        if dev_agents_flag:
            dev_agents = dev_agents_flag
        elif skip_confirm:
            dev_agents = None
        else:
            dev_agents = await self._collect_dev_agent_pool()

        judge_panel = None if skip_confirm else await self._collect_judge_panel()

        return intake.build_brief(
            draft, document_path, dev_agents=dev_agents, judge_panel=judge_panel
        )

    async def _prompt_multiline(self, *, prompt_prefix: str = "> ") -> str:
        """Collect free-text across multiple lines; an empty line ends input.

        Args:
            prompt_prefix: Per-line prompt text.

        Returns:
            The collected lines, joined with newlines.
        """
        lines: list[str] = []
        while True:
            try:
                line = await self._session.prompt_async(prompt_prefix)
            except EOFError:
                break
            if not line:
                break
            lines.append(line)
        return "\n".join(lines)

    def _print_draft_summary(self, draft: FeatureDraft) -> None:
        """Render the Rich review panel for a :class:`FeatureDraft`.

        Args:
            draft: The current (possibly regenerated/edited) draft.
        """

        def _bullets(items: list[str]) -> str:
            return "\n".join(f"  - {item}" for item in items) or "  (none)"

        self.console.print(
            Panel(
                f"[bold]Title[/bold]: {draft.title}\n"
                f"[bold]Slug[/bold]: {draft.slug}\n\n"
                f"[bold]Problem Statement[/bold]:\n{draft.problem_statement}\n\n"
                f"[bold]Requirements[/bold]:\n{_bullets(draft.requirements)}\n\n"
                f"[bold]Acceptance Criteria[/bold]:\n{_bullets(draft.acceptance_criteria)}\n\n"
                f"[bold]Affected Areas[/bold]:\n{_bullets(draft.affected_areas)}\n\n"
                f"[bold]Out of Scope[/bold]:\n{_bullets(draft.out_of_scope)}\n\n"
                f"[bold]Open Questions[/bold]:\n{_bullets(draft.open_questions)}",
                title="Feature Draft",
                border_style="cyan",
            )
        )

    async def _edit_draft_field(self, draft: FeatureDraft, field_name: str) -> FeatureDraft:
        """Directly edit one field of the draft (the ``edit <field>`` action).

        Args:
            draft: The draft being edited.
            field_name: Raw field name typed by the user.

        Returns:
            A copy of ``draft`` with ``field_name`` replaced, or the
            unchanged ``draft`` when ``field_name`` is not recognised.
        """
        from parrot.cli.devloop.intake import FeatureDraft

        field_name = field_name.strip()
        if field_name not in FeatureDraft.model_fields:
            self.console.print(
                f"[red]Unknown field: {field_name!r}. Valid fields: "
                f"{', '.join(FeatureDraft.model_fields)}[/red]"
            )
            return draft

        current = getattr(draft, field_name)
        if isinstance(current, list):
            self.console.print(
                f"[dim]Editing {field_name} (one item per line, empty line to finish; "
                "an immediate empty line leaves it unchanged)[/dim]"
            )
            items: list[str] = []
            while True:
                try:
                    line = await self._session.prompt_async("  > ")
                except EOFError:
                    break
                if not line:
                    break
                items.append(line)
            # An immediate empty line (no items typed) means "no change" —
            # matching the scalar branch's "empty input = keep current"
            # semantics, rather than silently clearing the list to [].
            new_value: Any = items if items else current
        else:
            try:
                raw = (await self._session.prompt_async(f"  {field_name} [{current}]: ")).strip()
            except EOFError:
                raw = ""
            new_value = raw or current

        return draft.model_copy(update={field_name: new_value})

    async def _prompt_backend_choice(self, backends: list[BackendInfo]) -> str | None:
        """Render a numbered backend picker and prompt for a choice.

        Args:
            backends: Candidate catalog entries (already role-filtered).

        Returns:
            The chosen backend id, or ``None`` on EOF/empty input
            (ends the enclosing row-collection loop).
        """
        table = Table(show_header=False, box=None, padding=(0, 1))
        for i, backend in enumerate(backends, 1):
            table.add_row(f"  {i}.", f"{backend.id} (default model: {backend.default_model})")
        self.console.print(table)

        while True:
            try:
                raw = (await self._session.prompt_async("  Backend: ")).strip()
            except EOFError:
                return None
            if not raw:
                return None
            try:
                idx = int(raw)
                if 1 <= idx <= len(backends):
                    return backends[idx - 1].id
            except ValueError:
                if raw in {b.id for b in backends}:
                    return raw
            self.console.print(f"[red]Choose 1-{len(backends)}, or a backend id[/red]")

    async def _collect_dev_agent_pool(self) -> list[DevAgentSpec] | None:
        """Optional dev-agent pool step — rows of ``DevAgentSpec`` (G2).

        Default is skip (returns ``None``, i.e. the single-agent path).
        Backend choices + default-model hints come from the catalog
        (:mod:`parrot.flows.dev_loop.catalog`, TASK-1968).

        Returns:
            The collected pool, or ``None`` when the user skips it (or
            no valid row was collected).
        """
        from pydantic import ValidationError

        from parrot.flows.dev_loop import catalog
        from parrot.flows.dev_loop.models import DevAgentSpec

        try:
            add_pool = (
                await self._session.prompt_async(
                    "\nConfigure a custom dev-agent pool? [y/N]: "
                )
            ).strip().lower()
        except EOFError:
            return None
        if add_pool not in ("y", "yes"):
            return None

        backends = catalog.backends_for_role("development")
        rows: list[DevAgentSpec] = []
        while True:
            prompt = "Add a dev-agent row? [y/N]: " if rows else "Add a dev-agent row? [Y/n]: "
            try:
                more = (await self._session.prompt_async(prompt)).strip().lower()
            except EOFError:
                break
            proceed = more in ("y", "yes") or (not more and not rows)
            if not proceed:
                break

            backend_id = await self._prompt_backend_choice(backends)
            if backend_id is None:
                break
            backend = catalog.get_backend(backend_id)
            default_hint = backend.default_model if backend else "default"
            try:
                model = (
                    await self._session.prompt_async(f"  Model [{default_hint}]: ")
                ).strip()
            except EOFError:
                model = ""
            try:
                count_raw = (await self._session.prompt_async("  Count [1]: ")).strip()
            except EOFError:
                count_raw = ""
            try:
                count = int(count_raw) if count_raw else 1
            except ValueError:
                count = 1

            try:
                rows.append(DevAgentSpec(agent=backend_id, model=model, count=count))
            except ValidationError as exc:
                self.console.print(f"[red]Invalid dev-agent row: {exc}[/red]")

        return rows or None

    async def _collect_judge_panel(self) -> JudgePanelConfig | None:
        """Optional QA judge-panel step — rows of ``JudgeSpec`` (feature path only).

        Choices are limited to the catalog's ``JUDGE_BACKENDS``,
        intersected with ``_JUDGE_REVIEW_CAPABLE_BACKENDS`` (backends
        ``JudgeSpec`` actually accepts). Default is skip
        (``None``, i.e. ``JudgePanelReviewDispatcher`` falls back to
        ``default_judge_panel()`` / ``DEV_LOOP_JUDGE_PANEL``). A
        ``JudgeSpec`` construction failure is reported and the row is
        retried rather than crashing the wizard.

        Returns:
            The collected panel, or ``None`` when skipped/empty.
        """
        from pydantic import ValidationError

        from parrot.flows.dev_loop import catalog
        from parrot.flows.dev_loop.models import (
            JudgePanelConfig,
            JudgeSpec,
        )

        try:
            customize = (
                await self._session.prompt_async(
                    "\nCustomize the QA judge panel? [y/N]: "
                )
            ).strip().lower()
        except EOFError:
            return None
        if customize not in ("y", "yes"):
            return None

        judge_backend_ids = set(catalog.JUDGE_BACKENDS) & set(_JUDGE_REVIEW_CAPABLE_BACKENDS)
        # `backends_for_role` (not `catalog.BACKENDS`) — a reviewer need
        # not be a dev-loop coding backend: "mantle" has no
        # `build_dispatcher` branch and lives in `REVIEW_ONLY_BACKENDS`.
        backends = [b for b in catalog.backends_for_role("judge") if b.id in judge_backend_ids]
        judges: list[JudgeSpec] = []
        while True:
            prompt = "Add a judge? [y/N]: " if judges else "Add a judge? [Y/n]: "
            try:
                more = (await self._session.prompt_async(prompt)).strip().lower()
            except EOFError:
                break
            proceed = more in ("y", "yes") or (not more and not judges)
            if not proceed:
                break

            backend_id = await self._prompt_backend_choice(backends)
            if backend_id is None:
                break
            backend = catalog.get_backend(backend_id)
            default_hint = backend.default_model if backend else "default"
            try:
                model = (
                    await self._session.prompt_async(f"  Model [{default_hint}]: ")
                ).strip()
            except EOFError:
                model = ""

            try:
                judges.append(JudgeSpec(agent=backend_id, model=model))
            except ValidationError as exc:
                self.console.print(
                    f"[red]Invalid judge: {exc}[/red] — pick a backend with a "
                    "review profile."
                )

        return JudgePanelConfig(judges=judges) if judges else None

    async def _collect_revision_brief(self, brief_file: Optional[str] = None) -> Any:
        """Collect a RevisionBrief via wizard or file."""
        from parrot.flows.dev_loop.models import RevisionBrief  # noqa: PLC0415
        from parrot.cli.wizard import PydanticWizard  # noqa: PLC0415

        if brief_file:
            return self._load_brief_file(brief_file, RevisionBrief)

        wizard = PydanticWizard(
            RevisionBrief, console=self.console, session=self._session
        )
        return await wizard.collect()

    def _load_brief_file(self, path_str: str, model_type: type) -> Any:
        """Load a brief from a YAML or JSON file."""
        data = self._read_brief_data(path_str)
        return model_type(**data)

    def _load_brief(self, path_str: str) -> Any:
        """Load a ``WorkBrief`` or ``FeatureBrief`` from a YAML/JSON file (FEAT-378).

        Routes through the ``Brief`` discriminated union
        (:func:`~parrot.flows.dev_loop.models.parse_brief`, TASK-1918):
        ``kind: feature`` → :class:`FeatureBrief`; anything else (or no
        ``kind`` at all) → ``WorkBrief`` — byte-identical to the
        pre-FEAT-378 ``_load_brief_file(path, WorkBrief)`` behavior.

        Args:
            path_str: Path to the YAML/JSON brief file.

        Returns:
            A validated ``WorkBrief`` or ``FeatureBrief`` instance.

        Raises:
            FileNotFoundError: When ``path_str`` does not resolve to a file.
            pydantic.ValidationError: When the loaded data fails validation
                against the resolved brief model.
        """
        from parrot.flows.dev_loop.models import parse_brief  # noqa: PLC0415

        data = self._read_brief_data(path_str)
        return parse_brief(data)

    @staticmethod
    def _read_brief_data(path_str: str) -> Dict[str, Any]:
        """Read + parse a YAML/JSON brief file into a raw ``dict``.

        Args:
            path_str: Path to the brief file.

        Returns:
            The parsed mapping.

        Raises:
            FileNotFoundError: When ``path_str`` does not resolve to a file.
        """
        path = Path(path_str).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Brief file not found: {path}")
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # noqa: PLC0415
            data = yaml.safe_load(text)
        except Exception:
            data = json.loads(text)
        return data

    def _print_feature_brief_summary(self, brief: Any) -> None:
        """Render a confirmation summary panel for a ``FeatureBrief`` (FEAT-378).

        Mirrors the existing gate/header ``Panel`` rendering style — the
        WorkBrief path has no equivalent pre-dispatch summary today, so
        this is additive only (zero behavior change for WorkBrief runs).

        Args:
            brief: The validated ``FeatureBrief`` about to be dispatched.
        """
        judges = "default (3-judge panel)"
        if brief.judge_panel is not None:
            judges = ", ".join(j.agent for j in brief.judge_panel.judges)
        self.console.print(
            Panel(
                f"[bold]document_path[/bold]: {brief.document_path}\n"
                f"[bold]document_kind[/bold]: {brief.document_kind}\n"
                f"[bold]jira_issue_key[/bold]: {brief.jira_issue_key or '(none)'}\n"
                f"[bold]judge_panel[/bold]: {judges}",
                title="Feature Brief",
                border_style="green",
            )
        )

    async def _dispatch_run(self, brief: Any) -> str:
        """Dispatch a new dev-loop run and attach a RunView."""
        import uuid  # noqa: PLC0415
        from parrot.flows.dev_loop.models import FeatureBrief  # noqa: PLC0415

        if isinstance(brief, FeatureBrief):
            self._print_feature_brief_summary(brief)

        run_id = f"run-{uuid.uuid4().hex[:8]}"
        runner = self._runtime.runner

        task = asyncio.create_task(
            runner.run(brief, run_id=run_id),
            name=f"devloop-run-{run_id}",
        )
        self._runs[run_id] = task

        # Wait briefly for the host to be created
        await asyncio.sleep(0.1)
        host = runner.get_host(run_id)
        if host:
            view = RunView(host, self.console, run_id=run_id)
            self._views[run_id] = view
            self._active_view = view
            self._active_run_id = run_id

        self.console.print(f"[green]Dispatched run {run_id}[/green]")
        return run_id

    async def _dispatch_revision(self, brief: Any) -> str:
        """Dispatch a revision-mode run."""
        import uuid  # noqa: PLC0415
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        runner = self._runtime.runner

        task = asyncio.create_task(
            runner.run_revision(brief, run_id=run_id),
            name=f"devloop-revision-{run_id}",
        )
        self._runs[run_id] = task

        await asyncio.sleep(0.1)
        host = runner.get_host(run_id)
        if host:
            view = RunView(host, self.console, run_id=run_id)
            self._views[run_id] = view
            self._active_view = view
            self._active_run_id = run_id

        self.console.print(f"[green]Dispatched revision run {run_id}[/green]")
        return run_id

    async def _command_loop(self) -> int:
        """Main interactive loop: render + poll gates + accept commands."""
        stop_event = asyncio.Event()

        with patch_stdout():
            while not self._stop:
                # Render active view if any
                if self._active_view:
                    render_task = asyncio.create_task(
                        self._active_view.run_live(stop_event)
                    )
                else:
                    render_task = None

                try:
                    # Poll for gates + accept user input
                    await self._interactive_loop(stop_event)
                except (EOFError, KeyboardInterrupt):
                    await self._handle_ctrl_c()
                finally:
                    stop_event.set()
                    if render_task and not render_task.done():
                        render_task.cancel()
                        try:
                            await render_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    stop_event.clear()

        # Wait for all runs to complete
        for run_id, task in list(self._runs.items()):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        return 0

    async def _interactive_loop(self, stop_event: asyncio.Event) -> None:
        """Accept commands and watch for gates."""
        while not self._stop:
            # Check for pending gates
            if self._active_view:
                pending = self._active_view.pending_gates()
                if pending:
                    await self._handle_gates(pending)
                    continue

            # Check if active run finished
            if self._active_run_id and self._active_run_id in self._runs:
                task = self._runs[self._active_run_id]
                if task.done():
                    # Final poll to get remaining envelopes
                    if self._active_view:
                        self._active_view.poll_once()
                    try:
                        result = task.result()
                        status = getattr(result, "status", "unknown")
                        self.console.print(
                            f"\n[bold]Run {self._active_run_id} finished: {status}[/bold]"
                        )
                    except Exception as exc:
                        self.console.print(
                            f"\n[bold red]Run {self._active_run_id} errored: {exc}[/bold red]"
                        )
                    self._active_view = None
                    stop_event.set()

            # Accept user input
            try:
                raw = await asyncio.wait_for(
                    self._session.prompt_async("devloop> "),
                    timeout=_GATE_POLL_INTERVAL,
                )
            except asyncio.TimeoutError:
                continue
            except EOFError:
                self._stop = True
                break

            raw = raw.strip()
            if not raw:
                continue

            if raw.startswith("/"):
                await self._dispatch_command(raw)
            else:
                self.console.print("[dim]Type /help for commands.[/dim]")

    async def _handle_gates(self, gates: Dict[str, Any]) -> None:
        """Prompt user for each pending gate."""
        for gate_id, gate in gates.items():
            if self._active_view:
                self._active_view.pause()

            kind = getattr(gate, "kind", "")
            title = getattr(gate, "title", "")
            instructions = getattr(gate, "instructions", "")
            expires_at = getattr(gate, "expires_at", None)

            panel_content = f"[bold yellow]{kind}[/bold yellow]: {title}"
            if instructions:
                panel_content += f"\n{instructions}"
            if expires_at:
                import time  # noqa: PLC0415
                remaining = max(0, expires_at - time.time())
                panel_content += f"\n[dim]Expires in {int(remaining)}s[/dim]"

            self.console.print(Panel(
                panel_content,
                title=f"Gate: {gate_id}",
                border_style="yellow",
            ))

            try:
                resolution = await self._session.prompt_async(
                    "  Approve or reject? [a/r]: "
                )
                resolution = resolution.strip().lower()
                if resolution in ("a", "approve", "approved", "y", "yes"):
                    resolution_str = "approved"
                elif resolution in ("r", "reject", "rejected", "n", "no"):
                    resolution_str = "rejected"
                else:
                    self.console.print("[yellow]Skipping gate (enter 'a' or 'r').[/yellow]")
                    if self._active_view:
                        self._active_view.resume()
                    continue

                comment = await self._session.prompt_async("  Comment (optional): ")
                comment = comment.strip()

                identity = os.environ.get("USER", "cli-user")
                runner = self._runtime.runner

                try:
                    await runner.resolve_gate(
                        self._active_run_id,
                        gate_id,
                        resolution=resolution_str,
                        resolved_by=identity,
                        comment=comment,
                    )
                    self.console.print(
                        f"[green]Gate {gate_id} {resolution_str}.[/green]"
                    )
                except Exception as exc:
                    self.console.print(
                        f"[red]Gate resolution failed: {exc}[/red]"
                    )

            except (EOFError, KeyboardInterrupt):
                self.console.print("[dim]Gate skipped.[/dim]")

            if self._active_view:
                self._active_view.resume()

    async def _handle_ctrl_c(self) -> None:
        """Handle Ctrl-C: confirm cancellation."""
        if not self._active_run_id:
            self._stop = True
            return

        self.console.print("\n[yellow]Ctrl-C detected.[/yellow]")
        try:
            confirm = await self._session.prompt_async(
                "Cancel active run? [y/N]: "
            )
            if confirm.strip().lower() in ("y", "yes"):
                identity = os.environ.get("USER", "cli-user")
                runner = self._runtime.runner
                try:
                    await runner.cancel_run(
                        self._active_run_id,
                        requested_by=identity,
                    )
                    self.console.print(
                        f"[red]Run {self._active_run_id} cancelled.[/red]"
                    )
                except Exception as exc:
                    self.console.print(f"[red]Cancel failed: {exc}[/red]")
                self._stop = True
            else:
                self.console.print("[dim]Continuing...[/dim]")
        except (EOFError, KeyboardInterrupt):
            self._stop = True

    # ── Slash commands ──────────────────────────────────────────────────

    async def _dispatch_command(self, raw: str) -> None:
        """Parse and dispatch a slash command."""
        parts = raw[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        handlers = {
            "runs": self._cmd_runs,
            "attach": self._cmd_attach,
            "cancel": self._cmd_cancel,
            "new": self._cmd_new,
            "feature": self._cmd_feature,
            "revise": self._cmd_revise,
            "help": self._cmd_help,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(args)
            except Exception as exc:
                self.console.print(f"[red]Error: {exc}[/red]")
        else:
            self.console.print(
                f"[yellow]Unknown command: /{cmd}[/yellow] — type /help"
            )

    async def _cmd_runs(self, args: str) -> None:
        """List all runs in this session."""
        if not self._runs:
            self.console.print("[dim]No runs.[/dim]")
            return

        table = Table(title="Runs")
        table.add_column("Run ID", style="cyan")
        table.add_column("Status")
        table.add_column("Active View")

        runner = self._runtime.runner
        # `active_runs`/`parked_runs` are properties (copies), not methods.
        active_set = runner.active_runs
        parked_set = runner.parked_runs

        for run_id, task in self._runs.items():
            if task.done():
                try:
                    result = task.result()
                    status = f"[green]finished ({getattr(result, 'status', '?')})[/green]"
                except Exception:
                    status = "[red]errored[/red]"
            elif run_id in parked_set:
                # FEAT-377 TASK-1917 (G6): a parked run released its
                # concurrency slot while awaiting a gate — it is in flight,
                # not capacity-queued, so it must not show as "queued (cap)".
                status = "[yellow]awaiting gate (parked)[/yellow]"
            elif run_id in active_set:
                status = "[yellow]running[/yellow]"
            else:
                status = "[dim]queued (cap)[/dim]"

            is_active = "*" if run_id == self._active_run_id else ""
            table.add_row(run_id, status, is_active)

        self.console.print(table)

    async def _cmd_attach(self, args: str) -> None:
        """Switch the active view to a different run."""
        run_id = args.strip()
        if not run_id:
            self.console.print("[yellow]Usage: /attach <run-id>[/yellow]")
            return
        if run_id not in self._views:
            self.console.print(f"[red]Run {run_id} not found or no view.[/red]")
            return
        if self._active_view:
            self._active_view.stop()
        self._active_view = self._views[run_id]
        self._active_run_id = run_id
        self.console.print(f"[green]Attached to {run_id}[/green]")

    async def _cmd_cancel(self, args: str) -> None:
        """Cancel a run."""
        run_id = args.strip() or self._active_run_id
        if not run_id:
            self.console.print("[yellow]No active run to cancel.[/yellow]")
            return
        identity = os.environ.get("USER", "cli-user")
        runner = self._runtime.runner
        try:
            await runner.cancel_run(run_id, requested_by=identity)
            self.console.print(f"[red]Run {run_id} cancelled.[/red]")
        except Exception as exc:
            self.console.print(f"[red]Cancel failed: {exc}[/red]")

    async def _cmd_new(self, args: str) -> None:
        """Start a new run with the wizard."""
        if self._active_view:
            self._active_view.pause()
        try:
            brief = await self._collect_work_brief()
            await self._dispatch_run(brief)
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]Cancelled.[/dim]")
        except (FileNotFoundError, ValueError) as exc:
            # Mirrors start()'s friendly error path (G5): pydantic.
            # ValidationError subclasses ValueError, so this also catches
            # an invalid brief — never a raw traceback.
            self.console.print(f"[bold red]Brief error:[/bold red] {exc}")
        if self._active_view:
            self._active_view.resume()

    async def _cmd_feature(self, args: str) -> None:
        """Start a new feature-mode run via free-text intake (``/feature``, G3/G4)."""
        if self._active_view:
            self._active_view.pause()
        try:
            text = args.strip() or None
            brief = await self._collect_feature_brief(text=text)
            await self._dispatch_run(brief)
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]Cancelled.[/dim]")
        except (FileNotFoundError, ValueError) as exc:
            # Mirrors start()'s friendly error path (G5): an empty free-text
            # request, an intake LLM failure, or an invalid FeatureBrief
            # (pydantic.ValidationError subclasses ValueError) all surface
            # as "Brief error:" — never a raw traceback.
            self.console.print(f"[bold red]Brief error:[/bold red] {exc}")
        if self._active_view:
            self._active_view.resume()

    async def _cmd_revise(self, args: str) -> None:
        """Start a revision-mode run."""
        if self._active_view:
            self._active_view.pause()
        try:
            brief_file = args.strip() or None
            brief = await self._collect_revision_brief(brief_file)
            await self._dispatch_revision(brief)
        except (EOFError, KeyboardInterrupt):
            self.console.print("[dim]Cancelled.[/dim]")
        if self._active_view:
            self._active_view.resume()

    async def _cmd_help(self, args: str) -> None:
        """Show help."""
        help_text = (
            "[bold]Commands:[/bold]\n"
            "  /new           Start a new run (wizard)\n"
            "  /feature [text] Start a new feature-mode run (free-text intake)\n"
            "  /runs          List all runs in this session\n"
            "  /attach <id>   Switch view to a different run\n"
            "  /cancel [id]   Cancel a run (default: active)\n"
            "  /revise [file] Start a revision-mode run\n"
            "  /help          Show this help\n"
            "  /quit          Exit the console\n"
            "\n"
            "  Ctrl-C         Cancel active run (with confirmation)"
        )
        self.console.print(Panel(help_text, title="Help", border_style="blue"))

    async def _cmd_quit(self, args: str) -> None:
        """Exit the console."""
        self._stop = True
