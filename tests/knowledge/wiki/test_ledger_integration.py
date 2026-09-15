"""FEAT-566 core integration and wiki regression gate (spec §§4-5).

Cross-component integration: LedgerLog/LedgerIndex/LedgerService, the
FederatedWikiStore overlay routing (Module 13), and SDDGraphIngest all
exercised together against real stores — not mocks. A second gate re-runs
the broader wiki suite and records evidence, protecting unaffected wiki
behavior.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.ledger.index import LedgerIndex
from parrot.knowledge.wiki.ledger.log import LedgerLog
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest
from parrot.knowledge.wiki.ledger.service import LedgerService
from parrot.knowledge.wiki.ledger.store import LedgerStore
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, SQLiteWikiStore, WikiPageRecord

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def shared_root(tmp_path):
    """A shared root with a local wiki plane (one real sym: page) and a ledger plane."""
    root = tmp_path / "shared"
    root.mkdir()

    wiki_dir = root / ".parrot" / "wiki"
    wiki_dir.mkdir(parents=True)
    local_store = SQLiteWikiStore(
        wiki_dir / "wiki.db",
        wiki_name="local",
        sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0),
    )
    return root, local_store


def _ledger_service(root: Path) -> LedgerService:
    """Build a LedgerService pointed directly at root's ledger dir (bypasses git detection)."""
    ledger_dir = root / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    store = LedgerStore(
        ledger_dir / "ledger.db", wiki_name="ledger", sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0)
    )
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    index = LedgerIndex(store, log)
    return LedgerService(index, store, log, root)


async def _federated(local_store: SQLiteWikiStore, ledger_service: LedgerService) -> FederatedWikiStore:
    """Mount the ledger as a read-only overlay, exactly as create_wiki_mcp_server does."""
    ledger_dir = ledger_service.shared_root / ".parrot" / "ledger"
    config = WikiNamespaceConfig(
        store=str(ledger_dir),
        overlay_prefixes=["issue", "task", "spec", "insight"],
    )
    handle = NamespaceHandle(name="ledger", store=ledger_service.store, config=config, storage_dir=ledger_dir)
    return FederatedWikiStore(local_store, "local", [handle], [])


