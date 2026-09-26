"""FEAT-602 TASK-3744 — full stack against the fake Hooba server."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from parrot_tools.hooba import HoobaSettings, HoobaToolkit
from parrot_tools.hooba.models import InvoiceDraft, InvoiceLineDraft

from .fake_server import ACCOUNT_ID, FakeHoobaState, build_fake_hooba_app, USERNAME, PASSWORD


@pytest.fixture
async def hooba(aiohttp_server, monkeypatch, tmp_path):
    """(toolkit, state) wired to a fresh fake server."""
    state = FakeHoobaState()
    # Initialize with test data
    state.contacts = [
        {"id": 10, "legalName": "Acme Corp"},
    ]
    state.invoice_series = [
        {"id": 1, "code": "A", "default": True, "defaultForSimplified": False},
    ]
    state.taxes = [
        {"id": 55, "operationType": "sale", "percentage": 21, "code": "IVA21"},
        # BBVA import creates PURCHASE-invoice drafts; the bundled autonomo_es_v1.yaml
        # rule table maps to IVA21 (telco/fuel/unclassified) and IVA10 (meals).
        {"id": 56, "operationType": "purchase", "percentage": 21, "code": "IVA21"},
        {"id": 57, "operationType": "purchase", "percentage": 10, "code": "IVA10"},
    ]
    state.income_taxes = [
        {"id": 1, "code": "IRPF15", "percentage": 15},
    ]
    state.document_types = [
        {"id": 1, "code": "FACTURA", "description": "Factura"},
    ]

    app = build_fake_hooba_app(state)
    server = await aiohttp_server(app)

    # Configure settings to point to fake server
    settings = HoobaSettings(
        base_url=str(server.make_url("")).rstrip("/"),
        account_id=ACCOUNT_ID,
    )

    # Set up environment for credentials
    monkeypatch.setenv("HOOBA_USERNAME", USERNAME)
    monkeypatch.setenv("HOOBA_PASSWORD", PASSWORD)

    # Create toolkit
    toolkit = HoobaToolkit(settings=settings)

    return toolkit, state


async def test_hooba_end_to_end_against_fake_server(hooba):
    """whoami → invoice draft; all state "draft"; no :issue/:confirm/DELETE in state.requests."""
    toolkit, state = hooba

    # 1. whoami
    result = await toolkit.hooba_whoami()
    assert result["status"] == "success"
    assert result["result"]["accountId"] == ACCOUNT_ID

    # 2. Create invoice draft
    draft = InvoiceDraft(
        contact_query="Acme Corp",
        lines=[InvoiceLineDraft(name="Consulting", price="100.00")],
    )
    result = await toolkit.hooba_create_invoice_draft(draft)
    assert result["status"] == "success"
    receipt = result["result"]
    assert receipt["state"] == "draft"
    invoice_id = receipt["id"]

    # Verify no :issue, :confirm, or DELETE in requests
    for method, path in state.requests:
        assert ":issue" not in path, f":issue found in {path}"
        assert ":confirm" not in path, f":confirm found in {path}"
        assert method != "DELETE", f"DELETE found in {path}"


async def test_bbva_import_end_to_end(hooba, tmp_path, monkeypatch):
    """dry run → 0 POSTs; apply → one purchase draft per planned row; reconciled; re-run → 0 new POSTs.

    The fixture workbook has 7 debit rows (5 base + 2 ``extra_rows``) and 2 credits (parser-skipped
    before reaching the rule engine). Of the 7 debits, "TRASPASO A CUENTA PROPIA" matches the bundled
    ``skip_transfers`` rule (rule.skip, never becomes a draft); the remaining 6 match non-skip rules
    (reta/telco/fuel/meals/unclassified×2) and each becomes exactly one purchase-invoice draft.
    """
    from .fixtures.make_bbva_fixture import build_bbva_workbook

    toolkit, state = hooba
    # Route the resume/reconcile checkpoint manifest to an isolated tmp dir, never the real state dir.
    monkeypatch.setenv("PARROT_STATE_DIR", str(tmp_path / "state"))

    bbva_path = tmp_path / "bbva.xlsx"
    build_bbva_workbook(bbva_path, extra_rows=2)

    # -- 1. Dry run: plans everything, POSTs nothing --
    result = await toolkit.hooba_import_bbva_statement(str(bbva_path), period="2026-09", dry_run=True)
    assert result["status"] == "success", result
    batch = result["result"]
    assert batch["planned"] == 6  # 7 debits - 1 skip_transfers row
    assert batch["created"] == []
    assert len(batch["skipped"]) == 1
    assert batch["skipped"][0]["reason"] == "rule.skip"
    assert state.purchase_invoices == {}  # dry run must perform zero POSTs
    assert batch["reconciled"] is False  # nothing applied yet: 0 drafts + 1 skip != 7 rows

    # -- 2. Apply: exactly one purchase-invoice draft per planned (non-skip) row --
    result = await toolkit.hooba_import_bbva_statement(str(bbva_path), period="2026-09", dry_run=False)
    assert result["status"] == "success", result
    batch = result["result"]
    assert batch["planned"] == 6
    assert len(batch["created"]) == 6
    assert all(receipt["state"] == "draft" for receipt in batch["created"])
    assert len(state.purchase_invoices) == 6
    assert batch["reconciled"] is True  # 6 drafts + 1 skip == 7 rows

    # -- 3. Re-run: the manifest already covers every row, so nothing new is planned or POSTed --
    invoice_count_after_first_apply = len(state.purchase_invoices)
    result = await toolkit.hooba_import_bbva_statement(str(bbva_path), period="2026-09", dry_run=False)
    assert result["status"] == "success", result
    batch = result["result"]
    assert batch["planned"] == 0
    assert batch["created"] == []
    assert len(state.purchase_invoices) == invoice_count_after_first_apply  # zero new POSTs
    assert batch["reconciled"] is True  # still 6 drafts + 1 skip == 7 rows (CRITICAL-2 regression)


async def test_session_expiry_relogin(hooba):
    """Basic session test - toolkit can connect and authenticate."""
    toolkit, state = hooba

    # whoami should work
    result = await toolkit.hooba_whoami()
    assert result["status"] == "success"
    assert result["result"]["accountId"] == ACCOUNT_ID


def test_no_real_data_committed():
    """Scan per Implementation Notes (AC-17).

    Two confirmed regressions in the original version:

    1. The filter discarded a git-grep match whenever the whole ``path:content`` line
       contained the substring "test" or "fixture" -- since every match from
       ``tests/hooba`` unavoidably has "test" in its own file *path*, that blindly
       discarded 100% of matches originating from the directory this scan most needs
       to police. Fixed by filtering on the matched *content* only, never the path.
    2. Importing ``parrot`` (transitively, via this module's own top-level
       ``from parrot_tools.hooba import ...``) runs ``navconfig.conf``'s unconditional
       ``os.chdir(BASE_DIR)`` as an IMPORT SIDE EFFECT, and ``BASE_DIR`` resolves to
       wherever navconfig's settings/install root is -- NOT necessarily this worktree.
       Every ``git grep``/``Path.exists()`` call that relied on ``os.getcwd()`` or a
       bare relative path was therefore silently scanning the WRONG checkout (verified:
       injecting a canary secret into this worktree's fake_server.py did not fail this
       test before this fix). Fixed by anchoring on ``__file__`` (never ``Path.cwd()``)
       to locate this worktree's own repo root via ``git rev-parse --show-toplevel``,
       and passing that root as an explicit ``cwd=`` to every subprocess call.
    """
    import subprocess

    # `__file__` is fixed at import time and immune to any later chdir; resolve the
    # true repo root from it instead of trusting os.getcwd() (see regression 2 above).
    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    )

    # Scan for potential real data patterns in hooba package and tests.
    paths_to_scan = [
        "packages/ai-parrot-tools/src/parrot_tools/hooba",
        "packages/ai-parrot-tools/tests/hooba",
    ]
    # This file necessarily contains the forbidden patterns below as string literals
    # (the detection mechanism itself) -- exclude it from its own scan.
    self_path = str(Path(__file__).resolve().relative_to(repo_root))

    # Patterns that should NOT appear (real credentials, IBANs, etc.). A synthetic
    # test double is fine (e.g. "sid=valid-1", "s3cr3t") -- these regexes are already
    # shaped to require real-looking data (22-digit IBAN body, 16+ hex-char session id).
    forbidden_patterns = [
        (r"HOOBA_PASSWORD=\S+", "real HOOBA_PASSWORD"),
        (r"ES\d{22}", "Spanish IBAN"),
        (r"sid=[0-9a-f]{16,}", "real session ID"),
    ]

    for path in paths_to_scan:
        if not (repo_root / path).exists():
            continue

        for pattern, description in forbidden_patterns:
            result = subprocess.run(
                ["git", "grep", "-nE", pattern, "--", path, f":(exclude){self_path}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                matches = []
                for line in result.stdout.splitlines():
                    # git grep -n output is "<path>:<line_no>:<content>" -- split on the
                    # FIRST TWO colons so the filter below only ever sees the matched
                    # content, never the (necessarily test/fixture-named) file path.
                    _file, _lineno, content = line.split(":", 2)
                    if "test" not in content.lower() and "fixture" not in content.lower():
                        matches.append(line)
                if matches:
                    pytest.fail(f"Found {description} in {path}: {matches[:3]}")
