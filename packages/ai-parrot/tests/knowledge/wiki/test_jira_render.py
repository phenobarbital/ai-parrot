"""Tests for the deterministic Jira renderer (FEAT-454, M3)."""

import inspect
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from parrot.interfaces.jira import JiraPerson, parse_issue
from parrot.knowledge.wiki import jira_render
from parrot.knowledge.wiki.jira_render import (
    EXTRACTOR_VERSION,
    SYNC_MARKER,
    issue_filename,
    person_slug,
    render_group_note,
    render_issue_document,
    render_person_note,
    split_at_marker,
)

GOLDEN = Path(__file__).parent / "fixtures" / "jira" / "NAV-9372.golden.md"
BASE = "https://example.atlassian.net"


@pytest.fixture
def frozen_now() -> datetime:
    """Fixed fetched_at so golden comparisons are byte-stable."""
    return datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def issue(raw_issue):
    return parse_issue(raw_issue, base_url=BASE, ac_field_id="customfield_10101")


class TestGoldenAndDeterminism:
    def test_golden(self, issue, frozen_now):
        """G2: byte-identical to the committed golden document."""
        rendered = render_issue_document(issue, fetched_at=frozen_now)
        if not GOLDEN.exists():  # first run: write, then COMMIT it
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(rendered, encoding="utf-8")
            pytest.fail("golden written — inspect and commit it, then re-run")
        assert rendered == GOLDEN.read_text(encoding="utf-8")

    def test_render_twice_identical(self, issue, frozen_now):
        a = render_issue_document(issue, fetched_at=frozen_now)
        b = render_issue_document(issue, fetched_at=frozen_now)
        assert a == b

    def test_idempotent_over_own_output(self, issue, frozen_now):
        once = render_issue_document(issue, fetched_at=frozen_now)
        twice = render_issue_document(issue, fetched_at=frozen_now, existing=once)
        assert twice == once