class TestLedgerCoreIntegration:
    async def test_full_lifecycle_yields_consistent_log_and_index_state(self, shared_root):
        root, _local_store = shared_root
        service = _ledger_service(root)

        issue_id = await service.open_issue(
            title="Full lifecycle issue", body="b", severity="major", discovered_from="task:TASK-1"
        )
        assert await service.claim(issue_id, "task:TASK-2") is True
        assert await service.close_issue(issue_id, "fixed", actor="human:jesus") is True

        # Rebuild from the durable log alone and confirm identical final state.
        rebuilt = await service.index.rebuild()
        ready = await service.ready_work()
        async with service.store.ledger_transaction("read") as conn:
            from parrot.knowledge.wiki.ledger.index import _decode_issue_body

            async with conn.execute("SELECT body FROM pages WHERE concept_id = ?", (issue_id,)) as cur:
                row = await cur.fetchone()
            state = _decode_issue_body(row[0])

        assert rebuilt == 3  # opened, claimed, closed
        assert ready == []  # closed issues are not "ready"
        assert state["status"] == "closed"

    async def test_sdd_ingest_yields_spec_and_task_pages_with_edges(self, shared_root, tmp_path):
        root, _local_store = shared_root
        service = _ledger_service(root)

        (root / "sdd" / "specs").mkdir(parents=True)
        (root / "sdd" / "tasks" / "index").mkdir(parents=True)
        (root / "sdd" / "specs" / "demo-feature.spec.md").write_text(
            "---\ntype: feature\nbase_branch: dev\n---\n\n# Demo Feature\n", encoding="utf-8"
        )
        (root / "sdd" / "tasks" / "index" / "demo-feature.json").write_text(
            json.dumps(
                {
                    "feature": "demo-feature",
                    "feature_id": "FEAT-900",
                    "spec": "sdd/specs/demo-feature.spec.md",
                    "tasks": [
                        {"id": "TASK-9001", "title": "First", "status": "done", "depends_on": []},
                        {"id": "TASK-9002", "title": "Second", "status": "pending", "depends_on": ["TASK-9001"]},
                    ],
                }
            ),
            encoding="utf-8",
        )

        stats = await SDDGraphIngest(service.store, root).ingest_all()

        assert stats["specs"] == 1
        assert stats["tasks"] == 2
        async with service.store.ledger_transaction("read") as conn:
            async with conn.execute(
                "SELECT 1 FROM edges WHERE src = ? AND dst = ? AND rel = 'blocks'",
                ("task:TASK-9001", "task:TASK-9002"),
            ) as cur:
                blocks_row = await cur.fetchone()
        # TASK-9001 blocks TASK-9002 (the dependency blocks the dependent).
        assert blocks_row is not None

    async def test_scoped_context_returns_issue_touching_given_file(self, shared_root):
        root, _local_store = shared_root
        service = _ledger_service(root)
        await service.open_issue(
            title="Touches pkg/mod.py",
            body="b",
            discovered_from="task:TASK-1",
            about=["sym:pkg/mod.py#Func"],
        )

        context = await service.get_context(["pkg/mod.py"])

        assert "Touches pkg/mod.py" in context

    async def test_federated_bare_id_routes_to_ledger_overlay(self, shared_root):
        root, local_store = shared_root
        service = _ledger_service(root)
        issue_id = await service.open_issue(title="Overlay routed", body="b", discovered_from="task:TASK-1")

        federated = await _federated(local_store, service)
        page = await federated.get_page(issue_id)  # bare id, no "ledger::" prefix

        assert page is not None
        assert page["title"] == "Overlay routed"

    async def test_local_symbol_sees_inbound_ledger_edge(self, shared_root):
        root, local_store = shared_root
        service = _ledger_service(root)

        sym_id = "sym:pkg/mod.py#Func"
        await local_store.upsert_pages(
            [WikiPageRecord(concept_id=sym_id, title="Func", category="sym", body="def Func(): ...")]
        )
        issue_id = await service.open_issue(
            title="Bug in Func", body="b", discovered_from="task:TASK-1", about=[sym_id]
        )

        federated = await _federated(local_store, service)
        inbound = await federated.neighbors(sym_id, direction="in")

        inbound_ids = {row["concept_id"] for row in inbound}
        assert f"ledger::{issue_id}" in inbound_ids

    async def test_export_snapshot_reflects_final_ledger_state(self, shared_root, tmp_path):
        root, _local_store = shared_root
        service = _ledger_service(root)
        await service.open_issue(title="Snapshot me", body="b", discovered_from="task:TASK-1")
        dest = tmp_path / "issues.jsonl"

        changed = await service.export_snapshot(dest)

        assert changed is True
        rows = [json.loads(line) for line in dest.read_text(encoding="utf-8").splitlines()]
        assert any(row["title"] == "Snapshot me" for row in rows)


# Federation/tool/MCP/CLI/project/DevLoop regression suites named by spec §5,
# as explicit file paths rather than the whole `tests/knowledge/wiki/`
# directory: a directory target would re-collect THIS file, and the nested
# `TestWikiRegressionGate` test would then spawn another nested subprocess
# doing the same thing, recursively, until resources are exhausted. Explicit
# paths are also dramatically faster than the full ~1800-test directory,
# which matters because this runs nested inside an already-running pytest
# process.
_REGRESSION_SUITE_FILES = [
    "test_federation.py",
    "test_federation_overlay.py",
    "test_ledger_tools.py",
    "test_mcp_server_ledger.py",
    "test_mcp_server_structural.py",
    "test_cli_ledger.py",
    "test_cli_symbols.py",
    "test_project_shared_root.py",
    "test_project_namespaces.py",
    "test_devloop_ledger_context.py",
]


class TestWikiRegressionGate:
    def test_wiki_suite_passes_and_evidence_is_saved(self):
        """Required wiki suites pass; deterministic evidence is retained (spec §5)."""
        log_path = REPO_ROOT / "artifacts" / "logs" / "feat-566-ledger-core.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        targets = [f"tests/knowledge/wiki/{name}" for name in _REGRESSION_SUITE_FILES]
        result = subprocess.run(
            [sys.executable, "-m", "pytest", *targets, "-q", "-m", "not slow"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )

        log_path.write_text(
            "FEAT-566 Module 5 core integration + wiki regression gate\n"
            f"command: pytest {' '.join(targets)} -q -m 'not slow'\n"
            f"exit_code: {result.returncode}\n\n"
            "--- stdout (tail) ---\n"
            + "\n".join(result.stdout.splitlines()[-40:])
            + "\n\n--- stderr (tail) ---\n"
            + "\n".join(result.stderr.splitlines()[-20:])
            + "\n",
            encoding="utf-8",
        )

        assert result.returncode == 0, result.stdout[-4000:]
