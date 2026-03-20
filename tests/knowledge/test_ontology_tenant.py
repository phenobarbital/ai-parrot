"""Tests for tenant ontology manager."""
from pathlib import Path

import pytest
import yaml

from parrot.knowledge.ontology.schema import PropertyDef
from parrot.knowledge.ontology.tenant import TenantOntologyManager


@pytest.fixture
def ontology_dir(tmp_path: Path) -> Path:
    """Create a temp ontology directory with base + domain + client YAMLs."""
    # Base
    base = {
        "name": "base",
        "version": "1.0",
        "entities": {
            "Employee": {
                "collection": "employees",
                "key_field": "employee_id",
                "properties": [
                    {"employee_id": {"type": "string"}},
                    {"name": {"type": "string"}},
                ],
                "vectorize": ["name"],
            },
        },
        "relations": {},
        "traversal_patterns": {},
    }
    (tmp_path / "base.ontology.yaml").write_text(yaml.dump(base))

    # Domains dir
    domains = tmp_path / "domains"
    domains.mkdir()
    domain = {
        "name": "field_services",
        "extends": "base",
        "entities": {
            "Employee": {
                "extend": True,
                "properties": [
                    {"project_code": {"type": "string"}},
                ],
            },
            "Project": {
                "collection": "projects",
                "key_field": "project_id",
                "properties": [
                    {"project_id": {"type": "string"}},
                    {"name": {"type": "string"}},
                ],
                "vectorize": ["name"],
            },
        },
        "relations": {
            "assigned_to": {
                "from": "Employee",
                "to": "Project",
                "edge_collection": "assigned_to",
            },
        },
    }
    (domains / "field_services.ontology.yaml").write_text(yaml.dump(domain))

    # Clients dir
    clients = tmp_path / "clients"
    clients.mkdir()
    client = {
        "name": "epson",
        "extends": "field_services",
        "traversal_patterns": {
            "find_portal": {
                "description": "Find employee portal",
                "trigger_intents": ["my portal"],
                "query_template": "FOR v IN 1..2 OUTBOUND @uid assigned_to RETURN v",
                "post_action": "vector_search",
            },
        },
    }
    (clients / "epson.ontology.yaml").write_text(yaml.dump(client))

    return tmp_path


@pytest.fixture
def manager(ontology_dir: Path) -> TenantOntologyManager:
    return TenantOntologyManager(ontology_dir=ontology_dir)


class TestResolve:

    def test_resolve_base_only(self, manager):
        """Tenant with no domain/client file gets just the base."""
        ctx = manager.resolve("unknown_tenant")
        assert ctx.tenant_id == "unknown_tenant"
        assert "Employee" in ctx.ontology.entities
        assert len(ctx.ontology.entities) == 1  # Only base Employee

    def test_resolve_with_domain(self, manager):
        """Tenant with domain gets base + domain."""
        ctx = manager.resolve("unknown_tenant", domain="field_services")
        assert "Employee" in ctx.ontology.entities
        assert "Project" in ctx.ontology.entities
        assert "assigned_to" in ctx.ontology.relations
        # Employee should have extended properties
        emp = ctx.ontology.entities["Employee"]
        assert "project_code" in emp.get_property_names()

    def test_resolve_full_chain(self, manager):
        """Known tenant gets base + domain + client."""
        ctx = manager.resolve("epson", domain="field_services")
        assert ctx.tenant_id == "epson"
        assert "find_portal" in ctx.ontology.traversal_patterns
        assert "Project" in ctx.ontology.entities

    def test_arango_db_name(self, manager):
        ctx = manager.resolve("epson", domain="field_services")
        assert ctx.arango_db == "epson_ontology"

    def test_pgvector_schema(self, manager):
        ctx = manager.resolve("epson", domain="field_services")
        assert ctx.pgvector_schema == "epson"

    def test_missing_domain_skipped(self, manager):
        """Missing domain file is silently skipped."""
        ctx = manager.resolve("epson", domain="nonexistent_domain")
        # Should still work with base + client
        assert "Employee" in ctx.ontology.entities


class TestCache:

    def test_cache_hit(self, manager):
        ctx1 = manager.resolve("epson", domain="field_services")
        ctx2 = manager.resolve("epson")  # domain ignored on cache hit
        assert ctx1 is ctx2  # Same object

    def test_invalidate_specific(self, manager):
        manager.resolve("epson", domain="field_services")
        assert "epson" in manager.list_tenants()
        manager.invalidate("epson")
        assert "epson" not in manager.list_tenants()

    def test_invalidate_all(self, manager):
        manager.resolve("epson", domain="field_services")
        manager.resolve("unknown_tenant")
        assert len(manager.list_tenants()) == 2
        manager.invalidate()
        assert len(manager.list_tenants()) == 0

    def test_re_resolve_after_invalidate(self, manager):
        ctx1 = manager.resolve("epson", domain="field_services")
        manager.invalidate("epson")
        ctx2 = manager.resolve("epson", domain="field_services")
        assert ctx1 is not ctx2  # New object after invalidation

    def test_list_tenants(self, manager):
        assert manager.list_tenants() == []
        manager.resolve("epson", domain="field_services")
        manager.resolve("unknown_tenant")
        assert set(manager.list_tenants()) == {"epson", "unknown_tenant"}


class TestCustomTemplates:

    def test_custom_db_template(self, ontology_dir):
        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            db_template="custom_{tenant}_db",
        )
        ctx = mgr.resolve("acme")
        assert ctx.arango_db == "custom_acme_db"

    def test_custom_pgvector_template(self, ontology_dir):
        mgr = TenantOntologyManager(
            ontology_dir=ontology_dir,
            pgvector_schema_template="schema_{tenant}",
        )
        ctx = mgr.resolve("acme")
        assert ctx.pgvector_schema == "schema_acme"


class TestErrors:

    def test_no_yaml_files_raises(self, tmp_path):
        """Empty ontology dir raises FileNotFoundError."""
        mgr = TenantOntologyManager(ontology_dir=tmp_path)
        with pytest.raises(FileNotFoundError, match="No ontology YAML"):
            mgr.resolve("any_tenant")
