"""Bank-statement Excel ingestion via ExecutionPlan (FEAT-453, Module 9, G7).

Builds a deterministic, LLM-free :class:`~parrot.bots.flows.plan.ExecutionPlan`
that registers one expense per Excel row, through
:class:`~parrot.tools.execution_plan.toolkit.ExecutionPlanToolkit`'s
zero-token tool-call DAG substrate.

Decision D3 (the hazard this module exists to defuse): two legitimate
imports of *different* bank statements for the *same* period must never
share a resumability identity. ``ImportRun.statement_digest`` (sha256 of the
source bytes) is baked into every node's ``id``/``store_as`` at plan-build
time, so a second import for the same period never collides with the
first's working-memory keys.

**Contract correction** (documented per the anti-hallucination discipline —
see this task's Completion Note for the full account): the task's Codebase
Contract describes the D3 hazard in terms of
``parrot_tools.scraping.flow_executor._checkpoint_token`` — that mechanism
belongs to the *browser* ``FlowExecutor`` (used by
``BusinessAutomationToolkit``/TASK-2390), not to ``ExecutionPlanToolkit``'s
``ExecutionPlan``/``AgentsFlow`` substrate, which this module actually uses
and which has **no** ``global_params`` field and explicitly disables
flow-level checkpointing (FEAT-399, ``PlanMetadata.checkpoint=False`` at the
toolkit). This module therefore (a) discriminates re-imports by baking the
digest into node/working-memory identity instead of a nonexistent
``flow.global_params``, and (b) maintains its own small, permission-hardened
import manifest under ``${PARROT_STATE_DIR}`` as the audit/reconciliation
record this feature needs, independent of ``AgentsFlow``'s own (disabled)
checkpointing.

**Resume-without-duplicates (code-review remediation, AC-12)**: since
``AgentsFlow``'s own checkpointing is deliberately disabled (see above),
per-row resumability lives entirely in this module's manifest instead.
:func:`make_import_progress_listener` returns a sync ``(event, node_id,
info) -> None`` callback matching ``AgentsFlow``/``ExecutionPlanToolkit``'s
already-public ``on_node_event`` contract (``parrot/bots/flows/flow/flow.py
:422``, ``parrot/tools/execution_plan/toolkit.py:103``) — no core file is
modified. The caller passes it to
``ExecutionPlanToolkit(on_node_event=make_import_progress_listener(...))``
(or composes it via ``AgentsFlow.add_node_event_listener`` for a
lower-level driver). On every ``"node_completed"`` event for one of this
plan's ``row-<digest>-<i>`` nodes, the row index is appended to the
manifest's ``completed_rows`` list — synchronously, before the flow
advances to the next node, so a kill immediately after leaves that row
durably marked done. :func:`build_import_plan` reads any existing
manifest for the same ``statement_digest`` before building nodes and
skips already-completed rows, so re-running it after a crash produces a
plan containing only the remaining rows — never a duplicate registration.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import pandas as pd
from parrot.bots.flows.plan import ExecutionPlan, PlanMetadata, PlanNode
from parrot_loaders.excel import ExcelLoader

from .models import ImportRun

logger = logging.getLogger(__name__)

#: Environment variable naming the root state directory. Checkpoints live
#: under ``<state_dir>/business_automation/checkpoints/<operation>/`` —
#: outside both the Obsidian vault and every wiki storage root (Decision D3).
_STATE_DIR_ENV_VAR = "PARROT_STATE_DIR"


def _state_dir() -> Path:
    """Resolve the root state directory (``$PARROT_STATE_DIR`` or a
    per-user default)."""
    raw = os.environ.get(_STATE_DIR_ENV_VAR)
    if raw:
        return Path(raw)
    return Path.home() / ".parrot_state"


def checkpoint_dir_for(operation: str) -> Path:
    """Return (creating if needed) the checkpoint directory for *operation*.

    ``${PARROT_STATE_DIR}/business_automation/checkpoints/<operation>/``,
    directory mode ``0700`` (Decision D3) — never inside the Obsidian vault
    or a wiki storage root, both of which are mirrored/ingested surfaces.
    """
    path = _state_dir() / "business_automation" / "checkpoints" / operation
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def compute_statement_digest(xlsx_path: Union[str, Path]) -> str:
    """Return a stable digest of the source Excel file's bytes.

    Decision D3: this discriminates two legitimate imports of different
    statements for the same ``period`` — without it, the second import
    would resume/collide with the first's working-memory keys and silently
    skip every row it (wrongly) believes is already done.
    """
    data = Path(xlsx_path).read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


async def _load_expense_rows(
    xlsx_path: Union[str, Path], client_column: str, amount_column: str
) -> List[Dict[str, str]]:
    """Load per-row expense data from *xlsx_path*.

    Uses :class:`ExcelLoader` in row mode to establish the canonical
    per-row Document count (the contract's "iterate ExcelLoader row-mode
    Documents"), cross-checked against a direct ``pandas.read_excel`` for
    the actual column values — ``ExcelLoader``'s row-mode ``Document.metadata``
    carries column *names* and a rendered text body, not the raw per-column
    values needed to populate each node's parameters, so the structured
    values are sourced directly (pandas is already an ``ExcelLoader``
    dependency, not a new one).

    Raises:
        ValueError: If the two counts disagree (data integrity), or a
            required column is missing.
    """
    # NOTE: pass a concrete Path (not str) to loader.load() — AbstractLoader
    # .from_path() converts a str source via PurePath(), whose base class has
    # no is_dir(); Path is safe on both branches. Pre-existing behaviour in
    # parrot.loaders.abstract, out of this task's file scope — worked around
    # here rather than modified there.
    resolved_path = Path(xlsx_path)
    loader = ExcelLoader(resolved_path, output_mode="row")
    documents = await loader.load(resolved_path, split_documents=False)

    df = pd.read_excel(str(xlsx_path))

    if len(documents) != len(df):
        raise ValueError(
            f"Row count mismatch between ExcelLoader ({len(documents)}) and "
            f"pandas ({len(df)}) for {xlsx_path} — refusing to ingest"
        )

    missing_columns = {client_column, amount_column} - {str(c) for c in df.columns}
    if missing_columns:
        raise ValueError(f"Missing required column(s) in {xlsx_path}: {sorted(missing_columns)}")

    df.columns = [str(c) for c in df.columns]
    return df[[client_column, amount_column]].astype(str).to_dict(orient="records")


def _plan_name_for(digest: str) -> str:
    """The deterministic ``ExecutionPlan.name`` for a statement digest —
    shared by :func:`build_import_plan` and :func:`make_import_progress_listener`
    so the two never drift on the naming convention."""
    return f"expense-import-{digest}"


def _manifest_path_for(operation: str, digest: str) -> Path:
    """The deterministic manifest path for a statement digest."""
    return checkpoint_dir_for(operation) / f"{_plan_name_for(digest)}.import.json"


_ROW_NODE_ID_RE = re.compile(r"^row-(?P<digest>.+)-(?P<index>\d+)$")


def _read_completed_rows(operation: str, digest: str) -> set:
    """Read the set of already-completed row indices from a prior manifest
    for this exact ``(operation, digest)``, or an empty set if none exists
    yet (first import, or the manifest was never written)."""
    manifest_path = _manifest_path_for(operation, digest)
    if not manifest_path.is_file():
        return set()
    try:
        data = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning(
            "Import manifest %s is unreadable/corrupt; treating as no prior "
            "completions (a fresh full plan will be built, not a resume).",
            manifest_path,
        )
        return set()
    return set(data.get("completed_rows", []))


@dataclass
class ImportPlanBundle:
    """The constructed :class:`ExecutionPlan` plus its :class:`ImportRun`
    discriminator (Decision D3) and row counts (for reconciliation).

    Attributes:
        plan: The plan to run, containing only rows not yet completed.
            ``None`` when :attr:`fully_completed` is ``True`` — an
            ``ExecutionPlan`` cannot hold zero nodes (``min_length=1``), so
            a fully-resumed import returns no plan at all rather than
            constructing an invalid one.
        import_run: The statement's ``ImportRun`` discriminator.
        row_count: Total rows in the source statement (Decision D3's
            reconciliation unit) — unaffected by resume; always the
            original Excel row count.
        already_completed_rows: How many of ``row_count`` were already
            marked done in a prior manifest (0 on a first import).
        fully_completed: ``True`` when every row was already completed —
            re-running :func:`build_import_plan` after the whole statement
            finished is a safe no-op, not an error.
    """

    plan: Optional[ExecutionPlan]
    import_run: ImportRun
    row_count: int
    already_completed_rows: int = 0
    fully_completed: bool = False

    @property
    def remaining_row_count(self) -> int:
        """Rows the returned :attr:`plan` will actually register."""
        return self.row_count - self.already_completed_rows


async def build_import_plan(
    xlsx_path: Union[str, Path],
    *,
    period: str,
    operation: str = "register_expense",
    client_column: str = "client",
    amount_column: str = "amount",
) -> ImportPlanBundle:
    """Build a deterministic, LLM-free ExecutionPlan for a bank-statement import.

    One :class:`PlanNode` per row, each invoking *operation* (via the
    ``run_operation`` tool — see
    :meth:`~parrot_tools.business_automation.toolkit.BusinessAutomationToolkit.run_operation`)
    with that row's values baked in as literal ``args`` (this function
    generates the plan fresh per import; there is no need for
    ``ExecutionPlan``'s ``{params.<name>}``/``{item...}`` runtime
    placeholders). Nodes are chained via ``depends_on`` — and
    ``PlanMetadata.max_parallel_tasks=1`` set as a second line of defense —
    so the import runs strictly sequentially over the one authenticated
    browser session the underlying flow drives.

    Args:
        xlsx_path: Path to the bank-statement Excel file.
        period: Accounting period label (e.g. ``"2026-Q1"``) — a human
            identifier, not itself a uniqueness guarantee (Decision D3: two
            statements can share a period).
        operation: The :class:`~parrot_tools.business_automation.models.BusinessOperation`
            name to invoke per row (default ``"register_expense"``).
        client_column: Excel column holding the client name.
        amount_column: Excel column holding the expense amount.

    Returns:
        An :class:`ImportPlanBundle` with the plan (only not-yet-completed
        rows — see :func:`make_import_progress_listener`), its
        ``ImportRun``, and the row counts (for reconciliation via
        :func:`reconcile`).
    """
    digest = compute_statement_digest(xlsx_path)
    import_run = ImportRun(statement_digest=digest, period=period, started_at=datetime.now(timezone.utc))

    rows = await _load_expense_rows(xlsx_path, client_column, amount_column)
    completed_rows = _read_completed_rows(operation, digest)

    nodes: List[PlanNode] = []
    previous_id: Optional[str] = None
    for i, row in enumerate(rows):
        if i in completed_rows:
            continue
        node_id = f"row-{digest}-{i}"
        nodes.append(
            PlanNode(
                id=node_id,
                tool="run_operation",
                args={
                    "name": operation,
                    "params": {
                        client_column: row[client_column],
                        amount_column: row[amount_column],
                    },
                },
                store_as=f"expense-{digest}-{i}",
                depends_on=[previous_id] if previous_id else [],
                description=f"Register expense row {i} of statement {digest}",
            )
        )
        previous_id = node_id

    _write_import_manifest(
        operation, _plan_name_for(digest), import_run, rows_in=len(rows), completed_rows=completed_rows
    )

    if not nodes:
        # Every row was already completed by a prior run — a resumed
        # re-build is a safe no-op, not an error (ExecutionPlan.nodes
        # requires min_length=1, so there is no valid empty plan to return).
        return ImportPlanBundle(
            plan=None,
            import_run=import_run,
            row_count=len(rows),
            already_completed_rows=len(completed_rows),
            fully_completed=True,
        )

    plan = ExecutionPlan(
        name=_plan_name_for(digest),
        objective=(f"Register {len(nodes)} expense(s) from a bank statement for period {period}"),
        nodes=nodes,
        metadata=PlanMetadata(max_parallel_tasks=1),
    )

    return ImportPlanBundle(
        plan=plan,
        import_run=import_run,
        row_count=len(rows),
        already_completed_rows=len(completed_rows),
        fully_completed=False,
    )


def _write_import_manifest(
    operation: str,
    plan_name: str,
    import_run: ImportRun,
    *,
    rows_in: int,
    completed_rows: Optional[set] = None,
) -> Path:
    """Persist a small, permission-hardened import manifest.

    This is this module's own audit/reconciliation record — independent of
    ``AgentsFlow``'s own (disabled, FEAT-399) flow-level checkpointing.
    File mode ``0600`` (Decision D3): checkpoints contain client names.

    Args:
        completed_rows: Row indices already known to be done (preserved
            across a resumed :func:`build_import_plan` call — never reset
            to empty on an existing manifest).
    """
    checkpoint_dir = checkpoint_dir_for(operation)
    manifest_path = checkpoint_dir / f"{plan_name}.import.json"
    manifest_path.write_text(
        json.dumps(
            {
                "plan_name": plan_name,
                "operation": operation,
                "statement_digest": import_run.statement_digest,
                "period": import_run.period,
                "started_at": import_run.started_at.isoformat(),
                "rows_in": rows_in,
                "completed_rows": sorted(completed_rows or ()),
            },
            indent=2,
        )
    )
    manifest_path.chmod(0o600)
    return manifest_path


def make_import_progress_listener(operation: str, digest: str) -> Callable[[str, str, Dict[str, Any]], None]:
    """Build an ``AgentsFlow``/``ExecutionPlanToolkit``-compatible
    ``on_node_event`` listener that records per-row completion (AC-12).

    Pass the returned callback to ``ExecutionPlanToolkit(on_node_event=...)``
    (or ``AgentsFlow.add_node_event_listener``) when executing the
    :class:`ExecutionPlan` from :func:`build_import_plan` for this exact
    ``(operation, digest)`` pair — no core file is modified; both extension
    points already accept an arbitrary sync/async ``(event, node_id, info)``
    callback (``parrot/bots/flows/flow/flow.py:422``,
    ``parrot/tools/execution_plan/toolkit.py:103``).

    On every ``"node_completed"`` event for one of this plan's
    ``row-<digest>-<i>`` nodes, appends *i* to the manifest's
    ``completed_rows`` — synchronously, so a process kill immediately after
    this callback returns still leaves that row durably marked done. Events
    for any other node id (a different plan/digest sharing the same
    listener registry) are ignored. Never raises: a manifest write failure
    is logged and swallowed, matching this ecosystem's "telemetry must
    never break the run" contract.

    Args:
        operation: The :class:`~parrot_tools.business_automation.models.BusinessOperation`
            name this import registers against (selects the checkpoint dir).
        digest: The statement's ``statement_digest`` (selects the manifest).

    Returns:
        A sync ``(event, node_id, info) -> None`` callback.
    """

    def _listener(event: str, node_id: str, _info: Dict[str, Any]) -> None:
        if event != "node_completed":
            return
        match = _ROW_NODE_ID_RE.match(node_id)
        if match is None or match.group("digest") != digest:
            return
        try:
            completed = _read_completed_rows(operation, digest)
            completed.add(int(match.group("index")))
            manifest_path = _manifest_path_for(operation, digest)
            data = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
            data["completed_rows"] = sorted(completed)
            manifest_path.write_text(json.dumps(data, indent=2))
            manifest_path.chmod(0o600)
        except Exception:
            logger.exception(
                "Failed to record row completion for operation=%r digest=%r node=%r",
                operation,
                digest,
                node_id,
            )

    return _listener


def reconcile(bundle: ImportPlanBundle, registrations_out: int) -> Dict[str, Any]:
    """Compare rows-in vs registrations-out and report the delta.

    *registrations_out* counts only registrations from running *this*
    bundle's plan; rows already completed by a prior (resumed-from) run are
    added in automatically via :attr:`ImportPlanBundle.already_completed_rows`,
    so reconciliation always reflects the whole statement, not just the
    remainder a resumed plan actually executed.

    Args:
        bundle: The :class:`ImportPlanBundle` returned by
            :func:`build_import_plan`.
        registrations_out: Number of ``register_expense`` (or equivalent)
            invocations that actually succeeded in *this* run.

    Returns:
        ``{"rows_in", "registrations_out", "delta", "reconciled"}`` —
        ``reconciled`` is ``True`` only when ``delta == 0``.
    """
    total_registered = bundle.already_completed_rows + registrations_out
    delta = bundle.row_count - total_registered
    return {
        "rows_in": bundle.row_count,
        "registrations_out": total_registered,
        "delta": delta,
        "reconciled": delta == 0,
    }
