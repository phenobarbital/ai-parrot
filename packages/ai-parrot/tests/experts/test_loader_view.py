"""Tests for domain-expert bundle loading and name overlays (FEAT-778 M2)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from parrot.experts.loader import BUNDLED_EXPERTS_DIR, discover_expert_bundles, parse_expert_bundle
from parrot.experts.models import ExpertBundle, ExpertBundleError, ExpertManifest
from parrot.experts.view import ExpertView
from parrot.skills.tenancy import RESERVED_TENANT_NAMES, validate_tenant_id


def _fixture_bundle_root(expert_bundle: Path) -> Path:
    """Return the sample bundle directory created by the shared fixture."""
    return expert_bundle / "experts" / "sample-expert"


def _bundle(root: Path, *, global_only: bool = False, origin: str = "workspace") -> ExpertBundle:
    """Build a minimal in-memory bundle for overlay tests."""
    manifest = ExpertManifest.model_validate(
        {
            "name": "sample-expert",
            "display_name": "Sample Expert",
            "description": "Overlay test expert",
            "knowledge": [{"source": "wiki", "mode": "retrieval"}],
            "global_only": global_only,
        }
    )
    return ExpertBundle(
        manifest=manifest,
        root=root,
        identity_dir=root / "identity",
        origin=origin,
    )


def test_discover_ignores_dirs_without_manifest(tmp_path: Path) -> None:
    """Discovery is non-recursive and silently ignores directories without manifests."""
    (tmp_path / "ordinary-dir").mkdir()
    (tmp_path / ".hidden").mkdir()
    nested = tmp_path / "container" / "nested-expert"
    nested.mkdir(parents=True)
    (nested / "expert.yaml").write_text("invalid: nested", encoding="utf-8")

    bundles, skipped = discover_expert_bundles(tmp_path)

    assert bundles == []
    assert skipped == []


def test_bundle_name_must_match_dir(expert_bundle: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A manifest whose name differs from its directory is rejected and reported as skipped."""
    bundle_root = _fixture_bundle_root(expert_bundle)
    manifest_path = bundle_root / "expert.yaml"
    manifest_path.write_text(manifest_path.read_text(encoding="utf-8").replace("sample-expert", "other-expert", 1))

    with pytest.raises(ExpertBundleError, match="does not match bundle directory"):
        parse_expert_bundle(bundle_root)

    with caplog.at_level(logging.WARNING, logger="parrot.experts.loader"):
        bundles, skipped = discover_expert_bundles(expert_bundle / "experts")

    assert bundles == []
    assert len(skipped) == 1
    assert skipped[0]["path"] == str(bundle_root)
    assert "does not match bundle directory" in skipped[0]["reason"]
    assert "Skipping expert bundle" in caplog.text


def test_identity_dollar_placeholder_rejected(expert_bundle: Path) -> None:
    """Identity fields cannot contain string.Template placeholders."""
    bundle_root = _fixture_bundle_root(expert_bundle)
    (bundle_root / "identity" / "role.md").write_text("You are $role.", encoding="utf-8")

    with pytest.raises(ExpertBundleError, match=r"role\.md.*\$"):
        parse_expert_bundle(bundle_root)


def test_bundle_without_rules_loads_with_warning(
    expert_bundle: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing expert governance is optional and emits exactly one warning."""
    bundle_root = _fixture_bundle_root(expert_bundle)
    (bundle_root / "rules" / "governance.md").unlink()

    with caplog.at_level(logging.WARNING, logger="parrot.experts.loader"):
        bundle = parse_expert_bundle(bundle_root)

    records = [record for record in caplog.records if record.name == "parrot.experts.loader"]
    assert bundle.rules is None
    assert len(records) == 1
    assert records[0].getMessage() == (
        "expert sample-expert: no rules/governance.md — org/team/project rules still apply"
    )


def test_tenant_shadows_global_unless_global_only(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Narrower bundles replace ordinary base bundles but cannot replace global-only bundles."""
    base = _bundle(tmp_path / "bundled", origin="bundled")
    tenant = _bundle(tmp_path / "tenant")

    view = ExpertView([base], [tenant], label="tenant:acme")

    assert view.resolve("sample-expert") is tenant
    assert view.bundles() == [tenant]
    assert view.shadowing == {"sample-expert": str(tenant.root)}

    locked = _bundle(tmp_path / "locked", global_only=True, origin="bundled")
    with caplog.at_level(logging.WARNING, logger="parrot.experts.view"):
        locked_view = ExpertView([locked], [tenant], label="tenant:acme")

    assert locked_view.resolve("sample-expert") is locked
    assert locked_view.shadowing == {}
    assert "global_only" in caplog.text
    assert "tenant:acme" in caplog.text


def test_reserved_names_include_experts() -> None:
    """Every new top-level expert directory name is reserved for tenant ids."""
    expected = {"experts", "knowledge", "governance"}

    assert expected <= RESERVED_TENANT_NAMES
    for name in expected:
        with pytest.raises(ValueError, match="Reserved tenant id"):
            validate_tenant_id(name)


def test_bundled_dir_resolves() -> None:
    """The bundled expert resource resolves to the package marker directory."""
    assert BUNDLED_EXPERTS_DIR.is_dir()
    assert BUNDLED_EXPERTS_DIR.name == "bundled"
    assert (BUNDLED_EXPERTS_DIR / "__init__.py").is_file()
