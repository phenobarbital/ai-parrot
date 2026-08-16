"""HTML page handlers for parrot-formdesigner.

Serves the form builder UI: index, gallery, render form, submit form.

Every handler reads the optional URL mount prefix from
``request.app["_form_prefix"]`` (populated by ``setup_form_routes``) and
forwards it to the page-template builders so that links and form
actions match the routes registered by aiohttp.
"""

from __future__ import annotations

import json
import logging
from html import escape

from aiohttp import web

from ..core.style import LayoutType, StyleSchema
from ..renderers.html5 import HTML5Renderer
from ..services.registry import FormRegistry
from ..services.validators import FormValidator
from ..renderers.jsonschema import JsonSchemaRenderer
from .templates import error_page, form_page, gallery_page, index_page, page_shell, schema_page


def _prefix(request: web.Request) -> str:
    """Return the form-designer mount prefix for this request.

    Reads the value populated by ``setup_form_routes`` at registration
    time. Falls back to ``""`` when the app was wired without a prefix
    (legacy behaviour, routes at root).
    """
    return request.app.get("_form_prefix", "")


class FormPageHandler:
    """Serves HTML pages for the form builder UI.

    Args:
        registry: FormRegistry instance for looking up forms.
        renderer: HTML5Renderer for rendering form HTML.
        validator: FormValidator for validating submissions.
    """

    def __init__(
        self,
        registry: FormRegistry,
        renderer: HTML5Renderer | None = None,
        validator: FormValidator | None = None,
    ) -> None:
        self.registry = registry
        self.renderer = renderer or HTML5Renderer()
        self.schema_renderer = JsonSchemaRenderer()
        self.validator = validator or FormValidator()
        self.logger = logging.getLogger(__name__)

    async def index(self, request: web.Request) -> web.Response:
        """GET / — Landing page with prompt input and DB form loader.

        Args:
            request: Incoming HTTP request.

        Returns:
            HTML page response.
        """
        p = _prefix(request)
        # FEAT-421: read directly from match_info (URL-declared, already
        # validated by @requires_tenant at route-registration time) rather
        # than importing api.tenant.declared_tenant() here, which would
        # widen the existing ui->api coupling (see TASK-2200's completion
        # note) beyond what this template-URL fix needs.
        tenant = request.match_info.get("tenant", "")
        return web.Response(
            text=page_shell(
                "Create a Form",
                index_page(prefix=p, tenant=tenant),
                prefix=p,
                tenant=tenant,
            ),
            content_type="text/html",
        )

    async def gallery(self, request: web.Request) -> web.Response:
        """GET /gallery — List all previously generated forms.

        Args:
            request: Incoming HTTP request.

        Returns:
            HTML page response with the form gallery.
        """
        p = _prefix(request)
        # FEAT-421 review fix: this handler previously always resolved
        # tenant=None (-> registry.default_tenant), completely ignoring the
        # tenant declared and authorized in the URL by @requires_tenant —
        # a pre-existing gap (ui/handlers.py was never in the spec's 30
        # classified call sites) that this fix closes so the gallery
        # actually reflects the declared tenant's forms.
        tenant = request.match_info.get("tenant") or None
        forms = await self.registry.list_forms(tenant=tenant)

        if not forms:
            items_html = (
                f"<p>No forms created yet. "
                f"<a href='{p}/t/{escape(tenant or '')}/'>Create one!</a></p>"
            )
        else:
            items = []
            for form in forms:
                # FEAT-389: fid drives the "Open"/"Schema" links below, which
                # must match the {form_uid}-keyed UI routes (TASK-1981) — so
                # it is the immutable form_uid, not the mutable form_id slug.
                fid = form.form_uid
                title = form.title if isinstance(form.title, str) else form.title.get("en", fid)
                items.append(
                    f'<li>'
                    f'<span><strong>{escape(title)}</strong> '
                    f'<span style="color:var(--muted);font-size:.85rem">({escape(fid)})</span></span>'
                    f'<span style="display:flex;gap:.5rem;">'
                    f'<a href="{p}/t/{escape(tenant or "")}/forms/{escape(fid)}" class="btn btn-secondary" '
                    f'style="padding:.35rem .8rem; font-size:.85rem;">Open</a>'
                    f'<a href="{p}/t/{escape(tenant or "")}/forms/{escape(fid)}/schema" class="btn btn-secondary" '
                    f'style="padding:.35rem .8rem; font-size:.85rem;">Schema</a>'
                    f'</span>'
                    f'</li>'
                )
            items_html = f'<ul class="form-list">{"".join(items)}</ul>'

        return web.Response(
            text=page_shell(
                "Gallery", gallery_page(items_html), prefix=p, tenant=tenant or ""
            ),
            content_type="text/html",
        )

    async def render_form(self, request: web.Request) -> web.Response:
        """GET /forms/{form_uid} — Render the form as an HTML page.

        Args:
            request: Incoming HTTP request.

        Returns:
            HTML page with the rendered form, or 404 if not found.
        """
        p = _prefix(request)
        form_uid = request.match_info["form_uid"]
        # FEAT-421 review fix: see gallery()'s comment — resolve the
        # URL-declared tenant instead of always defaulting.
        tenant = request.match_info.get("tenant") or None
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return web.Response(
                text=page_shell(
                    "Not Found",
                    error_page("Form not found.", prefix=p, tenant=tenant or ""),
                    prefix=p,
                    tenant=tenant or "",
                ),
                status=404,
                content_type="text/html",
            )

        layout_name = request.query.get("layout", "single_column")
        try:
            layout = LayoutType(layout_name)
        except ValueError:
            layout = LayoutType.SINGLE_COLUMN

        style = StyleSchema(layout=layout)
        rendered = await self.renderer.render(form, style=style)
        t = escape(tenant or "")
        fragment = rendered.content.replace(
            "<form ",
            f'<form action="{p}/t/{t}/forms/{escape(form_uid)}" method="post" ',
            1,
        )

        title = form.title if isinstance(form.title, str) else form.title.get("en", "Form")
        schema_link = (
            f'<div style="margin-top:1rem;">'
            f'<a href="{p}/t/{t}/forms/{escape(form_uid)}/schema" class="btn btn-secondary"'
            f' style="font-size:.85rem;">View JSON Schema</a></div>'
        )
        return web.Response(
            text=page_shell(
                title,
                form_page(fragment) + schema_link,
                prefix=p,
                tenant=tenant or "",
            ),
            content_type="text/html",
        )

    async def view_schema(self, request: web.Request) -> web.Response:
        """GET /forms/{form_uid}/schema — Display JSON Schema as an HTML page.

        Args:
            request: Incoming HTTP request.

        Returns:
            HTML page with pretty-printed JSON Schema and Style Schema.
        """
        p = _prefix(request)
        form_uid = request.match_info["form_uid"]
        # FEAT-421 review fix: see gallery()'s comment — resolve the
        # URL-declared tenant instead of always defaulting.
        tenant = request.match_info.get("tenant") or None
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return web.Response(
                text=page_shell(
                    "Not Found",
                    error_page("Form not found.", prefix=p, tenant=tenant or ""),
                    prefix=p,
                    tenant=tenant or "",
                ),
                status=404,
                content_type="text/html",
            )

        rendered = await self.schema_renderer.render(form)
        schema_data = rendered.content
        style_data = rendered.style_output or {}

        schema_json = json.dumps(schema_data, indent=2, ensure_ascii=False)
        style_json = json.dumps(style_data, indent=2, ensure_ascii=False)

        title = form.title if isinstance(form.title, str) else form.title.get("en", "Form")
        return web.Response(
            text=page_shell(
                f"{title} - JSON Schema",
                schema_page(
                    form_uid,
                    title,
                    schema_json,
                    style_json,
                    prefix=p,
                    tenant=form.tenant or "",
                ),
                prefix=p,
                # FEAT-421 review fix (2nd pass): every sibling page_shell()
                # call passes tenant= so the top nav ("New Form"/"Gallery")
                # links stay tenant-qualified — this one was missing it,
                # which rendered them as "{prefix}/t//" (empty segment).
                tenant=form.tenant or "",
            ),
            content_type="text/html",
        )

    async def submit_form(self, request: web.Request) -> web.Response:
        """POST /forms/{form_uid} — Validate submission, show result.

        Args:
            request: Incoming HTTP request with form POST data.

        Returns:
            HTML page showing success or re-rendered form with errors.
        """
        p = _prefix(request)
        form_uid = request.match_info["form_uid"]
        # FEAT-421 review fix: see gallery()'s comment — resolve the
        # URL-declared tenant instead of always defaulting.
        tenant = request.match_info.get("tenant") or None
        form = await self.registry.get(form_uid, tenant=tenant)
        if form is None:
            return web.Response(
                text=page_shell(
                    "Not Found",
                    error_page("Form not found.", prefix=p, tenant=tenant or ""),
                    prefix=p,
                    tenant=tenant or "",
                ),
                status=404,
                content_type="text/html",
            )

        data = await request.post()
        submission = dict(data)
        result = await self.validator.validate(form, submission)
        title = form.title if isinstance(form.title, str) else form.title.get("en", "Form")

        if result.is_valid:
            sanitized_json = json.dumps(result.sanitized_data, indent=2, default=str)
            body = f"""\
<div class="success">
  <h2>Submitted successfully</h2>
  <p>The form data passed all validations.</p>
</div>
<div class="card">
  <h3>Submitted Data</h3>
  <pre>{escape(sanitized_json)}</pre>
</div>
<div style="display:flex; gap:.75rem;">
  <a href="{p}/t/{escape(tenant or "")}/forms/{escape(form_uid)}" class="btn btn-secondary">Fill again</a>
  <a href="{p}/t/{escape(tenant or "")}/" class="btn btn-primary">Create another form</a>
</div>"""
            return web.Response(
                text=page_shell(
                    f"{title} - Success", body, prefix=p, tenant=tenant or ""
                ),
                content_type="text/html",
            )

        rendered = await self.renderer.render(form, prefilled=submission, errors=result.errors)
        fragment = rendered.content.replace(
            "<form ",
            f'<form action="{p}/t/{escape(tenant or "")}/forms/{escape(form_uid)}" method="post" ',
            1,
        )
        error_count = len(result.errors)
        banner = (
            f'<div class="error-banner">'
            f'Please fix {error_count} error{"s" if error_count != 1 else ""} below.'
            f'</div>'
        )
        return web.Response(
            text=page_shell(
                title,
                f'{banner}<div class="card">{fragment}</div>',
                prefix=p,
                tenant=tenant or "",
            ),
            content_type="text/html",
        )
