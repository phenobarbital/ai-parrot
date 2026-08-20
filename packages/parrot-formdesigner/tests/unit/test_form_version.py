"""Unit tests for FormVersionService (FEAT-300 TASK-004)."""

from datetime import datetime, timezone

import pytest

from parrot_formdesigner.api._utils import _bump_version
from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services.form_version import (
    FormVersionService,
    VersionMeta,
    _bump,
    _parse_major_minor,
)
from parrot_formdesigner.services.registry import FormRegistry, FormStorage
from parrot_formdesigner.services.storage import PostgresFormStorage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_form(
    form_id: str = "form1",
    version: str = "1.0",
    # FEAT-389: fixed default so independently-instantiated fixtures (e.g.
    # the `svc`/`form` pair below) referring to "the same conceptual form"
    # share one form_uid — the registry/storage identity key — the same
    # way they already share the default form_id slug.
    form_uid: str = "11111111-1111-1111-1111-111111111111",
) -> FormSchema:
    return FormSchema(
        form_id=form_id,
        form_uid=form_uid,
        version=version,
        title="Test Form",
        sections=[
            FormSection(
                section_id="s1",
                fields=[FormField(field_id="q1", field_type=FieldType.TEXT, label="Q1")],
            )
        ],
        tenant="t1",
    )


@pytest.fixture
def registry():
    """FormRegistry with one in-memory form registered."""
    reg = FormRegistry()
    return reg


@pytest.fixture
async def svc(registry):
    """FormVersionService with no Postgres backend (in-memory)."""
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    return FormVersionService(registry, storage=None)


@pytest.fixture
async def form(registry):
    """The registered form fixture (matching svc fixture)."""
    return _minimal_form()


# ---------------------------------------------------------------------------
# Semver helpers
# ---------------------------------------------------------------------------


def test_parse_major_minor_normal():
    assert _parse_major_minor("1.0") == (1, 0)
    assert _parse_major_minor("2.5") == (2, 5)


def test_parse_major_minor_invalid_falls_back():
    """FEAT-433 TASK-2267: an unparseable version sorts LAST — the sentinel
    is NOT (1, 0), which used to silently mistake it for the OLDEST version
    in the history (the exact misordering Module 4 exists to close)."""
    from parrot_formdesigner.services.form_version import _UNPARSEABLE_SORT_KEY

    assert _parse_major_minor("not-semver") == _UNPARSEABLE_SORT_KEY
    assert _parse_major_minor("") == _UNPARSEABLE_SORT_KEY
    assert _parse_major_minor(None) == _UNPARSEABLE_SORT_KEY
    # And it really does sort last next to real versions:
    assert sorted(
        ["1.0", "not-semver", "2.5"], key=_parse_major_minor
    ) == ["1.0", "2.5", "not-semver"]


def test_parse_major_minor_three_part_ignores_patch():
    """A trailing patch component doesn't degrade to the sentinel — it
    shares its parent's (major, minor) ordering bucket."""
    assert _parse_major_minor("1.2.3") == (1, 2)


def test_bump_minor():
    assert _bump("1.0") == "1.1"
    assert _bump("1.1") == "1.2"
    assert _bump("2.9") == "2.10"


def test_bump_major():
    assert _bump("1.0", bump="major") == "2.0"
    assert _bump("1.5", bump="major") == "2.0"


def test_bump_twice():
    assert _bump(_bump("1.0")) == "1.2"


# ---------------------------------------------------------------------------
# FEAT-433 TASK-2267 — unify the two version bumpers
# ---------------------------------------------------------------------------


def test_bump_grammar_is_single():
    """Both former call sites (api._utils._bump_version and this module's
    _bump) produce identical output — _bump_version now delegates here."""

    for v in ("1.0", "1.9", "1.14"):
        assert _bump_version(v) == _bump(v)


def test_three_component_input_has_one_documented_behaviour():
    """Three-part input has one documented, tested behaviour — the last
    component is incremented, the shape is preserved. Not a silent (1, 0)
    degradation, and identical across both former call sites."""
    assert _bump("1.2.3") == "1.2.4"
    assert _bump_version("1.2.3") == "1.2.4"
    # bump="major" on 3-part input drops the patch, same rule as 2-part.
    assert _bump("1.2.3", bump="major") == "2.0"


