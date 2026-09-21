"""Backend resolution, PlanogramConfig new fields and ALTER-script checks (FEAT-574, spec Module 5)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import parrot_pipelines
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.backend import (
    DEFAULT_LLM_BACKEND,
    UNSET,
    ResolvedBackend,
    resolve_backend,
)

_PKG = Path(parrot_pipelines.__file__).parent
_MIN_CONFIG = {"brand": "X", "category": "Y", "aisle": {"name": "a"}, "shelves": []}

_ALTER_STATEMENTS = [
    "ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS slots_definition JSONB NULL;",
    "ALTER TABLE troc.planograms_configurations ADD COLUMN IF NOT EXISTS llm_backend TEXT NULL;",
    "ALTER TABLE troc.planograms_configurations ALTER COLUMN roi_detection_prompt DROP NOT NULL;",
    "ALTER TABLE troc.planograms_configurations ALTER COLUMN object_identification_prompt DROP NOT NULL;",
]


def _fake_client(name: str = "Anthropic", model: str | None = "claude-sonnet-5") -> SimpleNamespace:
    """A duck-typed client: the resolver only reads ``client_name`` and ``model``."""
    return SimpleNamespace(client_name=name, model=model)


@pytest.mark.parametrize(
    "llm, provider, model, config, expected",
    [
        # row 1 — instance wins over everything
        (_fake_client(), "google", "gemini-x", "google:gemini-y", ("anthropic", "claude-sonnet-5", "llm_instance")),
        # row 2 — string
        ("anthropic:claude-sonnet-5", UNSET, UNSET, "google:gemini-y", ("anthropic", "claude-sonnet-5", "llm_string")),
        ("anthropic", UNSET, UNSET, None, ("anthropic", None, "llm_string")),
        # row 3 — config, then package default
        (None, UNSET, UNSET, "anthropic:claude-sonnet-5", ("anthropic", "claude-sonnet-5", "config")),
        (None, UNSET, None, "anthropic:claude-sonnet-5", ("anthropic", "claude-sonnet-5", "config")),
        # row 4 / 5 — explicit provider, same vs different
        (None, "anthropic", UNSET, "anthropic:claude-sonnet-5", ("anthropic", "claude-sonnet-5", "constructor")),
        (None, "google", UNSET, "anthropic:claude-sonnet-5", ("google", None, "constructor")),
        # row 6 / 7
        (None, "Google", "gemini-x", "anthropic:claude-sonnet-5", ("google", "gemini-x", "constructor")),
        (None, UNSET, "claude-opus-4-8", "anthropic:claude-sonnet-5", ("anthropic", "claude-opus-4-8", "constructor")),
    ],
)
def test_backend_precedence_matrix(llm, provider, model, config, expected):
    """Every row of the FEAT-574 precedence matrix."""
    resolved = resolve_backend(llm, provider, model, config)
    assert isinstance(resolved, ResolvedBackend)
    assert (resolved.provider, resolved.model, resolved.origin) == expected


def test_package_default_is_google():
    """Nothing given ⇒ provider 'google', origin 'package_default', as_string() == DEFAULT_LLM_BACKEND."""
    resolved = resolve_backend(None, UNSET, UNSET, None)
    assert resolved.provider == "google"
    assert resolved.origin == "package_default"
    assert resolved.as_string() == DEFAULT_LLM_BACKEND
    assert ResolvedBackend(provider="anthropic", origin="config").as_string() == "anthropic"


@pytest.mark.parametrize("bad", ["", "   ", ":model", " : x"])
def test_invalid_backend_string_raises(bad):
    """An empty provider in the config backend or in an llm string is a ValueError."""
    with pytest.raises(ValueError):
        resolve_backend(None, UNSET, UNSET, bad)
    with pytest.raises(ValueError):
        resolve_backend(bad, UNSET, UNSET, None)


def test_planogram_config_optional_prompts_and_new_fields(tmp_path):
    """No prompts OK; slots_definition dict / str / Path stored as given; invalid llm_backend rejected."""
    cfg = PlanogramConfig(planogram_config=_MIN_CONFIG)
    assert cfg.roi_detection_prompt is None
    assert cfg.object_identification_prompt is None
    assert cfg.slots_definition is None
    assert cfg.llm_backend is None

    definition = {"shelves": [{"level": "top", "slots": []}]}
    assert PlanogramConfig(planogram_config=_MIN_CONFIG, slots_definition=definition).slots_definition == definition
    as_str = str(tmp_path / "missing.json")
    assert PlanogramConfig(planogram_config=_MIN_CONFIG, slots_definition=as_str).slots_definition == as_str
    as_path = tmp_path / "missing.json"
    assert PlanogramConfig(planogram_config=_MIN_CONFIG, slots_definition=as_path).slots_definition == as_path

    for good in ("anthropic:claude-sonnet-5", "google", "  google:gemini-x  "):
        assert PlanogramConfig(planogram_config=_MIN_CONFIG, llm_backend=good).llm_backend == good.strip()
    for bad in ("", "   ", ":model"):
        with pytest.raises(ValidationError):
            PlanogramConfig(planogram_config=_MIN_CONFIG, llm_backend=bad)


def test_table_sql_has_new_nullable_columns():
    """table.sql: new columns present, no 'prompt TEXT NOT NULL' left."""
    ddl = (_PKG / "table.sql").read_text()
    assert "slots_definition JSONB NULL" in ddl
    assert "llm_backend TEXT NULL" in ddl
    assert "prompt TEXT NOT NULL" not in ddl
    assert "roi_detection_prompt TEXT NULL" in ddl
    assert "object_identification_prompt TEXT NULL" in ddl


def test_alter_script_is_idempotent_text():
    """Executable statements of the ALTER script are exactly the four idempotent ones."""
    text = (_PKG / "alter_planograms_configurations_feat574.sql").read_text()
    statements = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("--")]
    assert statements == _ALTER_STATEMENTS
    assert all("IF NOT EXISTS" in s or "DROP NOT NULL" in s for s in statements)
