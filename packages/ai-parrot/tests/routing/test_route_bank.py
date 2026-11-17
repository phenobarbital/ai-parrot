"""Unit tests for the routes.yaml loader (FEAT-755 TASK-4759)."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.registry.routing.route_bank import (
    ROUTES_FILENAME,
    RouteBankFile,
    agent_routes_path,
    load_route_bank,
    merge_route_banks,
    resolve_route_banks,
    tenant_routes_path,
)


@pytest.fixture
def agent_root_with_banks(tmp_path: Path) -> Path:
    """Build an agent bank, a tenant bank, and a reserved tenant directory."""
    root = tmp_path / "agent"
    (root / ROUTES_FILENAME).parent.mkdir(parents=True)
    (root / ROUTES_FILENAME).write_text(
        """version: 1
threshold: 0.9
margin: 0.1
routes:
  structured_chart:
    - agent chart
  a2ui:KPICard:
    - agent kpi
""",
        encoding="utf-8",
    )
    acme_bank = root / "tenants" / "acme" / ROUTES_FILENAME
    acme_bank.parent.mkdir(parents=True)
    acme_bank.write_text(
        """routes:
  structured_chart:
    - tenant chart
  a2ui:KPICard:
    - agent kpi
    - tenant kpi
""",
        encoding="utf-8",
    )
    (root / "tenants" / "skills").mkdir(parents=True)
    return root


class TestLoad:
    """Route-bank parsing and failure behavior."""

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        """A missing route bank is not an error."""
        assert load_route_bank(tmp_path / ROUTES_FILENAME) is None

    def test_valid_file_returns_model(self, tmp_path: Path) -> None:
        """A valid route bank is parsed into the declared schema."""
        path = tmp_path / ROUTES_FILENAME
        path.write_text("version: 1\nroutes:\n  structured_map:\n    - map it\n", encoding="utf-8")

        bank = load_route_bank(path)

        assert bank == RouteBankFile(version=1, routes={"structured_map": ["map it"]})

    @pytest.mark.parametrize(
        "content",
        [
            "routes: [unterminated",
            "routes: {}\nunknown: true\n",
        ],
    )
    def test_invalid_file_warns_and_returns_none(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        content: str,
    ) -> None:
        """Bad YAML and schema violations are warned about and skipped."""
        path = tmp_path / ROUTES_FILENAME
        path.write_text(content, encoding="utf-8")

        assert load_route_bank(path) is None
        assert f"Skipping route bank {path}" in caplog.text

    def test_read_error_warns_and_returns_none(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Filesystem errors satisfy the loader's never-raises contract."""
        path = tmp_path / ROUTES_FILENAME
        path.write_text("routes: {}", encoding="utf-8")

        def fail_read_text(self: Path, encoding: str) -> str:
            raise OSError("unreadable")

        monkeypatch.setattr(Path, "read_text", fail_read_text)

        assert load_route_bank(path) is None
        assert "unreadable" in caplog.text


class TestMerge:
    """Pure phrase-bank merge semantics."""

    def test_extend_preserves_order_and_deduplicates(self) -> None:
        """Default overlays append only unseen utterances."""
        base = {"structured_chart": ["base", "shared"], "structured_map": ["map"]}
        overlay = RouteBankFile(routes={"structured_chart": ["shared", "agent"], "a2ui:KPICard": ["kpi"]})

        assert merge_route_banks(base, overlay) == {
            "structured_chart": ["base", "shared", "agent"],
            "structured_map": ["map"],
            "a2ui:KPICard": ["kpi"],
        }

    def test_replace_substitutes_each_overlay_key(self) -> None:
        """A replace overlay substitutes present keys without dropping others."""
        base = {"structured_chart": ["base"], "structured_map": ["map"]}
        overlay = RouteBankFile(replace=True, routes={"structured_chart": ["replacement", "replacement"]})

        assert merge_route_banks(base, overlay) == {
            "structured_chart": ["replacement"],
            "structured_map": ["map"],
        }


class TestResolve:
    """Agent and tenant bank resolution."""

    def test_none_agent_root_returns_defaults_only(self) -> None:
        """The no-agent-directory path copies and de-duplicates defaults."""
        defaults = {"structured_chart": ["chart", "chart"]}

        resolved = resolve_route_banks(None, defaults=defaults, tenant_based=True)

        assert resolved.routes == {"structured_chart": ["chart"]}
        assert resolved.tenant_routes == {}

    def test_agent_and_tenant_banks_merge_in_order(self, agent_root_with_banks: Path) -> None:
        """Tenant banks inherit the already-merged global phrase bank."""
        defaults = {"structured_chart": ["default chart"], "structured_map": ["default map"]}

        resolved = resolve_route_banks(agent_root_with_banks, defaults=defaults, tenant_based=True)

        assert resolved.routes == {
            "structured_chart": ["default chart", "agent chart"],
            "structured_map": ["default map"],
            "a2ui:KPICard": ["agent kpi"],
        }
        assert resolved.tenant_routes == {
            "acme": {
                "structured_chart": ["default chart", "agent chart", "tenant chart"],
                "structured_map": ["default map"],
                "a2ui:KPICard": ["agent kpi", "tenant kpi"],
            }
        }
        assert resolved.threshold == 0.9
        assert resolved.margin == 0.1

    def test_tenant_based_false_skips_tenant_tree(self, agent_root_with_banks: Path) -> None:
        """Tenant discovery is disabled when tenancy is not configured."""
        resolved = resolve_route_banks(agent_root_with_banks, defaults={}, tenant_based=False)

        assert resolved.tenant_routes == {}

    def test_missing_or_invalid_tenant_bank_inherits_global(self, tmp_path: Path) -> None:
        """A valid tenant directory remains usable when its bank cannot load."""
        root = tmp_path / "agent"
        (root / "tenants" / "missing").mkdir(parents=True)
        invalid_path = root / "tenants" / "invalid" / ROUTES_FILENAME
        invalid_path.parent.mkdir(parents=True)
        invalid_path.write_text("extra: forbidden", encoding="utf-8")

        resolved = resolve_route_banks(root, defaults={"structured_map": ["map"]}, tenant_based=True)

        assert resolved.tenant_routes == {
            "invalid": {"structured_map": ["map"]},
            "missing": {"structured_map": ["map"]},
        }


class TestContainment:
    """Route-bank path containment."""

    @pytest.mark.parametrize("tenant", ["../escape", "routes", "skills"])
    def test_tenant_routes_path_rejects_invalid_or_reserved_name(self, tmp_path: Path, tenant: str) -> None:
        """Traversal and reserved tenant names fail before path access."""
        with pytest.raises(ValueError):
            tenant_routes_path(tmp_path / "agent", tenant)

    def test_agent_and_tenant_paths(self, tmp_path: Path) -> None:
        """Valid path helpers use the fixed filename and tenant layout."""
        root = tmp_path / "agent"

        assert agent_routes_path(root) == root / ROUTES_FILENAME
        assert tenant_routes_path(root, "acme") == root / "tenants" / "acme" / ROUTES_FILENAME