def test_major_bump_survives():
    """bump="major" still works after the merge."""
    assert _bump("1.0", bump="major") == "2.0"
    assert _bump("1.9", bump="major") == "2.0"


def test_non_conforming_input_is_total_not_raising():
    """_bump_version is called on the editor's hot path (every save) and
    must never raise — even on a legacy/malformed value already stored."""
    assert _bump("garbage") == "garbage.1"
    assert _bump_version("1") == "1.1"  # bare major-only input, pre-existing case


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def test_form_version_publish_sets_flag(svc, form):
    """FEAT-433 Q5: publish() promotes the live version IN PLACE — it
    returns the SAME tag the form was already at and sets published_version
    to that same tag (no bump)."""
    tag = await svc.publish(form.form_uid, tenant="t1")
    assert tag == "1.0"

    published = await svc.get_published(form.form_uid, version=tag, tenant="t1")
    assert published is not None
    assert published.published_version == tag


async def test_form_version_publish_version_tag_correct(svc, form):
    """Publishing a 1.0 form yields 1.0 (promoted in place, not bumped)."""
    tag = await svc.publish(form.form_uid, tenant="t1")
    assert tag == "1.0"


async def test_form_version_publish_twice_increments(svc, form):
    """A second publish only produces a NEW tag if an editor SAVE bumped
    the version in between — publish() itself no longer bumps (Q5)."""
    tag1 = await svc.publish(form.form_uid, tenant="t1")
    assert tag1 == "1.0"

    # Simulate an editor save (the only thing that bumps now).
    live = await svc._registry.get(form.form_uid, tenant="t1")
    bumped = live.model_copy(update={"version": _bump_version(live.version)})
    await svc._registry.register(bumped, overwrite=True, tenant="t1")

    tag2 = await svc.publish(form.form_uid, tenant="t1")
    assert tag2 == "1.1"


async def test_form_version_publish_bump_param_is_now_unused(svc, form):
    """FEAT-433 Q5: the `bump` kwarg is kept only for backward API
    compatibility — publish() no longer calls _bump() at all, so it has no
    effect; publishing always promotes the live version as-is."""
    tag = await svc.publish(form.form_uid, tenant="t1", bump="major")
    assert tag == "1.0"  # unchanged by bump="major" — NOT "2.0"


async def test_form_version_publish_unknown_form_raises(svc):
    """publish() raises KeyError when form_id is not in registry."""
    with pytest.raises(KeyError):
        await svc.publish("no-such-form", tenant="t1")


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


async def test_form_version_immutable_on_edit(svc, form):
    """Attempting to re-publish an already-published version raises ValueError.

    FEAT-433 Q5: publish() promotes in place, so this no longer needs a
    "roll the live version back" trick — publishing the SAME version twice
    in a row (no editor save in between) already targets an
    already-published row directly.

    Strategy:
    1. Publish once → live form's version ("1.0") is stamped published.
    2. publish() again, unchanged, must detect the already-published "1.0"
       row and raise ValueError.
    """
    tag = await svc.publish(form.form_uid, tenant="t1")
    assert tag == "1.0"

    with pytest.raises(ValueError, match="frozen"):
        await svc.publish(form.form_uid, tenant="t1")


# ---------------------------------------------------------------------------
# List versions
# ---------------------------------------------------------------------------


async def test_form_version_list_versions(svc, form):
    """list_versions() returns the published snapshot(s)."""
    await svc.publish(form.form_uid, tenant="t1")
    versions = await svc.list_versions(form.form_uid, tenant="t1")
    assert len(versions) == 1
    assert isinstance(versions[0], VersionMeta)
    assert versions[0].version == "1.0"


async def test_form_version_list_versions_empty(svc, form):
    """list_versions() returns [] when no publishes have been done."""
    versions = await svc.list_versions(form.form_uid, tenant="t1")
    assert versions == []


