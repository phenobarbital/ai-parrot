"""Tests for the Jira sweep — watermark, orphans, entity notes (FEAT-454, M4)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from parrot.interfaces.jira import JiraAuthError, parse_issue
from parrot.knowledge.wiki.jira_sync import (
    JiraScopeState,
    JiraSyncState,
    SweepReport,
    jql_fingerprint,
    load_sync_state,
    resolve_issues_dir,
    save_sync_state,
    sweep_jira_issues,
)

BASE = "https://example.atlassian.net"
JQL = "project = NAV"


class _FakeNotFoundError(Exception):
    """Duck-typed 404, mirroring `jira.exceptions.JIRAError`'s shape
    (a `status_code` attribute) without importing the real `jira` package."""

    def __init__(self, status_code: int = 404) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class FakeJiraInterface:
    """In-memory JiraInterface stand-in: no network, scriptable pages,
    plus a failure-injection hook for the partial-sweep tests."""

    def __init__(
        self,
        raw_issues,
        *,
        fail_after=None,
        unreachable=(),
        probe_error=None,
        transient_error_keys=(),
        server_url=BASE,
        remote_links_by_key=None,
    ):
        self.raw_issues = list(raw_issues)
        self.fail_after = fail_after
        self.unreachable = set(unreachable)
        self.probe_error = probe_error
        self.transient_error_keys = set(transient_error_keys)
        self.server_url = server_url
        self.remote_links_by_key = dict(remote_links_by_key or {})
        self.searched: list[str] = []
        self.remote_links_calls: list[str] = []

    async def search_issues(self, jql, *, fields=None, expand=None, page_size=100):
        self.searched.append(jql)
        if not self.raw_issues and self.probe_error is not None:
            raise self.probe_error
        for i, raw in enumerate(self.raw_issues):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("injected mid-sweep failure")
            yield raw

    async def get_issue(self, key, *, fields=None, expand=None):
        if key in self.unreachable:
            raise _FakeNotFoundError(404)
        if key in self.transient_error_keys:
            # No status_code — a non-404/403 failure (rate limit, timeout,
            # permissions), distinct from a definitive "gone" verdict.
            raise RuntimeError(f"injected transient error probing {key}")
        return {"id": "0", "key": key}

    async def resolve_ac_field_id(self):
        return "customfield_10101"

    async def get_remote_links(self, key):
        self.remote_links_calls.append(key)
        return self.remote_links_by_key.get(key, [])

    async def verify_auth(self):
        if self.probe_error is not None:
            raise self.probe_error
        return {"accountId": "x"}

    @staticmethod
    def parse_issue(raw, *, base_url=BASE, ac_field_id=None, raw_remote_links=None):
        return parse_issue(raw, base_url=base_url, ac_field_id=ac_field_id, raw_remote_links=raw_remote_links)


def _sweep(iface, d, **kw) -> SweepReport:
    return asyncio.run(sweep_jira_issues(iface, d, jql=JQL, **kw))


def _tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


class TestPublicSurface:
    def test_save_sync_state_roundtrip(self, issues_dir):
        state = JiraSyncState(scopes={"fp1": JiraScopeState(jql=JQL, jql_fingerprint="fp1", extractor_version=1)})
        save_sync_state(issues_dir, state)
        loaded = load_sync_state(issues_dir)
        assert loaded.scopes["fp1"].jql == JQL


class TestWatermark:
    def test_advances_on_success(self, raw_issue, issues_dir):
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        state = load_sync_state(issues_dir)
        scope = state.scopes[jql_fingerprint(JQL)]
        assert report.watermark_advanced is True
        assert scope.last_run_status == "ok"
        assert scope.last_watermark.startswith("2026-08-20")

    def test_not_advanced_on_partial(self, raw_issue, issues_dir):
        iface = FakeJiraInterface([raw_issue, raw_issue], fail_after=1)
        report = _sweep(iface, issues_dir)
        scope = load_sync_state(issues_dir).scopes[jql_fingerprint(JQL)]
        assert report.errors and report.watermark_advanced is False
        assert scope.last_watermark is None
        assert scope.last_run_status == "partial"

    def test_partial_written_before_fetch(self, raw_issue, issues_dir):
        """A SIGKILL mid-sweep must leave 'partial' on disk."""
        iface = FakeJiraInterface([raw_issue], fail_after=0)
        _sweep(iface, issues_dir)
        raw = json.loads((issues_dir / ".parrot" / "jira_sync.json").read_text())
        fp = jql_fingerprint(JQL)
        assert raw["scopes"][fp]["last_run_status"] == "partial"

    def test_second_run_fetches_nothing(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        second = _sweep(FakeJiraInterface([]), issues_dir)
        assert second.fetched == 0 and second.written == 0

    def test_watermark_added_as_jql_conjunct(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([])
        _sweep(iface, issues_dir)
        assert any("updated >=" in q for q in iface.searched)

    def test_scopes_keyed_by_fingerprint(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        asyncio.run(sweep_jira_issues(FakeJiraInterface([raw_issue]), issues_dir, jql="project = OTHER"))
        state = load_sync_state(issues_dir)
        assert len(state.scopes) == 2
        assert jql_fingerprint(JQL) != jql_fingerprint("project = OTHER")

    def test_force_ignores_watermark(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([raw_issue])
        _sweep(iface, issues_dir, force=True)
        assert all("updated >=" not in q for q in iface.searched)

    def test_extractor_version_bump_forces_rerender(self, raw_issue, issues_dir, monkeypatch):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        import parrot.knowledge.wiki.jira_sync as sync_mod

        monkeypatch.setattr(sync_mod, "EXTRACTOR_VERSION", 99)
        iface = FakeJiraInterface([raw_issue])
        report = _sweep(iface, issues_dir)
        assert all("updated >=" not in q for q in iface.searched)
        assert report.written >= 1

    def test_watermark_comes_from_jira_not_local_clock(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        scope = load_sync_state(issues_dir).scopes[jql_fingerprint(JQL)]
        assert "2026-08-20" in scope.last_watermark  # the fixture's `updated`


class TestAuthProbe:
    def test_empty_result_probes_and_does_not_advance(self, issues_dir):
        """The AUTHENTICATED_FAILED trap — the worst failure mode (§7)."""
        iface = FakeJiraInterface([], probe_error=JiraAuthError("AUTHENTICATED_FAILED"))
        report = _sweep(iface, issues_dir)
        assert report.errors and report.watermark_advanced is False
        state = load_sync_state(issues_dir)
        assert state.scopes[jql_fingerprint(JQL)].last_watermark is None


class TestIdempotenceAndInPlaceUpdate:
    def test_one_document_per_ticket(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert len(list(issues_dir.glob("NAV-*.md"))) == 1

    def test_unchanged_issue_not_rewritten(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        path = issues_dir / "NAV-9372.md"
        before = path.stat().st_mtime_ns
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert report.unchanged >= 1 and report.written == 0
        assert path.stat().st_mtime_ns == before

    def test_changed_status_updates_in_place(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        changed = json.loads(json.dumps(raw_issue))
        changed["fields"]["status"]["name"] = "Done"
        changed["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        report = _sweep(FakeJiraInterface([changed]), issues_dir, force=True)
        assert report.written == 1
        assert "Done" in (issues_dir / "NAV-9372.md").read_text()

    def test_human_tail_survives_resync(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        path = issues_dir / "NAV-9372.md"
        path.write_text(path.read_text() + "\n## My note\n\nkeep me\n")
        changed = json.loads(json.dumps(raw_issue))
        changed["fields"]["status"]["name"] = "Done"
        changed["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        _sweep(FakeJiraInterface([changed]), issues_dir, force=True)
        text = path.read_text()
        assert "keep me" in text and "Done" in text

    def test_force_resync_unchanged_ticket_ignores_fetched_at_drift(self, raw_issue, issues_dir, monkeypatch):
        """Adversarial-review regression: a --force resync of an
        UNCHANGED ticket, executed at a LATER wall-clock time, must
        still count as unchanged and leave the file byte-identical and
        its mtime untouched — sync.fetched_at drifting alone must never
        trigger a rewrite (G2)."""
        import parrot.knowledge.wiki.jira_sync as sync_mod

        class _FixedDatetime(datetime):
            _now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)

            @classmethod
            def now(cls, tz=None):
                return cls._now

        monkeypatch.setattr(sync_mod, "datetime", _FixedDatetime)

        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        path = issues_dir / "NAV-9372.md"
        before_bytes = path.read_bytes()
        before_mtime = path.stat().st_mtime_ns

        _FixedDatetime._now = datetime(2026, 8, 25, 9, 0, 0, tzinfo=UTC)
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)

        assert report.unchanged >= 1 and report.written == 0
        assert path.read_bytes() == before_bytes
        assert path.stat().st_mtime_ns == before_mtime


class TestEntityNotes:
    def test_notes_emitted(self, raw_issue, issues_dir):
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        assert report.entity_notes > 0
        assert list((issues_dir / "people").glob("*.md"))
        assert (issues_dir / "projects" / "NAV.md").exists()
        assert list((issues_dir / "components").glob("*.md"))
        assert list((issues_dir / "labels").glob("*.md"))

    def test_incremental_sweep_merges_keys(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        second = json.loads(json.dumps(raw_issue))
        second["key"] = "NAV-9999"
        second["id"] = "184221"
        second["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        _sweep(FakeJiraInterface([second]), issues_dir)
        project_note = (issues_dir / "projects" / "NAV.md").read_text()
        assert "NAV-9372" in project_note and "NAV-9999" in project_note

    def test_entity_note_human_tail_survives(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        note = issues_dir / "projects" / "NAV.md"
        note.write_text(note.read_text() + "\nproject owner: Ana\n")
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert "project owner: Ana" in note.read_text()

    def test_no_email_in_any_generated_file(self, raw_issue, issues_dir):
        """G9 over the whole corpus."""
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        for path in issues_dir.rglob("*.md"):
            text = path.read_text()
            assert "jlara@example.com" not in text
            assert "aruiz@example.com" not in text

    def test_remote_links_fetched_and_rendered(self, raw_issue, issues_dir):
        """Adversarial-review finding: `get_remote_links` existed on the
        interface since TASK-2400 but the sweep never called it — every
        ticket silently got `remote_links=[]` regardless of what Jira
        actually had. This is the sweep's side of that wiring."""
        iface = FakeJiraInterface(
            [raw_issue],
            remote_links_by_key={"NAV-9372": [{"object": {"title": "Runbook", "url": "https://wiki/runbook"}}]},
        )
        _sweep(iface, issues_dir)
        assert iface.remote_links_calls == ["NAV-9372"]
        text = (issues_dir / "NAV-9372.md").read_text()
        assert "## Remote Links" in text
        assert "[Runbook](https://wiki/runbook)" in text


