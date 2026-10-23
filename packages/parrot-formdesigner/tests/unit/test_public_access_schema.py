"""FEAT-730 — public_access schema block."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from parrot_formdesigner.core import (
    CompletionAction,
    PublicAccessConfig,
    evaluate_open,
    normalize_key_value,
)
from parrot_formdesigner.core.persistence import FormPersistenceConfig
from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
from parrot_formdesigner.core.types import FieldType

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _form(**kwargs) -> FormSchema:
    fields = [
        FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
        FormField(field_id="group", field_type=FieldType.GROUP, label="Group"),
        FormField(field_id="doc", field_type=FieldType.FILE, label="Doc"),
    ]
    return FormSchema(
        form_id="pub",
        title="Pub",
        sections=[FormSection(section_id="s1", fields=fields)],
        **kwargs,
    )


def test_public_access_defaults_none():
    """A form without the block round-trips with public_access None."""
    form = _form()
    assert form.public_access is None
    dumped = form.model_dump(mode="json")
    assert dumped["public_access"] is None
    assert FormSchema.model_validate(dumped).public_access is None


def test_public_access_round_trip():
    form = _form(public_access={"max_responses": 3, "unique_key_field": "email"})
    again = FormSchema.model_validate(form.model_dump(mode="json"))
    assert again.public_access.max_responses == 3
    assert again.public_access.unique_key_field == "email"


@pytest.mark.parametrize(
    "url", ["http://x.com/a", "javascript:alert(1)", "data:text/html,x", "/relative", "https://"]
)
def test_redirect_requires_https_rejects(url):
    with pytest.raises(ValidationError):
        CompletionAction(mode="redirect", redirect_url=url)


def test_redirect_requires_https_missing_url_and_ok():
    with pytest.raises(ValidationError):
        CompletionAction(mode="redirect")
    ok = CompletionAction(mode="redirect", redirect_url="https://example.com/thanks")
    assert ok.redirect_url == "https://example.com/thanks"
    with pytest.raises(ValidationError):  # validated in any mode
        CompletionAction(mode="message", redirect_url="http://example.com")


def test_closes_at_naive_rejected():
    with pytest.raises(ValidationError):
        PublicAccessConfig(closes_at=datetime(2026, 1, 1, 12, 0))
    cfg = PublicAccessConfig(closes_at=datetime(2026, 1, 1, 14, 0, tzinfo=timezone(timedelta(hours=2))))
    assert cfg.closes_at == NOW
    assert cfg.closes_at.utcoffset() == timedelta(0)


def test_unique_key_must_exist_and_be_scalar():
    for bad in ("nope", "group", "doc"):
        with pytest.raises(ValidationError, match=bad):
            _form(public_access={"unique_key_field": bad})
    assert _form(public_access={"unique_key_field": "email"}).public_access.unique_key_field == "email"


def test_cap_with_persistence_rejected():
    persistence = FormPersistenceConfig.model_validate(
        {"data": {"type": "postgres_table", "connection": "c", "schema_name": "s", "table": "t"}}
    )
    with pytest.raises(ValidationError, match="persistence"):
        _form(public_access={"max_responses": 5}, persistence=persistence)
    with pytest.raises(ValidationError, match="persistence"):
        _form(public_access={"unique_key_field": "email"}, persistence=persistence)
    # close-only policy is fine with persistence
    assert _form(public_access={"accepting_responses": False}, persistence=persistence).public_access


def test_evaluate_open():
    assert evaluate_open(None, now=NOW) is None
    assert evaluate_open(PublicAccessConfig(), now=NOW) is None
    assert evaluate_open(PublicAccessConfig(accepting_responses=False), now=NOW) == "form_closed"
    assert evaluate_open(PublicAccessConfig(closes_at=NOW - timedelta(seconds=1)), now=NOW) == "form_closed"
    assert evaluate_open(PublicAccessConfig(closes_at=NOW), now=NOW) == "form_closed"
    assert evaluate_open(PublicAccessConfig(closes_at=NOW + timedelta(seconds=1)), now=NOW) is None


def test_normalize_key_value():
    for blank in (None, "", "  ", [], {}):
        assert normalize_key_value(blank) is None
    assert normalize_key_value(" a@x.com ") == "a@x.com"
    assert normalize_key_value(5) == 5
    assert normalize_key_value(0) == 0
