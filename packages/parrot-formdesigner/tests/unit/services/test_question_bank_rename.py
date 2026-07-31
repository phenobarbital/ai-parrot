"""Unit tests for FEAT-393 Module 12 — question bank field_id -> question_id rename.

Spec §4 Module 12 (TASK-2006). ``ReusableField``/``ReusableFieldRef`` are
renamed end to end (``field_id`` -> ``question_id``) since the bank id has
no relation to ``FormField.field_id``. Bank entries are templates: every
``resolve_ref()`` insertion mints a FRESH ``field_uid``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.question_bank import (
    _CREATE_TABLE_SQL,
    _INCREMENT_SQL,
    _INSERT_SQL,
    _SELECT_ALL_SQL,
    _SELECT_SQL,
    QuestionBankService,
    ReusableField,
    ReusableFieldRef,
)


@pytest.fixture
def bank() -> QuestionBankService:
    """QuestionBankService using in-memory (db=None) store, tenant='t1'."""
    return QuestionBankService(MagicMock(), tenant="t1")


def _text_field(field_id: str = "q1", label: str = "Q1") -> FormField:
    return FormField(field_id=field_id, field_type=FieldType.TEXT, label=label)


# ---------------------------------------------------------------------------
# Model roundtrip
# ---------------------------------------------------------------------------


def test_question_id_model_roundtrip() -> None:
    """ReusableField/ReusableFieldRef use question_id, not field_id/bank_field_id."""
    field = _text_field()
    entry = ReusableField(question_id="uuid-123", definition=field, tenant="t1")
    assert entry.question_id == "uuid-123"
    assert not hasattr(entry, "field_id")

    ref = ReusableFieldRef(question_id="uuid-123", overrides={"label": "New"})
    assert ref.question_id == "uuid-123"
    assert not hasattr(ref, "bank_field_id")


def test_ddl_and_sql_use_question_id() -> None:
    """DDL + all four SQL statements reference question_id, not field_id."""
    for sql in (_CREATE_TABLE_SQL, _INSERT_SQL, _SELECT_SQL, _SELECT_ALL_SQL, _INCREMENT_SQL):
        assert "question_id" in sql
    assert "UNIQUE(question_id, tenant)" in _CREATE_TABLE_SQL


# ---------------------------------------------------------------------------
# Fresh field_uid minting on resolve_ref
# ---------------------------------------------------------------------------


async def test_resolve_ref_mints_fresh_field_uid(bank: QuestionBankService) -> None:
    """Two resolve_ref() insertions of the same bank entry mint distinct field_uids."""
    created = await bank.create_field(_text_field())
    qid = created.question_id

    a = await bank.resolve_ref(ReusableFieldRef(question_id=qid))
    b = await bank.resolve_ref(ReusableFieldRef(question_id=qid))

    assert a.field_uid != b.field_uid


async def test_overrides_cannot_set_field_uid(bank: QuestionBankService) -> None:
    """overrides={'field_uid': ...} raises ValueError — never smuggled in."""
    created = await bank.create_field(_text_field())
    qid = created.question_id

    with pytest.raises(ValueError, match="field_uid"):
        await bank.resolve_ref(
            ReusableFieldRef(question_id=qid, overrides={"field_uid": "not-allowed"})
        )


async def test_increment_usage_by_question_id(bank: QuestionBankService) -> None:
    """increment_usage() accepts question_id and updates the in-memory entry."""
    created = await bank.create_field(_text_field())
    qid = created.question_id

    await bank.increment_usage(qid, forms=1, responses=1)
    updated = await bank.get_field(qid)
    assert updated is not None
    assert updated.usage_forms == 1
    assert updated.usage_responses == 1
