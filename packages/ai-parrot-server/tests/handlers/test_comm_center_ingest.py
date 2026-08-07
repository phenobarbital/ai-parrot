"""Unit tests for CommCenter recipient ingestion (FEAT-417, Module 4)."""
import asyncio
import base64

import pytest
from parrot.services.comm_center.ingest import (
    MAX_FILE_SIZE,
    MAX_RECIPIENTS,
    ingest_recipients,
)


@pytest.fixture
def messy_csv(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text(
        "Nombre, E-Mail ,Teléfono,user,department\n"
        "Ana Gomez,ana@example.com,+34600000000,agomez,Sales\n"
    )
    return p


@pytest.fixture
def messy_xlsx(tmp_path):
    """Same data as ``messy_csv``, exercising the openpyxl engine."""
    pd = pytest.importorskip("pandas")
    p = tmp_path / "r.xlsx"
    df = pd.DataFrame(
        [
            {
                "Nombre": "Ana Gomez",
                " E-Mail ": "ana@example.com",
                "Teléfono": "+34600000000",
                "user": "agomez",
                "department": "Sales",
            }
        ]
    )
    df.to_excel(p, index=False, engine="openpyxl")
    return p


class TestIngest:
    """Tests covering all three transports, normalization, and caps."""

    def test_size_and_recipient_caps_match_convention(self):
        assert MAX_FILE_SIZE == 50 * 1024 * 1024
        assert MAX_RECIPIENTS == 10_000

    async def test_columns_normalized(self, messy_csv):
        rows = await ingest_recipients(file_path=messy_csv)
        assert rows[0].name == "Ana Gomez"
        assert rows[0].email == "ana@example.com"
        assert rows[0].phone == "+34600000000"
        assert rows[0].username == "agomez"

    async def test_extra_columns_preserved(self, messy_csv):
        rows = await ingest_recipients(file_path=messy_csv)
        assert rows[0].extra["department"] == "Sales"

    async def test_transports_agree(self, messy_csv):
        via_file = await ingest_recipients(file_path=messy_csv)
        via_b64 = await ingest_recipients(
            file_bytes=base64.b64decode(base64.b64encode(messy_csv.read_bytes())),
            filename="r.csv",
        )
        assert [r.email for r in via_file] == [r.email for r in via_b64]

    async def test_rejects_empty_file(self, tmp_path):
        p = tmp_path / "e.csv"
        p.write_text("name,email\n")
        with pytest.raises(ValueError, match="0 recipients|empty"):
            await ingest_recipients(file_path=p)

    async def test_rejects_unknown_columns(self, tmp_path):
        p = tmp_path / "u.csv"
        p.write_text("foo,bar\n1,2\n")
        with pytest.raises(ValueError):
            await ingest_recipients(file_path=p)

    async def test_recipient_cap(self, tmp_path):
        p = tmp_path / "big.csv"
        p.write_text(
            "name,email\n"
            + "".join(f"U{i},u{i}@e.com\n" for i in range(MAX_RECIPIENTS + 1))
        )
        with pytest.raises(ValueError, match="10000|10 000|cap"):
            await ingest_recipients(file_path=p)

    async def test_row_missing_name_is_skipped_not_fatal(self):
        """Regression guard (adversarial code review, FEAT-417): a single
        row with no usable 'name' must be skipped, never abort ingestion
        for the rest of the batch (RecipientIn.name is required, so
        constructing it directly would otherwise raise)."""
        rows = [
            {"name": "Ana", "email": "ana@example.com"},
            {"name": "", "email": "blank-name@example.com"},
            {"email": "no-name-key@example.com"},
        ]
        recipients = await ingest_recipients(rows=rows)
        assert len(recipients) == 1
        assert recipients[0].name == "Ana"

    async def test_all_rows_missing_name_raises(self):
        rows = [{"email": "a@e.com"}, {"email": "b@e.com"}]
        with pytest.raises(ValueError, match="name"):
            await ingest_recipients(rows=rows)

    async def test_does_not_block_event_loop(self, messy_csv, monkeypatch):
        """pandas must be called via asyncio.to_thread."""
        called = {}
        real = asyncio.to_thread

        async def spy(fn, *a, **k):
            called["yes"] = True
            return await real(fn, *a, **k)

        monkeypatch.setattr(asyncio, "to_thread", spy)
        await ingest_recipients(file_path=messy_csv)
        assert called.get("yes") is True

    async def test_reserved_column_warns(self, tmp_path):
        p = tmp_path / "res.csv"
        p.write_text("name,email,subject\nAna,a@e.com,Hi\n")
        _rows, warnings = await ingest_recipients(file_path=p, return_warnings=True)
        assert any("subject" in w for w in warnings)

    async def test_ingest_xlsx_via_openpyxl(self, messy_xlsx):
        """.xlsx fixture -> rows, matching spec §4 `test_ingest_xlsx_via_openpyxl`."""
        rows = await ingest_recipients(file_path=messy_xlsx)
        assert rows[0].name == "Ana Gomez"
        assert rows[0].email == "ana@example.com"
        assert rows[0].phone == "+34600000000"
        assert rows[0].username == "agomez"
        assert rows[0].extra["department"] == "Sales"