class TestEntityNoteStaleMembershipPruning:
    """Adversarial-review finding: entity notes never removed stale
    membership at all — a ticket that left the JQL scope stayed listed on
    its person/project/component/label satellite notes forever. See
    `_prune_stale_entity_notes`'s docstring for the documented scope
    boundary of this fix (a same-scope reassignment while the ticket
    stays in scope is only half-corrected: the gaining entity's note is
    always fresh; the losing entity's note is not addressed here)."""

    def test_ticket_moved_out_of_scope_is_pruned_from_person_note(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        person_note = next((issues_dir / "people").glob("*.md"))
        assert "NAV-9372" in person_note.read_text()

        # A subsequent FULL sweep whose JQL scope no longer matches this
        # ticket at all (e.g. it moved to a different project) — fetches
        # nothing, but is still a full sweep (no watermark conjunct).
        _sweep(FakeJiraInterface([]), issues_dir, force=True)
        assert "NAV-9372" not in person_note.read_text()

    def test_ticket_moved_out_of_scope_is_pruned_from_project_note(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        project_note = issues_dir / "projects" / "NAV.md"
        assert "NAV-9372" in project_note.read_text()

        _sweep(FakeJiraInterface([]), issues_dir, force=True)
        assert "NAV-9372" not in project_note.read_text()

    def test_incremental_sweep_never_prunes(self, raw_issue, issues_dir):
        """An incremental sweep only ever sees a subset of tickets — it
        must never treat "not seen this run" as "no longer valid"."""
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        project_note_before = (issues_dir / "projects" / "NAV.md").read_text()

        second = json.loads(json.dumps(raw_issue))
        second["key"] = "NAV-9999"
        second["id"] = "184221"
        second["fields"]["updated"] = "2026-08-25T10:00:00.000+0000"
        # No force=True and a watermark already exists — this is an
        # incremental sweep that does not re-fetch NAV-9372 at all.
        _sweep(FakeJiraInterface([second]), issues_dir)

        project_note_after = (issues_dir / "projects" / "NAV.md").read_text()
        assert "NAV-9372" in project_note_after, "incremental sweep must not prune what it didn't re-fetch"
        assert "NAV-9999" in project_note_after
        assert project_note_before != project_note_after  # merged, not untouched

    def test_dry_run_reports_without_writing(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        person_note = next((issues_dir / "people").glob("*.md"))
        before = person_note.read_text()

        report = _sweep(FakeJiraInterface([]), issues_dir, force=True, dry_run=True)

        assert person_note.read_text() == before, "dry_run must never write"
        assert report.entity_notes > 0


class TestOrphansAndUnreachable:
    def test_orphan_reported_on_full_sweep(self, raw_issue, issues_dir):
        (issues_dir / "NAV-0001.md").write_text("---\nkey: NAV-0001\n---\n")
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert report.orphaned == 1
        assert (issues_dir / "NAV-0001.md").exists(), "orphans are NEVER deleted"

    def test_orphans_skipped_on_incremental_sweep(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        report = _sweep(FakeJiraInterface([]), issues_dir)
        assert report.orphaned == 0, "an incremental sweep must not call every document an orphan"

    def test_entity_dirs_not_scanned_for_orphans(self, raw_issue, issues_dir):
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, force=True)
        assert report.orphaned == 0

    def test_unreachable_marked_not_deleted(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([], unreachable={"NAV-9372"})
        _sweep(iface, issues_dir, force=True)
        path = issues_dir / "NAV-9372.md"
        assert path.exists()
        assert "unreachable_since" in path.read_text()

    def test_watermark_not_advanced_when_orphan_probe_errors(self, raw_issue, issues_dir):
        """Adversarial-review regression (G5): a transient error probing
        ONE orphan candidate — among an otherwise fully successful full
        sweep — must gate the watermark exactly like a fetch-loop
        failure does. Silently marking this run "ok" would be the same
        silent, self-perpetuating failure mode G5 exists to prevent,
        just via a different code path."""
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        iface = FakeJiraInterface([], transient_error_keys={"NAV-9372"})
        report = _sweep(iface, issues_dir, force=True)

        assert report.errors, "the transient probe error must be recorded"
        assert report.watermark_advanced is False
        scope = load_sync_state(issues_dir).scopes[jql_fingerprint(JQL)]
        assert scope.last_run_status == "partial"
        # The document itself is untouched — never marked unreachable on
        # an inconclusive probe, never deleted.
        path = issues_dir / "NAV-9372.md"
        assert path.exists()
        assert "unreachable_since" not in path.read_text()


class TestDryRun:
    def test_writes_nothing(self, raw_issue, issues_dir):
        before = _tree(issues_dir)
        report = _sweep(FakeJiraInterface([raw_issue]), issues_dir, dry_run=True)
        assert _tree(issues_dir) == before
        assert report.fetched == 1

    def test_dry_run_does_not_write_state(self, raw_issue, issues_dir):
        _sweep(FakeJiraInterface([raw_issue]), issues_dir, dry_run=True)
        assert not (issues_dir / ".parrot" / "jira_sync.json").exists()


class TestStorageLocation:
    def test_default_is_absolute_and_outside_repo(self, monkeypatch, tmp_path):
        """G8 — a relative default would write into the working tree."""
        monkeypatch.delenv("PARROT_HOME", raising=False)
        monkeypatch.delenv("JIRA_WIKI_ISSUES_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
        resolved = resolve_issues_dir()
        assert resolved.is_absolute()
        assert tmp_path not in resolved.parents and resolved != tmp_path

    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("JIRA_WIKI_ISSUES_DIR", str(tmp_path / "custom"))
        assert resolve_issues_dir() == tmp_path / "custom"

    def test_state_file_lives_under_dot_parrot(self, raw_issue, issues_dir):
        """.parrot is in VAULT_EXCLUDE_DIRS, so it is never re-ingested."""
        _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        assert (issues_dir / ".parrot" / "jira_sync.json").exists()


class TestNoLLM:
    def test_sweep_accepts_no_client(self):
        import inspect

        params = set(inspect.signature(sweep_jira_issues).parameters)
        assert not params & {"client", "llm", "model", "enrich"}

    def test_no_llm_import_in_module(self):
        import inspect

        import parrot.knowledge.wiki.jira_sync as mod

        src = inspect.getsource(mod)
        for banned in ("AbstractClient", "get_client", "completion("):
            assert banned not in src, banned


class TestConcurrency:
    def test_second_writer_refused(self, raw_issue, issues_dir):
        """wiki_write_lock — two crons must not interleave writes."""
        from parrot.knowledge.wiki.project import wiki_write_lock

        with wiki_write_lock(issues_dir / ".parrot"):
            report = _sweep(FakeJiraInterface([raw_issue]), issues_dir)
        assert report.errors
        assert report.written == 0