async def test_form_version_list_versions_multiple(svc, form):
    """list_versions() accumulates entries across multiple publishes —
    each preceded by an editor save (FEAT-433 Q5: publish() itself no
    longer bumps, so a second publish needs a new draft to promote)."""
    await svc.publish(form.form_uid, tenant="t1")  # "1.0"

    live = await svc._registry.get(form.form_uid, tenant="t1")
    bumped = live.model_copy(update={"version": _bump_version(live.version)})
    await svc._registry.register(bumped, overwrite=True, tenant="t1")

    await svc.publish(form.form_uid, tenant="t1")  # "1.1"

    versions = await svc.list_versions(form.form_uid, tenant="t1")
    assert len(versions) == 2
    assert [v.version for v in versions] == ["1.0", "1.1"]


# ---------------------------------------------------------------------------
# FEAT-433 TASK-2265 — FormStorage.list_versions(), one ordered query
# ---------------------------------------------------------------------------


class _SpyVersionStorage(FormStorage):
    """FormStorage double whose ``list_versions()`` returns fixed projected
    rows and counts how many times it was called — proves
    ``FormVersionService.list_versions()`` issues exactly one storage call
    instead of the old per-candidate-version probing loop."""

    def __init__(self, rows: list[dict]) -> None:
        # Rows deliberately NOT pre-sorted — proves the merge/sort in
        # FormVersionService.list_versions() orders correctly regardless of
        # the order storage returns them in.
        self._rows = rows
        self.list_versions_calls = 0

    async def save(self, form, style=None, *, tenant=None) -> str:
        return form.form_id

    async def load(self, form_uid, version=None, *, tenant=None):
        return None

    async def delete(self, form_uid, *, tenant=None) -> bool:
        return False

    async def list_forms(self, *, tenant=None):
        return []

    async def list_versions(self, form_uid, *, tenant=None) -> list[dict]:
        self.list_versions_calls += 1
        return list(self._rows)


def _published_row(version: str, *, created_at: datetime | None = None) -> dict:
    """A projected storage row for a version publish() actually stamped."""
    return {
        "version": version,
        "created_at": created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        "form_id": "form1",
        "published_version": version,
        "published_at": (created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)).isoformat(),
    }


async def test_list_versions_single_query():
    """Listing issues exactly one storage call (no per-version probing)."""
    storage = _SpyVersionStorage([_published_row(f"1.{i}") for i in range(15)])
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    await svc.list_versions(form.form_uid, tenant="t1")

    assert storage.list_versions_calls == 1


async def test_list_versions_orders_past_ten():
    """1.0..1.14 come back in that order: 1.9 before 1.10, 1.14 last."""
    # Deliberately scrambled — the merge/sort must not depend on storage
    # returning rows in order.
    rows = [_published_row(f"1.{i}") for i in (0, 10, 9, 14, 2, 1, 11, 3, 4, 5, 6, 7, 8, 12, 13)]
    storage = _SpyVersionStorage(rows)
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    versions = await svc.list_versions(form.form_uid, tenant="t1")

    assert [v.version for v in versions] == [f"1.{i}" for i in range(15)]
    assert versions[-1].version == "1.14"


async def test_list_versions_survives_gaps():
    """Deleting 1.2 and 1.3 still lists 1.4+ (the old probe stopped there)."""
    rows = [_published_row(v) for v in ("1.0", "1.1", "1.4", "1.5")]
    storage = _SpyVersionStorage(rows)
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    versions = await svc.list_versions(form.form_uid, tenant="t1")

    assert [v.version for v in versions] == ["1.0", "1.1", "1.4", "1.5"]


async def test_probe_storage_versions_removed():
    """_probe_storage_versions and _MAX_VERSION_PROBES no longer exist."""
    import parrot_formdesigner.services.form_version as form_version_module

    assert not hasattr(FormVersionService, "_probe_storage_versions")
    assert not hasattr(form_version_module, "_MAX_VERSION_PROBES")


# ---------------------------------------------------------------------------
# FEAT-433 TASK-2266 — draft/published label (D1/D3), demoted from a gate
# ---------------------------------------------------------------------------


