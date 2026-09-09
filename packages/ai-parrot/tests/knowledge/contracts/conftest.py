"""Shared fixtures for the contracts integration suite (TASK-3054).

Synthetic English corpus (MSA, SOW, amendment, NDA, contradictory clauses),
generated DOCX / text-PDF / image-only-PDF equivalents, two tenants that
deliberately reuse the same slugs and node ids, frozen clocks, and live
service gates.

Live services are opt-in and explicit:

* Postgres — ``GRAPHINDEX_PG_DSN`` (no ``default_dsn`` fallback);
* ArangoDB — ``CONTRACTS_ARANGO_URL`` (plus user/password/prefix).

A missing service skips only its own suite and, per spec §4, does **not**
count as acceptance.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import pytest

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 9)

PG_DSN: Optional[str] = os.environ.get("GRAPHINDEX_PG_DSN")
ARANGO_URL: Optional[str] = os.environ.get("CONTRACTS_ARANGO_URL")
ARANGO_USER = os.environ.get("CONTRACTS_ARANGO_USER", "root")
ARANGO_PASSWORD = os.environ.get("CONTRACTS_ARANGO_PASSWORD", "")

requires_pg = pytest.mark.skipif(not PG_DSN, reason="live Postgres suites require an explicit GRAPHINDEX_PG_DSN")
requires_arango = pytest.mark.skipif(
    not ARANGO_URL,
    reason="live ArangoDB suites require an explicit CONTRACTS_ARANGO_URL",
)


# --------------------------------------------------------------------------
# Synthetic English corpus
# --------------------------------------------------------------------------

MSA_MARKDOWN = """# ACME Master Services Agreement

This Master Services Agreement is entered into between Troc Global Inc. and
ACME, Inc.

## Term

This Agreement is effective as of January 1, 2026 and continues for an
initial term of twelve (12) months.

## Renewal and Notice

The Agreement renews automatically for successive twelve (12) month periods
unless either party gives sixty (60) days written notice.

## Compliance

Vendor shall maintain SOC 2 Type II certification and must provide the
report annually.

## Insurance

Vendor shall carry cyber liability insurance of at least USD 5,000,000.

## Governing Law

This Agreement is governed by the laws of Delaware.

## Signatures

Signed by Jane Doe, CFO of ACME, Inc.
"""

SOW_MARKDOWN = """# ACME Statement of Work 1

This Statement of Work is issued under the ACME Master Services Agreement
between Troc Global Inc. and ACME, Inc.

## Scope

Vendor shall deliver the migration described in Appendix A.

## Reporting

Vendor shall report progress monthly.

## Signatures

Signed by Jane Doe, CFO of ACME, Inc.
"""

AMENDMENT_MARKDOWN = """# Amendment No. 1 to the ACME Master Services Agreement

This Amendment amends the ACME Master Services Agreement between Troc
Global Inc. and ACME, Inc.

## Term

This Amendment is effective as of July 1, 2026.

## Notice

The notice period is amended to thirty (30) days written notice.

## Signatures

Signed by Jane Doe, CFO of ACME, Inc.
"""

NDA_MARKDOWN = """# Zeta Mutual Non-Disclosure Agreement

This Agreement is entered into between Troc Global Inc. and Zeta LLC.

## Confidentiality

Each party shall protect the other's confidential information.

## Term

This Agreement is effective as of March 1, 2026.

## Signatures

Signed by Sam Roe, COO of Zeta LLC.
"""

#: Deliberately contradicts the MSA's sixty-day notice period.
CONTRADICTORY_MARKDOWN = """# ACME Side Letter

This Side Letter relates to the ACME Master Services Agreement between Troc
Global Inc. and ACME, Inc.

## Notice

Notwithstanding the Agreement, either party may terminate on five (5) days
notice.

## Compliance

Vendor shall maintain ISO 27001 certification.
"""

HEADINGLESS_TEXT = "\n\n".join(
    f"Paragraph {index}: the parties agree to the terms set out herein." for index in range(1, 8)
)


@pytest.fixture()
def corpus(tmp_path: Path) -> dict[str, Path]:
    """Write the synthetic corpus (markdown + TXT) to disk."""
    folder = tmp_path / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    paths = {
        "msa": folder / "acme-msa.md",
        "sow": folder / "acme-sow-1.md",
        "amendment": folder / "acme-amendment-1.md",
        "nda": folder / "zeta-nda.md",
        "contradictory": folder / "acme-side-letter.md",
        "headingless": folder / "acme-notes.txt",
    }
    paths["msa"].write_text(MSA_MARKDOWN, encoding="utf-8")
    paths["sow"].write_text(SOW_MARKDOWN, encoding="utf-8")
    paths["amendment"].write_text(AMENDMENT_MARKDOWN, encoding="utf-8")
    paths["nda"].write_text(NDA_MARKDOWN, encoding="utf-8")
    paths["contradictory"].write_text(CONTRADICTORY_MARKDOWN, encoding="utf-8")
    paths["headingless"].write_text(HEADINGLESS_TEXT, encoding="utf-8")
    return paths


@pytest.fixture()
def docx_document(tmp_path: Path) -> Path:
    """Generate a small real DOCX equivalent of the MSA."""
    docx = pytest.importorskip("docx")
    path = tmp_path / "documents" / "acme-msa.docx"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    document.add_heading("ACME Master Services Agreement", level=1)
    document.add_paragraph("This Master Services Agreement is entered into between Troc Global " "Inc. and ACME, Inc.")
    document.add_heading("Compliance", level=2)
    document.add_paragraph("Vendor shall maintain SOC 2 Type II certification.")
    document.save(str(path))
    return path


@pytest.fixture()
def text_pdf(tmp_path: Path) -> Path:
    """Generate a small real text PDF with two pages."""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "documents" / "acme-msa.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text(
        (72, 72),
        "ACME MASTER SERVICES AGREEMENT between Troc Global and ACME, Inc.",
    )
    second = document.new_page()
    second.insert_text((72, 72), "Vendor shall maintain SOC 2 Type II certification.")
    document.save(str(path))
    document.close()
    return path


@pytest.fixture()
def image_only_pdf(tmp_path: Path) -> Path:
    """Generate a scanned-style PDF with no extractable text."""
    pymupdf = pytest.importorskip("pymupdf")
    path = tmp_path / "documents" / "scanned.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(72, 72, 300, 300), fill=(0.2, 0.2, 0.2))
    document.save(str(path))
    document.close()
    return path


# --------------------------------------------------------------------------
# Live service gates
# --------------------------------------------------------------------------


@pytest.fixture()
async def pg_pool() -> AsyncIterator[Any]:
    """A pool against the explicitly configured Postgres."""
    if not PG_DSN:  # pragma: no cover - skipped by the marker
        pytest.skip("no GRAPHINDEX_PG_DSN")
    import asyncpg

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=1, max_size=6)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture()
async def temp_schema(pg_pool) -> AsyncIterator[str]:
    """A temporary catalog schema, dropped afterwards."""
    schema = f"contracts_it_{uuid.uuid4().hex[:8]}"
    try:
        yield schema
    finally:
        async with pg_pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture()
def arango_params() -> dict[str, Any]:
    """Connection parameters for the explicitly configured ArangoDB."""
    if not ARANGO_URL:  # pragma: no cover - skipped by the marker
        pytest.skip("no CONTRACTS_ARANGO_URL")
    from urllib.parse import urlparse

    parsed = urlparse(ARANGO_URL)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 8529,
        "username": ARANGO_USER,
        "password": ARANGO_PASSWORD,
        "database": "_system",
    }
