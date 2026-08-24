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
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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


@dataclass
class ImportPlanBundle:
    """The constructed :class:`ExecutionPlan` plus its :class:`ImportRun`
    discriminator (Decision D3) and row count (for reconciliation)."""

    plan: ExecutionPlan
    import_run: ImportRun
    row_count: int


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
        An :class:`ImportPlanBundle` with the plan, its ``ImportRun``, and
        the row count (for reconciliation via :func:`reconcile`).
    """
    digest = compute_statement_digest(xlsx_path)
    import_run = ImportRun(statement_digest=digest, period=period, started_at=datetime.now(timezone.utc))

    rows = await _load_expense_rows(xlsx_path, client_column, amount_column)

    nodes: List[PlanNode] = []
    previous_id: Optional[str] = None
    for i, row in enumerate(rows):
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

    plan = ExecutionPlan(
        name=f"expense-import-{digest}",
        objective=(f"Register {len(rows)} expense(s) from a bank statement for period {period}"),
        nodes=nodes,
        metadata=PlanMetadata(max_parallel_tasks=1),
    )

    _write_import_manifest(operation, plan, import_run, rows_in=len(rows))

    return ImportPlanBundle(plan=plan, import_run=import_run, row_count=len(rows))


def _write_import_manifest(operation: str, plan: ExecutionPlan, import_run: ImportRun, *, rows_in: int) -> Path:
    """Persist a small, permission-hardened import manifest.

    This is this module's own audit/reconciliation record — independent of
    ``AgentsFlow``'s own (disabled, FEAT-399) flow-level checkpointing.
    File mode ``0600`` (Decision D3): checkpoints contain client names.
    """
    checkpoint_dir = checkpoint_dir_for(operation)
    manifest_path = checkpoint_dir / f"{plan.name}.import.json"
    manifest_path.write_text(
        json.dumps(
            {
                "plan_name": plan.name,
                "operation": operation,
                "statement_digest": import_run.statement_digest,
                "period": import_run.period,
                "started_at": import_run.started_at.isoformat(),
                "rows_in": rows_in,
            },
            indent=2,
        )
    )
    manifest_path.chmod(0o600)
    return manifest_path


def reconcile(bundle: ImportPlanBundle, registrations_out: int) -> Dict[str, Any]:
    """Compare rows-in vs registrations-out and report the delta.

    Args:
        bundle: The :class:`ImportPlanBundle` returned by
            :func:`build_import_plan`.
        registrations_out: Number of ``register_expense`` (or equivalent)
            invocations that actually succeeded.

    Returns:
        ``{"rows_in", "registrations_out", "delta", "reconciled"}`` —
        ``reconciled`` is ``True`` only when ``delta == 0``.
    """
    delta = bundle.row_count - registrations_out
    return {
        "rows_in": bundle.row_count,
        "registrations_out": registrations_out,
        "delta": delta,
        "reconciled": delta == 0,
    }
