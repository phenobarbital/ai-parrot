"""Unit tests for QuestionBankService (FEAT-300 TASK-003)."""

import pytest
from unittest.mock import MagicMock

from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.question_bank import (
    QuestionBankService,
    ReusableField,
    ReusableFieldRef,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_storage():
    """Return a minimal MagicMock that satisfies FormStorage type checks."""
    return MagicMock()


@pytest.fixture
def bank(mock_storage):
    """QuestionBankService using in-memory (db=None) store, tenant='t1'."""
    return QuestionBankService(mock_storage, tenant="t1")


def _text_field(field_id: str = "q1", label: str = "Q1") -> FormField:
    return FormField(field_id=field_id, field_type=FieldType.TEXT, label=label)


# ---------------------------------------------------------------------------
# Import / basic structure
# ---------------------------------------------------------------------------


def test_import_works():
    """Public names are importable from services.question_bank."""
    assert QuestionBankService is not None
    assert ReusableField is not None
    assert ReusableFieldRef is not None


def test_import_from_services_package():
    """Names re-exported from services/__init__.py."""
    from parrot_formdesigner.services import QuestionBankService as QBS
    from parrot_formdesigner.services import ReusableField as RF
    from parrot_formdesigner.services import ReusableFieldRef as RFR
    assert QBS is QuestionBankService
    assert RF is ReusableField
    assert RFR is ReusableFieldRef


def test_reusable_field_model():
    """ReusableField is a valid Pydantic v2 model with required fields."""
    field = _text_field()
    entry = ReusableField(field_id="uuid-123", definition=field, tenant="t1")
    assert entry.field_id == "uuid-123"
    assert entry.definition.field_id == "q1"
    assert entry.usage_forms == 0
    assert entry.usage_responses == 0


def test_reusable_field_ref_model():
    """ReusableFieldRef is a valid Pydantic v2 model."""
    ref = ReusableFieldRef(bank_field_id="uuid-123", overrides={"label": "New"})
    assert ref.bank_field_id == "uuid-123"
    assert ref.overrides == {"label": "New"}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_question_bank_create_and_retrieve(bank):
    """create_field() mints a UUID; get_field() returns the same definition."""
    field = _text_field("q1", "Q1")
    created = await bank.create_field(field)

    assert isinstance(created, ReusableField)
    assert created.field_id  # minted UUID
    assert created.tenant == "t1"
    assert created.definition.field_id == "q1"

    fetched = await bank.get_field(created.field_id)
    assert fetched is not None
    assert fetched.definition.field_id == "q1"


async def test_question_bank_get_unknown_returns_none(bank):
    """get_field() returns None for an unknown ID."""
    result = await bank.get_field("does-not-exist")
    assert result is None


async def test_question_bank_list_fields_empty(bank):
    """list_fields() returns [] when bank is empty."""
    assert await bank.list_fields() == []


async def test_question_bank_list_fields_populated(bank):
    """list_fields() returns all created entries."""
    await bank.create_field(_text_field("q1", "Q1"))
    await bank.create_field(_text_field("q2", "Q2"))
    fields = await bank.list_fields()
    assert len(fields) == 2


# ---------------------------------------------------------------------------
# Usage counters
# ---------------------------------------------------------------------------


async def test_question_bank_usage_counter(bank):
    """increment_usage() increments both forms and responses counters."""
    field = _text_field()
    created = await bank.create_field(field)
    fid = created.field_id

    await bank.increment_usage(fid, forms=1, responses=2)
    updated = await bank.get_field(fid)
    assert updated is not None
    assert updated.usage_forms == 1
    assert updated.usage_responses == 2


async def test_question_bank_usage_counter_additive(bank):
    """Multiple increment_usage() calls accumulate."""
    created = await bank.create_field(_text_field())
    fid = created.field_id

    await bank.increment_usage(fid, forms=1, responses=0)
    await bank.increment_usage(fid, forms=0, responses=3)
    updated = await bank.get_field(fid)
    assert updated.usage_forms == 1
    assert updated.usage_responses == 3


async def test_question_bank_usage_counter_unknown_noop(bank):
    """increment_usage() on unknown ID does not raise."""
    await bank.increment_usage("no-such-id", forms=5, responses=10)  # no exception


# ---------------------------------------------------------------------------
# Resolve ref
# ---------------------------------------------------------------------------


async def test_question_bank_resolve_ref(bank):
    """resolve_ref() returns a FormField matching the bank definition."""
    field = _text_field("q1", "Original Label")
    created = await bank.create_field(field)

    resolved = await bank.resolve_ref(
        ReusableFieldRef(bank_field_id=created.field_id)
    )
    assert isinstance(resolved, FormField)
    assert resolved.field_id == "q1"
    assert resolved.label == "Original Label"


async def test_question_bank_resolve_ref_with_overrides(bank):
    """resolve_ref() applies overrides on top of the definition."""
    field = _text_field("q1", "Original")
    created = await bank.create_field(field)

    resolved = await bank.resolve_ref(
        ReusableFieldRef(
            bank_field_id=created.field_id,
            overrides={"label": "New Label"},
        )
    )
    assert resolved.label == "New Label"
    assert resolved.field_id == "q1"  # unchanged


async def test_question_bank_resolve_ref_does_not_mutate_bank(bank):
    """resolve_ref() deep-copies: the bank entry is never mutated."""
    field = _text_field("q1", "Original")
    created = await bank.create_field(field)
    fid = created.field_id

    await bank.resolve_ref(
        ReusableFieldRef(bank_field_id=fid, overrides={"label": "Mutated?"})
    )
    original = await bank.get_field(fid)
    assert original.definition.label == "Original"


async def test_question_bank_resolve_ref_unknown_raises(bank):
    """resolve_ref() raises KeyError for unknown bank_field_id."""
    with pytest.raises(KeyError):
        await bank.resolve_ref(ReusableFieldRef(bank_field_id="no-such-id"))
