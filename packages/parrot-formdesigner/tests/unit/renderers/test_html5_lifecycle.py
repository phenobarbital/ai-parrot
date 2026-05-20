"""Unit tests for HTML5 renderer lifecycle script injection — FEAT-188 TASK-1272.

Verifies that:
- Forms without events render identical HTML to pre-change (no lifecycle script).
- Forms with events inject the CustomEvent script block.
- CSRF meta tag is emitted only when csrf_token kwarg is provided.
- form_id is correctly embedded in the script.
- Events config is correctly embedded in the script.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.events import FormEventBinding, FormEventsConfig
from parrot_formdesigner.core.schema import FormSchema
from parrot_formdesigner.renderers.html5 import HTML5Renderer


@pytest.fixture
def renderer() -> HTML5Renderer:
    """Return a fresh HTML5Renderer instance."""
    return HTML5Renderer()


def _make_form(
    form_id: str = "f1",
    events: FormEventsConfig | None = None,
) -> FormSchema:
    """Build a minimal FormSchema."""
    return FormSchema(
        form_id=form_id,
        title={"en": "Test"},
        sections=[],
        events=events,
    )


# ---------------------------------------------------------------------------
# No-events path (acid test — spec §5)
# ---------------------------------------------------------------------------


class TestNoEvents:
    """Forms without events must not include lifecycle script."""

    async def test_no_events_no_script_tags(self, renderer: HTML5Renderer) -> None:
        """Form without events config has no lifecycle script whatsoever."""
        form = _make_form(events=None)
        out = await renderer.render(form)

        assert "parrot:before-submit" not in out.content
        assert "parrot:before-open" not in out.content
        assert "parrot-form-" not in out.content or "parrot:before" not in out.content

    async def test_no_events_no_csrf_meta(self, renderer: HTML5Renderer) -> None:
        """Form without events never emits <meta name='parrot-csrf-token'> tag."""
        form = _make_form(events=None)
        out = await renderer.render(form, csrf_token="should_be_ignored")

        assert '<meta name="parrot-csrf-token"' not in out.content

    async def test_no_events_no_script_block(self, renderer: HTML5Renderer) -> None:
        """The <script> lifecycle block is absent for event-less forms."""
        form = _make_form(events=None)
        out = await renderer.render(form)

        # The IIFE marker is the fingerprint of our lifecycle script
        assert "function()" not in out.content or "EVENTS_CONFIG" not in out.content


# ---------------------------------------------------------------------------
# With events
# ---------------------------------------------------------------------------


class TestWithEvents:
    """Forms with events must inject the CustomEvent script."""

    async def test_events_inject_script_block(self, renderer: HTML5Renderer) -> None:
        """Form with events config includes the lifecycle script block."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        out = await renderer.render(form)

        assert "parrot:before-submit" in out.content

    async def test_form_id_embedded_in_script(self, renderer: HTML5Renderer) -> None:
        """The form_id is injected into the script so multiple forms can coexist."""
        form = _make_form(form_id="my_survey", events=FormEventsConfig(
            onBeforeSubmit=FormEventBinding(handler_ref="my_survey.onBeforeSubmit"),
        ))
        out = await renderer.render(form)

        # form_id as JSON string in the script
        assert '"my_survey"' in out.content

    async def test_events_config_embedded_as_json(self, renderer: HTML5Renderer) -> None:
        """The EVENTS_CONFIG JSON is present and includes the handler_ref."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="f1.onBeforeSubmit",
                    remote=True,
                ),
            )
        )
        out = await renderer.render(form)

        # The events config JSON includes the handler_ref and remote flag
        assert "f1.onBeforeSubmit" in out.content
        assert "remote" in out.content

    async def test_before_open_event_dispatched(self, renderer: HTML5Renderer) -> None:
        """The lifecycle script emits before-open on DOMContentLoaded."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeOpen=FormEventBinding(handler_ref="f1.onBeforeOpen"),
            )
        )
        out = await renderer.render(form)

        assert "parrot:before-open" in out.content or "before-open" in out.content

    async def test_multiple_events_all_present(self, renderer: HTML5Renderer) -> None:
        """Script block is present when multiple events are configured."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
                onAfterSubmit=FormEventBinding(handler_ref="f1.onAfterSubmit"),
                onError=FormEventBinding(handler_ref="f1.onError"),
            )
        )
        out = await renderer.render(form)

        assert "parrot:before-submit" in out.content
        # EVENTS_CONFIG includes all configured events
        assert "onBeforeSubmit" in out.content
        assert "onAfterSubmit" in out.content
        assert "onError" in out.content


# ---------------------------------------------------------------------------
# CSRF meta tag
# ---------------------------------------------------------------------------


class TestCSRFMeta:
    """CSRF meta tag is emitted iff csrf_token kwarg is provided AND form has events."""

    async def test_csrf_meta_when_token_provided(self, renderer: HTML5Renderer) -> None:
        """csrf_token kwarg → <meta name='parrot-csrf-token'> in output."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="f1.onBeforeSubmit",
                    remote=True,
                ),
            )
        )
        out = await renderer.render(form, csrf_token="abc123")

        assert '<meta name="parrot-csrf-token"' in out.content
        assert "abc123" in out.content

    async def test_csrf_meta_absent_when_no_token(self, renderer: HTML5Renderer) -> None:
        """No csrf_token kwarg → no <meta name='parrot-csrf-token'> tag in output."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="f1.onBeforeSubmit",
                    remote=True,
                ),
            )
        )
        out = await renderer.render(form)

        # The <meta> tag must not be present; the JS may reference the selector string
        assert '<meta name="parrot-csrf-token"' not in out.content

    async def test_csrf_meta_absent_when_token_none(self, renderer: HTML5Renderer) -> None:
        """Explicit csrf_token=None → no <meta> tag emitted."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(
                    handler_ref="f1.onBeforeSubmit",
                    remote=True,
                ),
            )
        )
        out = await renderer.render(form, csrf_token=None)

        # The <meta> tag must not be present; the JS may reference the selector string
        assert '<meta name="parrot-csrf-token"' not in out.content

    async def test_csrf_token_is_html_escaped(self, renderer: HTML5Renderer) -> None:
        """The CSRF token value is HTML-escaped to prevent XSS."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        out = await renderer.render(form, csrf_token='tok<en"&val')

        # The token value should be escaped — raw < and " should not appear in content
        assert "<en" not in out.content
        assert '"&val' not in out.content
        assert "parrot-csrf-token" in out.content

    async def test_csrf_meta_position_before_form(self, renderer: HTML5Renderer) -> None:
        """The <meta> tag is prepended before the form HTML (not appended after)."""
        form = _make_form(
            events=FormEventsConfig(
                onBeforeSubmit=FormEventBinding(handler_ref="f1.onBeforeSubmit"),
            )
        )
        out = await renderer.render(form, csrf_token="tok123")

        # meta should appear at the start, before the <form> element
        meta_pos = out.content.find("parrot-csrf-token")
        form_pos = out.content.find("<form")
        assert meta_pos < form_pos, "CSRF meta should appear before the <form> element"
