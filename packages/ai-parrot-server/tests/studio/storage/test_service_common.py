"""FEAT-621 M5 foundation — limits, allowlists, gate, validators (DB-free)."""
import pytest

from parrot.handlers.studio.storage import services
from parrot.handlers.studio.storage.models import (
    StudioAgentDefinition,
    StudioAssetInput,
    StudioAssetTooLarge,
    StudioPartition,
    StudioToolingRefused,
)
from parrot.handlers.studio.storage.services import _common
from parrot.handlers.studio.storage.services._common import (
    StudioBinaryAssetRefused,
    StudioClassAllowlist,
    StudioLimits,
    StudioToolingGate,
    StudioValidationError,
    validate_asset_input,
    validate_definition_for,
)

ACME = StudioPartition("acme")
LIMITS = StudioLimits()


def _asset(kind="identity", name="role.md", content="x", content_type="text/markdown"):
    return StudioAssetInput(kind=kind, name=name, content=content, content_type=content_type)


def test_limits_per_kind():
    assert validate_asset_input(LIMITS, _asset(content="a" * LIMITS.identity_max)) == LIMITS.identity_max
    with pytest.raises(StudioAssetTooLarge) as exc:
        validate_asset_input(LIMITS, _asset(content="a" * (LIMITS.identity_max + 1)))
    assert exc.value.code == "asset_too_large"
    assert validate_asset_input(LIMITS, _asset("kb", "n.md", "a" * LIMITS.kb_max)) == LIMITS.kb_max
    with pytest.raises(StudioAssetTooLarge):
        validate_asset_input(LIMITS, _asset("kb", "n.md", "a" * (LIMITS.kb_max + 1)))
    with pytest.raises(StudioAssetTooLarge):
        validate_asset_input(LIMITS, _asset("skills", "s.pdf.md", "a" * (LIMITS.skills_max + 1)))


def test_limits_size_counts_utf8_bytes():
    with pytest.raises(StudioAssetTooLarge):
        validate_asset_input(LIMITS, _asset(content="é" * (LIMITS.identity_max // 2 + 1)))


def test_limits_from_config(monkeypatch):
    values = {"STUDIO_ASSET_MAX_BYTES_KB": 10}
    monkeypatch.setattr(_common.config, "getint", lambda key, fallback=None: values.get(key, fallback))
    limits = StudioLimits.from_config()
    assert limits.kb_max == 10 and limits.identity_max == 64 * 1024 and limits.agent_total_max == 4 * 1024 * 1024


def test_binary_content_type_refused():
    with pytest.raises(StudioBinaryAssetRefused) as exc:
        validate_asset_input(LIMITS, _asset(content_type="application/pdf"))
    assert exc.value.code == "binary_assets_unsupported" and exc.value.status == 415


@pytest.mark.parametrize(
    "name",
    ["../role.md", "a/../../b.md", "/etc/passwd", "a\\b.md", "role\x00.md", "", "a//b.md", "./role.md", "a" * 300],
)
def test_unsafe_asset_names_refused(name):
    with pytest.raises(StudioValidationError) as exc:
        validate_asset_input(LIMITS, _asset("skills", name))
    assert exc.value.code == "invalid_asset_name"


def test_kind_filename_rules_apply():
    with pytest.raises(StudioValidationError):
        validate_asset_input(LIMITS, _asset("identity", "unknown.md"))
    with pytest.raises(StudioValidationError):
        validate_asset_input(LIMITS, _asset("kb", "notes.pdf"))
    with pytest.raises(StudioValidationError) as exc:
        validate_asset_input(LIMITS, _asset("skills", "s.md", "no frontmatter"))
    assert exc.value.code == "invalid_skill"


def test_class_allowlist_tenant_vs_global():
    definition = StudioAgentDefinition(bot_class="Foo")
    with pytest.raises(StudioValidationError) as exc:
        validate_definition_for(ACME, definition)
    assert exc.value.code == "bot_class_not_allowed"
    validate_definition_for(StudioPartition.GLOBAL, definition)
    validate_definition_for(ACME, definition, allowlist=StudioClassAllowlist(["Foo"]))
    validate_definition_for(ACME, StudioAgentDefinition(bot_class="BasicBot"))


def test_tenant_config_keys_allowlist():
    definition = StudioAgentDefinition(config={"max_retries": 3})
    with pytest.raises(StudioValidationError) as exc:
        validate_definition_for(ACME, definition)
    assert exc.value.code == "unsupported_config_key" and exc.value.status == 422
    validate_definition_for(StudioPartition.GLOBAL, definition)


def test_visibility_domain():
    definition = StudioAgentDefinition()
    validate_definition_for(ACME, definition, visibility="tenant")
    validate_definition_for(ACME, definition, visibility="groups", allowed_groups=["g"])
    with pytest.raises(StudioValidationError):
        validate_definition_for(ACME, definition, visibility="public")
    with pytest.raises(StudioValidationError):
        validate_definition_for(StudioPartition.GLOBAL, definition, visibility="tenant")


def test_gate_maps_refusal(monkeypatch):
    from parrot.tools import tooling_policy
    from parrot.tools.spec import NormalizedTooling

    def _refuse(app, tooling, *, subject):
        assert subject.tenant == "acme" and subject.phase == "write"
        raise tooling_policy.TenantToolingRefused("endpoint_not_allowed", item="srv")

    monkeypatch.setattr(tooling_policy, "enforce_tenant_tooling", _refuse)
    with pytest.raises(StudioToolingRefused) as exc:
        StudioToolingGate({}).enforce(ACME, NormalizedTooling(), agent_id=None, actor="u", phase="write")
    assert exc.value.code == "tooling_not_permitted" and exc.value.item == "srv"


def test_normalized_tooling_for_rows():
    from datetime import datetime, timezone

    from parrot.handlers.studio.storage.models import StudioToolingRecord

    now = datetime.now(timezone.utc)
    rows = [
        StudioToolingRecord(None, "mcp", "srv", 0, {"transport": "http", "url": "https://x/"}, {}, None, now),
        StudioToolingRecord(None, "toolkit", "jira", 0, {"params": {"a": 1}}, {}, None, now),
    ]
    tooling = _common.normalized_tooling_for(StudioAgentDefinition(tools=["calc"]), rows)
    assert tooling.tools == ["calc"]
    assert [t.slug for t in tooling.toolkits] == ["jira"] and tooling.toolkits[0].params == {"a": 1}
    assert [m.name for m in tooling.mcp_servers] == ["srv"]


def test_runtime_dir_not_under_agents_dir(monkeypatch, tmp_path):
    from parrot import conf

    monkeypatch.setattr(conf, "AGENTS_DIR", tmp_path / "agents")
    monkeypatch.setattr(_common.config, "get", lambda key, *a, **k: str(tmp_path / "agents" / "rt"))
    with pytest.raises(StudioValidationError):
        _common.studio_runtime_dir()
    monkeypatch.setattr(_common.config, "get", lambda key, *a, **k: str(tmp_path / "rt"))
    assert _common.studio_runtime_dir() == tmp_path / "rt"
    monkeypatch.setattr(_common.config, "get", lambda key, *a, **k: None)
    assert _common.studio_runtime_dir().name.startswith("parrot-studio-")


def test_lazy_exports():
    assert services.StudioLimits is StudioLimits
    assert set(services.__all__) >= {"StudioAgentService", "StudioAssetService", "StudioServices"}
    with pytest.raises(AttributeError):
        services.Nope  # noqa: B018