def _draft_row(version: str, *, created_at: datetime | None = None) -> dict:
    """A projected storage row for a version the EDITOR saved directly
    (``_bump_version`` + ``storage.save()``) — NO ``publish()`` call
    anywhere, so ``published_version`` is ``None`` (spec §4 fixture rule)."""
    ts = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "version": version,
        "created_at": ts,
        "updated_at": ts,
        "form_id": "form1",
        "published_version": None,
        "published_at": None,
    }


async def test_editor_saved_rows_are_labelled_draft():
    """Rows written via the editor path alone (no publish() anywhere in the
    fixture) appear in the listing, labelled draft."""
    storage = _SpyVersionStorage([_draft_row("1.0"), _draft_row("1.1")])
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    versions = await svc.list_versions(form.form_uid, tenant="t1")

    assert [v.version for v in versions] == ["1.0", "1.1"]
    assert all(v.is_published is False for v in versions)
    assert all(v.is_frozen is False for v in versions)


async def test_published_rows_are_labelled_published():
    """A row written by publish() comes back is_published is True."""
    storage = _SpyVersionStorage([_published_row("1.1")])
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    versions = await svc.list_versions(form.form_uid, tenant="t1")

    assert versions[0].is_published is True
    assert versions[0].is_frozen is True


async def test_draft_and_published_coexist_in_one_history():
    """publish, save twice, publish again → labels alternate correctly."""
    storage = _SpyVersionStorage([
        _published_row("1.0"),
        _draft_row("1.1"),
        _published_row("1.2"),
        _draft_row("1.3"),
    ])
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    versions = await svc.list_versions(form.form_uid, tenant="t1")

    assert [(v.version, v.is_published) for v in versions] == [
        ("1.0", True), ("1.1", False), ("1.2", True), ("1.3", False),
    ]


async def test_draft_published_at_is_not_now():
    """A draft's published_at equals its stored created_at — never wall-clock
    now (the previous fallback made every draft report "published just
    now")."""
    created = datetime(2020, 5, 4, tzinfo=timezone.utc)
    storage = _SpyVersionStorage([_draft_row("1.0", created_at=created)])
    registry = FormRegistry()
    form = _minimal_form()
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    versions = await svc.list_versions(form.form_uid, tenant="t1")

    assert versions[0].published_at == created