class TestFrontmatterContract:
    def _fm(self, text) -> dict:
        assert text.startswith("---\n")
        block = text.split("---\n", 2)[1]
        return yaml.safe_load(block)

    def test_key_order_matches_declared_tuple(self, issue, frozen_now):
        text = render_issue_document(issue, fetched_at=frozen_now)
        block = text.split("---\n", 2)[1]
        emitted = [ln.split(":", 1)[0] for ln in block.splitlines() if ln and not ln.startswith((" ", "-"))]
        order = list(jira_render._ISSUE_FRONTMATTER_FIELD_ORDER)
        assert emitted == [k for k in order if k in emitted]

    def test_type_is_plain_string(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        assert fm["type"] == "Issue"

    def test_lists_sorted(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        for key in ("labels", "components", "subtasks"):
            if key in fm:
                assert fm[key] == sorted(fm[key]), key

    def test_none_and_empty_omitted(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        assert "resolution" not in fm  # None in the fixture
        assert "resolved_at" not in fm
        assert all(v != [] for v in fm.values())

    def test_sync_stamp_present(self, issue, frozen_now):
        fm = self._fm(render_issue_document(issue, fetched_at=frozen_now))
        assert fm["sync"]["extractor_version"] == EXTRACTOR_VERSION
        assert fm["sync"]["fetched_at"]
        assert "unreachable_since" not in fm["sync"]


class TestSyncMarkerPreservation:
    """G4 — the highest-consequence path. A bug here eats someone's notes."""

    def test_preserves_human_tail_verbatim(self, issue, frozen_now):
        tail = f"{SYNC_MARKER}\n\n## My notes\n\nThis matters.\n\n   \t\n"
        existing = "---\nkey: NAV-9372\n---\n\nstale\n" + tail
        out = render_issue_document(issue, fetched_at=frozen_now, existing=existing)
        assert out.endswith(tail)

    def test_trailing_whitespace_survives(self, issue, frozen_now):
        tail = f"{SYNC_MARKER}\n\nnote with trailing spaces   \n\n\n"
        out = render_issue_document(issue, fetched_at=frozen_now, existing="old\n" + tail)
        assert out.endswith(tail)

    def test_missing_marker_is_appended_and_nothing_lost(self, issue, frozen_now):
        handmade = "# Hand written\n\nSomeone's irreplaceable note.\n"
        out = render_issue_document(issue, fetched_at=frozen_now, existing=handmade)
        assert SYNC_MARKER in out
        assert "Someone's irreplaceable note." in out

    def test_duplicated_marker_only_first_splits(self):
        text = f"gen\n{SYNC_MARKER}\nhuman a\n{SYNC_MARKER}\nhuman b\n"
        generated, tail = split_at_marker(text)
        assert generated == "gen\n"
        assert tail.count(SYNC_MARKER) == 2
        assert "human a" in tail and "human b" in tail

    def test_marker_inside_code_fence_splits_conservatively(self):
        """Documented v1 behaviour: first line-anchored match wins, and the
        fence lands (preserved) in the human tail. Never loses content."""
        text = f"gen\n```\n{SYNC_MARKER}\n```\ntail\n"
        generated, tail = split_at_marker(text)
        assert generated.startswith("gen")
        assert SYNC_MARKER in tail and "```" in tail

    def test_no_marker_returns_empty_tail(self):
        generated, tail = split_at_marker("just a document\n")
        assert generated == "just a document\n" and tail == ""


class TestWikilinksAndTags:
    def test_relations_emit_wikilinks(self, issue, frozen_now):
        out = render_issue_document(issue, fetched_at=frozen_now)
        for key in ("NAV-8000", "NAV-9000", "NAV-9373", "NAV-9400", "NAV-9111"):
            assert f"[[{key}]]" in out

    def test_tags_emitted_for_project_components_labels(self, issue, frozen_now):
        out = render_issue_document(issue, fetched_at=frozen_now)
        for tag in ("#NAV", "#navigator-forms", "#multitenant"):
            assert tag in out

    def test_repo_pages_are_never_wikilinks(self, issue, frozen_now):
        """Cross-namespace edges do not exist (cli.py:2665-2666)."""
        out = render_issue_document(
            issue, fetched_at=frozen_now, repo_pages=["repo::file:sdd/specs/jira-extractor-llmwiki.spec.md"]
        )
        assert "[[repo::" not in out
        assert "repo::file:sdd/specs/jira-extractor-llmwiki.spec.md" in out

    def test_jira_url_line_present_for_fts_join(self, issue, frozen_now):
        out = render_issue_document(issue, fetched_at=frozen_now)
        assert "**Jira**:" in out and "/browse/NAV-9372" in out


class TestHtmlConversion:
    def test_deterministic(self):
        html = "<p>a <code>b</code></p><table><tr><td>x</td></tr></table>"
        first = jira_render.html_to_markdown(html)
        assert first == jira_render.html_to_markdown(html)

    def test_no_line_wrapping(self):
        html = "<p>" + ("word " * 200).strip() + "</p>"
        out = jira_render.html_to_markdown(html)
        assert (
            max(len(l) for l in out.splitlines()) > 100
        ), "body_width must be 0 — default 78 wrapping is non-deterministic"

    def test_empty_and_none_degrade(self):
        assert jira_render.html_to_markdown(None) == ""
        assert jira_render.html_to_markdown("") == ""

    def test_links_and_code_survive(self):
        out = jira_render.html_to_markdown('<p><a href="https://x/y">y</a> <pre>code()</pre></p>')
        assert "https://x/y" in out and "code()" in out


class TestSlugsAndFilenames:
    def test_issue_filename(self):
        assert issue_filename("NAV-9372") == "NAV-9372.md"

    def test_person_slug_stable_across_rename(self):
        a = person_slug(JiraPerson(account_id="5f8a:abc-123", display_name="Jesus Lara"))
        b = person_slug(JiraPerson(account_id="5f8a:abc-123", display_name="J. Lara Gonzalez"))
        assert a == b

    def test_person_slug_is_filename_safe(self):
        slug = person_slug(JiraPerson(account_id="5f8a:abc/123", display_name="X"))
        assert not set(slug) & set('/\\:*?"<>| ')

    @pytest.mark.parametrize("name", ["navigator/forms", "multi tenant", "café"])
    def test_group_slug_filename_safe(self, name):
        slug = jira_render.group_slug(name)
        assert slug and not set(slug) & set('/\\:*?"<>| ')


class TestSatelliteNotes:
    def test_person_note(self):
        person = JiraPerson(account_id="5f8a:abc-123", display_name="Jesus Lara")
        out = render_person_note(person, ["NAV-9372", "NAV-9000"])
        assert "Jesus Lara" in out
        assert "[[NAV-9372]]" in out and "[[NAV-9000]]" in out
        assert "Person" in out
        assert "@" not in out  # G9

    def test_person_note_keys_sorted(self):
        person = JiraPerson(account_id="a", display_name="A")
        out = render_person_note(person, ["NAV-3", "NAV-1", "NAV-2"])
        assert out.index("NAV-1") < out.index("NAV-2") < out.index("NAV-3")

    @pytest.mark.parametrize("kind", ["project", "component", "label"])
    def test_group_note(self, kind):
        out = render_group_note(kind, "navigator-forms", ["NAV-9372"])
        assert "[[NAV-9372]]" in out and "navigator-forms" in out

    def test_satellite_notes_preserve_human_tail(self):
        person = JiraPerson(account_id="a", display_name="A")
        tail = f"{SYNC_MARKER}\n\nmy note\n"
        out = render_person_note(person, ["NAV-1"], existing="old\n" + tail)
        assert out.endswith(tail)


class TestPurity:
    def test_no_io_or_network_imports(self):
        src = inspect.getsource(jira_render)
        for banned in (
            "import aiohttp",
            "import requests",
            "import httpx",
            "import jira",
            "from jira ",
            "open(",
            ".write_text(",
        ):
            assert banned not in src, banned

    def test_render_takes_no_client(self):
        params = inspect.signature(render_issue_document).parameters
        assert not {"client", "llm", "model"} & set(params)