def test_version_meta_requires_is_published_and_is_frozen():
    """VersionMeta is extra='forbid' and no longer hardcodes is_frozen=True
    — every construction site must supply both fields explicitly."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VersionMeta(
            form_id="f1", version="1.0",
            published_at=datetime.now(timezone.utc), tenant="t1",
        )


# ---------------------------------------------------------------------------
# FEAT-433 TASK-2265 — PostgresFormStorage.list_versions() SQL shape
# ---------------------------------------------------------------------------


class _StubVersionRow(dict):
    """asyncpg.Record duck-type — supports row['key'] indexing."""


class _StubVersionConn:
    """Minimal asyncpg connection stub recording fetch() calls."""

    def __init__(self, rows: list[_StubVersionRow]) -> None:
        self._rows = rows
        self.fetch_calls = 0
        self.last_sql: str | None = None
        self.last_args: tuple | None = None

    async def fetch(self, sql: str, *args) -> list[_StubVersionRow]:
        self.fetch_calls += 1
        self.last_sql = sql
        self.last_args = args
        return list(self._rows)

    async def __aenter__(self) -> "_StubVersionConn":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _StubVersionAcquireCtx:
    def __init__(self, conn: _StubVersionConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _StubVersionConn:
        return self._conn

    async def __aexit__(self, *exc) -> bool:
        return False


class _StubVersionPool:
    def __init__(self, rows: list[_StubVersionRow]) -> None:
        self.conn = _StubVersionConn(rows)

    def acquire(self) -> _StubVersionAcquireCtx:
        return _StubVersionAcquireCtx(self.conn)


async def test_list_versions_projects_not_hauls():
    """The SQL selects the projected columns, not schema_json whole."""
    rows = [_StubVersionRow(
        version="1.0",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        form_id="f1",
        published_version="1.0",
        published_at="2026-01-01T00:00:00+00:00",
    )]
    pool = _StubVersionPool(rows)
    storage = PostgresFormStorage(pool=pool)

    out = await storage.list_versions("uid-1", tenant="t1")

    assert out == [{
        "version": "1.0",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "form_id": "f1",
        "published_version": "1.0",
        "published_at": "2026-01-01T00:00:00+00:00",
    }]
    # Never select schema_json whole — only its projected sub-fields.
    assert "schema_json," not in pool.conn.last_sql
    assert "SELECT schema_json" not in pool.conn.last_sql


async def test_list_versions_sql_guards_the_cast():
    """The ORDER BY guards the ::int cast against non-major.minor versions."""
    storage = PostgresFormStorage(pool=_StubVersionPool([]))
    sql = storage._list_versions_sql(None)
    assert "::int" in sql
    assert "NULLS LAST" in sql
    assert "CASE WHEN version ~" in sql


async def test_list_versions_single_storage_call():
    """A single fetch() call regardless of row count."""
    pool = _StubVersionPool([])
    storage = PostgresFormStorage(pool=pool)

    await storage.list_versions("uid-1", tenant="t1")

    assert pool.conn.fetch_calls == 1


# ---------------------------------------------------------------------------
# RF-06: snapshot isolation
# ---------------------------------------------------------------------------


async def test_publish_then_edit_isolation(registry):
    """RF-06: v1 snapshot is unchanged after v2 is published."""
    form = _minimal_form("form-rf06", version="1.0")
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=None)

    v1_tag = await svc.publish(form.form_uid, tenant="t1")
    original_title = form.title

    # Simulate an editor save: bump the version AND change the title
    # (FEAT-433 Q5: publish() itself no longer bumps, so a second publish
    # needs the editor's save to produce a new draft first).
    live = await registry.get(form.form_uid, tenant="t1")
    edited = live.model_copy(update={
        "version": _bump_version(live.version),
        "title": "Edited Title",
    })
    await registry.register(edited, overwrite=True, tenant="t1")

    # Publish the new draft as a second version
    v2_tag = await svc.publish(form.form_uid, tenant="t1")
    assert v2_tag != v1_tag

    # v1 snapshot must be unchanged
    snap_v1 = await svc.get_published(form.form_uid, version=v1_tag, tenant="t1")
    assert snap_v1 is not None
    assert snap_v1.title == original_title  # untouched


# ---------------------------------------------------------------------------
# FEAT-433 TASK-2268 — get_published() drops the second filter site
# ---------------------------------------------------------------------------


class _LoadableStorage(FormStorage):
    """FormStorage double whose load() returns whatever was save()'d and
    whose list_versions() mirrors the projected-dict shape — proves
    get_published() no longer filters on published_version (Module 5) and
    lets list_versions()/get_published() be exercised together (the
    anti-regression: every listed version must resolve)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str | None, str], dict[str, FormSchema]] = {}

    async def save(self, form: FormSchema, style=None, *, tenant=None) -> str:
        versions = self._rows.setdefault((tenant, str(form.form_uid)), {})
        versions[form.version] = form.model_copy(deep=True)
        return form.form_id

    async def load(self, form_uid, version=None, *, tenant=None):
        versions = self._rows.get((tenant, str(form_uid)), {})
        if not versions:
            return None
        if version is not None:
            snap = versions.get(version)
            return snap.model_copy(deep=True) if snap else None
        return list(versions.values())[-1].model_copy(deep=True)

    async def delete(self, form_uid, *, tenant=None) -> bool:
        return self._rows.pop((tenant, str(form_uid)), None) is not None

    async def list_forms(self, *, tenant=None):
        return []

    async def list_versions(self, form_uid, *, tenant=None) -> list[dict]:
        versions = self._rows.get((tenant, str(form_uid)), {})
        return [
            {
                "version": version,
                "created_at": snap.created_at or datetime.now(timezone.utc),
                "updated_at": snap.created_at or datetime.now(timezone.utc),
                "form_id": snap.form_id,
                "published_version": snap.published_version,
                "published_at": (snap.meta or {}).get("published_at"),
            }
            for version, snap in versions.items()
        ]


async def test_get_published_returns_draft_version():
    """get_published() returns a row whose published_version != version
    instead of None (FEAT-433 Module 5) — the editor-saved draft case."""
    storage = _LoadableStorage()
    registry = FormRegistry()
    form = _minimal_form(version="1.0")
    await registry.register(form, tenant="t1")
    await storage.save(form, tenant="t1")  # editor path — NO publish()
    svc = FormVersionService(registry, storage=storage)

    snap = await svc.get_published(form.form_uid, version="1.0", tenant="t1")

    assert snap is not None
    assert snap.published_version is None


async def test_every_listed_version_is_retrievable():
    """Anti-regression: every entry list_versions() returns resolves via
    get_published() — "list works, clicking 404s" no longer happens."""
    storage = _LoadableStorage()
    registry = FormRegistry()
    form = _minimal_form(version="1.0")
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    await storage.save(form, tenant="t1")  # 1.0 draft
    draft2 = form.model_copy(deep=True, update={"version": "1.1"})
    await storage.save(draft2, tenant="t1")  # 1.1 draft
    await registry.register(draft2, overwrite=True, tenant="t1")
    await svc.publish(form.form_uid, tenant="t1")  # promotes live "1.1" in place (Q5)

    versions = await svc.list_versions(form.form_uid, tenant="t1")
    assert len(versions) == 2  # "1.0" draft, "1.1" now published in place

    for v in versions:
        snap = await svc.get_published(form.form_uid, version=v.version, tenant="t1")
        assert snap is not None, f"version {v.version} listed but not retrievable"


async def test_publish_succeeds_when_target_version_has_only_a_draft_row():
    """FEAT-433 Q5 + Module 5: publish()'s fast-path pre-check distinguishes
    "a row exists at the target version" from "that row is ALREADY
    published" — an editor-saved draft at the live version (the normal
    case: the editor always saves before publishing) does not trip the
    guard; only an already-published row does (see
    test_form_version_immutable_on_edit)."""
    storage = _LoadableStorage()
    registry = FormRegistry()
    form = _minimal_form(version="1.0")
    await registry.register(form, tenant="t1")
    svc = FormVersionService(registry, storage=storage)

    # The editor already saved a draft at "1.0" — the live version publish()
    # is about to promote. This is the NORMAL case, not a race.
    await storage.save(form, tenant="t1")

    tag = await svc.publish(form.form_uid, tenant="t1")
    assert tag == "1.0"

    published = await svc.get_published(form.form_uid, version="1.0", tenant="t1")
    assert published is not None
    assert published.published_version == "1.0"


# ---------------------------------------------------------------------------
# Deletion guard
# ---------------------------------------------------------------------------


async def test_form_version_delete_with_responses_blocked():
    """safe_delete raises ValueError when has_responses returns True."""
    registry = FormRegistry()
    form = _minimal_form("form-del")
    await registry.register(form, tenant="t1")

    async def _has_responses(form_id: str, tenant: str) -> bool:
        return True

    svc = FormVersionService(registry, has_responses=_has_responses)

    with pytest.raises(ValueError, match="responses"):
        await svc.safe_delete(form.form_uid, tenant="t1")


async def test_form_version_delete_without_responses_allowed():
    """safe_delete succeeds when has_responses returns False."""
    registry = FormRegistry()
    form = _minimal_form("form-del2")
    await registry.register(form, tenant="t1")

    async def _no_responses(form_id: str, tenant: str) -> bool:
        return False

    svc = FormVersionService(registry, has_responses=_no_responses)
    # Should not raise
    await svc.safe_delete(form.form_uid, tenant="t1")


async def test_form_version_delete_no_hook_allowed():
    """safe_delete is always allowed when no has_responses hook is provided."""
    registry = FormRegistry()
    form = _minimal_form("form-del3")
    await registry.register(form, tenant="t1")

    svc = FormVersionService(registry)
    # No hook → deletion is always allowed
    await svc.safe_delete(form.form_uid, tenant="t1")
