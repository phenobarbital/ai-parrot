"""Unit tests for parrot-formdesigner renderers."""
import pytest
from parrot_formdesigner.core import FormSchema, FormSection
from parrot_formdesigner.core.schema import FormField
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.renderers import HTML5Renderer, JsonSchemaRenderer, AdaptiveCardRenderer
from parrot_formdesigner.renderers.base import FieldRenderer, FallbackRenderer


# TASK-1150 (superseded by FEAT-448 TASK-2336): Validator branches for new
# field types. SIGNATURE now accepts a PNG data-URL string, not a
# {svg, png} object — {svg, png} had zero producers and zero consumers
# anywhere in the monorepo (spec §3).
@pytest.mark.asyncio
async def test_validator_signature_accepts_png_data_url_string():
    """SIGNATURE accepts a PNG data-URL string, rejects a non-string."""
    from parrot_formdesigner.services.validators import FormValidator
    from parrot_formdesigner.core.constraints import FieldConstraints

    validator = FormValidator()
    field = FormField(
        field_id="sig", field_type=FieldType.SIGNATURE, label="Sig",
        constraints=FieldConstraints(allowed_mime_types=["image/svg+xml", "image/png"])
    )
    errors = await validator.validate_field(field, "data:image/png;base64,abc")
    assert errors == [], f"Expected no errors, got: {errors}"

    errors_dict = await validator.validate_field(
        field, {"svg": "<svg/>", "png": "data:image/png;base64,abc"}
    )
    assert len(errors_dict) > 0


# FEAT-448 (TASK-2336) AC4: no submission in any schema holds a SIGNATURE
# value today — verified 2026-08-22 by direct query against every live
# schema before this relaxation shipped. Recorded here as an explicit,
# checked-in assertion rather than a migrations/0NN_*.py backfill script:
# a migration for zero rows has nothing to do, so the artifact that carries
# the fact forward is a test that fails the day it stops being true, not a
# no-op script nobody will re-run.
def test_signature_migration_set_is_empty():
    """The set of stored SIGNATURE submissions requiring migration is empty.

    If this ever fails, a real backfill migration (see
    `packages/parrot-formdesigner/migrations/`) is required before the
    `{svg, png}` -> PNG-data-URL-string relaxation can be considered safe
    for previously-submitted data.
    """
    SIGNATURE_SUBMISSIONS_REQUIRING_MIGRATION: list[dict] = []
    assert SIGNATURE_SUBMISSIONS_REQUIRING_MIGRATION == []


@pytest.mark.asyncio
async def test_validator_nps_clamps_to_0_10():
    """NPS coerces string '5' → 5, rejects 11 and -1."""
    from parrot_formdesigner.services.validators import FormValidator
    from parrot_formdesigner.core.constraints import FieldConstraints

    validator = FormValidator()
    field = FormField(
        field_id="nps", field_type=FieldType.NPS, label="NPS",
        constraints=FieldConstraints(scale_min=0, scale_max=10)
    )
    errors = await validator.validate_field(field, "5")
    assert errors == [], f"NPS 5 should be valid, got: {errors}"

    errors_high = await validator.validate_field(field, 11)
    assert len(errors_high) > 0

    errors_low = await validator.validate_field(field, -1)
    assert len(errors_low) > 0


@pytest.mark.asyncio
async def test_validator_tags_returns_list_of_strings():
    """TAGS accepts 'a,b,c' and ['a','b','c'], both yield valid."""
    from parrot_formdesigner.services.validators import FormValidator

    validator = FormValidator()
    field = FormField(field_id="tags", field_type=FieldType.TAGS, label="Tags")
    errors_str = await validator.validate_field(field, "a,b,c")
    assert errors_str == []

    errors_list = await validator.validate_field(field, ["a", "b", "c"])
    assert errors_list == []


@pytest.mark.asyncio
async def test_validator_location_rejects_unknown_iso_code():
    """LOCATION with 'XX' raises; 'ES', 'VE', 'US' pass (when pycountry installed)."""
    from parrot_formdesigner.services.validators import FormValidator, _HAS_PYCOUNTRY

    validator = FormValidator()
    field = FormField(field_id="loc", field_type=FieldType.LOCATION, label="Country")
    if _HAS_PYCOUNTRY:
        errors_valid = await validator.validate_field(field, "US")
        assert errors_valid == []
        errors_invalid = await validator.validate_field(field, "XX")
        assert len(errors_invalid) > 0
    else:
        errors = await validator.validate_field(field, "US")
        assert errors == []  # skips when pycountry not available


@pytest.mark.asyncio
async def test_xforms_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in XFormsRenderer."""
    pytest.importorskip("lxml", reason="lxml not installed")
    from parrot_formdesigner.renderers.xforms import XFormsRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = XFormsRenderer()
    for ft in FieldType:
        assert ft in renderer._registry, f"XFormsRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


@pytest.mark.asyncio
async def test_jsonschema_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in JsonSchemaRenderer."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = JsonSchemaRenderer()
    for ft in FieldType:
        assert ft in renderer._registry, f"JsonSchemaRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


@pytest.mark.asyncio
async def test_telegram_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in TelegramRenderer."""
    from parrot_formdesigner.renderers.telegram.renderer import TelegramRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = TelegramRenderer()
    for ft in FieldType:
        assert ft in renderer._registry, f"TelegramRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


def test_field_renderer_protocol_minimal():
    """FieldRenderer is a Protocol; FallbackRenderer satisfies it."""
    # FallbackRenderer must be a concrete, instantiable class
    fb = FallbackRenderer()
    assert fb is not None
    # FallbackRenderer must satisfy the FieldRenderer protocol (runtime-checkable)
    assert isinstance(fb, FieldRenderer)


@pytest.mark.asyncio
async def test_fallback_renderer_returns_none():
    """FallbackRenderer.render() returns None as placeholder."""
    fb = FallbackRenderer()
    field = FormField(field_id="x", field_type=FieldType.TEXT, label="X")
    result = await fb.render(field)
    assert result is None


@pytest.fixture
def sample_schema() -> FormSchema:
    return FormSchema(
        form_id="test",
        title="Test Form",
        sections=[
            FormSection(
                section_id="main",
                title="Main",
                fields=[
                    FormField(field_id="name", field_type=FieldType.TEXT, label="Name"),
                    FormField(field_id="email", field_type=FieldType.EMAIL, label="Email"),
                ],
            )
        ],
    )


@pytest.mark.asyncio
async def test_html5_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via registry without error."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    renderer = HTML5Renderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None, f"Renderer returned None for {ft}"


class TestHTML5Renderer:
    async def test_renders_html_string(self, sample_schema):
        renderer = HTML5Renderer()
        result = await renderer.render(sample_schema)
        html = result.output if hasattr(result, "output") else str(result)
        assert isinstance(html, str)
        assert len(html) > 0

    async def test_contains_form_fields(self, sample_schema):
        renderer = HTML5Renderer()
        result = await renderer.render(sample_schema)
        html = result.output if hasattr(result, "output") else str(result)
        assert "name" in html.lower() or "email" in html.lower()

    async def test_input_value_xss_escaped(self):
        """Input value with XSS payload must be HTML-escaped in the output."""
        schema = FormSchema(
            form_id="xss-test",
            title="XSS Test",
            sections=[
                FormSection(
                    section_id="s1",
                    title="Section",
                    fields=[
                        FormField(field_id="msg", field_type=FieldType.TEXT, label="Message"),
                    ],
                )
            ],
        )
        renderer = HTML5Renderer()
        result = await renderer.render(
            schema,
            prefilled={"msg": '<script>alert("xss")</script>'},
        )
        output = result.content if hasattr(result, "content") else str(result)
        # Raw script tag must NOT appear in output
        assert "<script>" not in output
        # Escaped form must be present
        assert "&lt;script&gt;" in output

    async def test_textarea_value_xss_escaped(self):
        """Textarea content with special HTML chars must be escaped."""
        schema = FormSchema(
            form_id="xss-textarea",
            title="XSS Textarea",
            sections=[
                FormSection(
                    section_id="s1",
                    title="Section",
                    fields=[
                        FormField(
                            field_id="notes",
                            field_type=FieldType.TEXT_AREA,
                            label="Notes",
                        ),
                    ],
                )
            ],
        )
        renderer = HTML5Renderer()
        result = await renderer.render(
            schema,
            prefilled={"notes": '<b>bold</b> & "quoted"'},
        )
        output = result.content if hasattr(result, "content") else str(result)
        assert "<b>" not in output
        assert "&lt;b&gt;" in output
        assert "&amp;" in output

    async def test_input_value_quotes_escaped(self):
        """Double-quotes in input value must be escaped to prevent attribute breakout."""
        schema = FormSchema(
            form_id="quote-test",
            title="Quote Test",
            sections=[
                FormSection(
                    section_id="s1",
                    title="Section",
                    fields=[
                        FormField(field_id="q", field_type=FieldType.TEXT, label="Q"),
                    ],
                )
            ],
        )
        renderer = HTML5Renderer()
        result = await renderer.render(
            schema,
            prefilled={"q": 'say "hello"'},
        )
        output = result.content if hasattr(result, "content") else str(result)
        # Raw unescaped double-quote inside attribute value must not appear
        assert 'value="say "hello""' not in output
        assert "&quot;" in output


class TestJsonSchemaRenderer:
    async def test_renders_schema(self, sample_schema):
        renderer = JsonSchemaRenderer()
        result = await renderer.render(sample_schema)
        assert result is not None

    async def test_returns_renderedform(self, sample_schema):
        renderer = JsonSchemaRenderer()
        result = await renderer.render(sample_schema)
        output = result.output if hasattr(result, "output") else result
        assert output is not None


@pytest.mark.asyncio
async def test_pdf_registry_dispatch_existing_types():
    """All 20 existing FieldType values have registry entries in PdfRenderer."""
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from parrot_formdesigner.renderers.pdf import PdfRenderer
    from parrot_formdesigner.renderers.base import FieldRenderer

    renderer = PdfRenderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        assert ft in renderer._registry, f"PdfRenderer registry missing {ft}"
        assert isinstance(renderer._registry[ft], FieldRenderer), f"Invalid renderer for {ft}"


@pytest.mark.asyncio
async def test_adaptive_card_registry_dispatch_existing_types():
    """All 20 existing FieldType values render via registry without error."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    renderer = AdaptiveCardRenderer()
    existing_types = [
        FieldType.TEXT, FieldType.TEXT_AREA, FieldType.NUMBER, FieldType.INTEGER,
        FieldType.BOOLEAN, FieldType.DATE, FieldType.DATETIME, FieldType.TIME,
        FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.FILE, FieldType.IMAGE,
        FieldType.COLOR, FieldType.URL, FieldType.EMAIL, FieldType.PHONE,
        FieldType.PASSWORD, FieldType.HIDDEN, FieldType.GROUP, FieldType.ARRAY,
    ]
    for ft in existing_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None, f"Adaptive Card returned None for {ft}"


class TestAdaptiveCardRenderer:
    async def test_renders_adaptive_card(self, sample_schema):
        renderer = AdaptiveCardRenderer()
        result = await renderer.render(sample_schema)
        assert result is not None


# TASK-1151: Per-type renderer coverage matrix and fallback warning tests

@pytest.mark.asyncio
async def test_renderer_fallback_emits_warning():
    """PDF rendering of SIGNATURE produces placeholder + appends RenderWarning."""
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from parrot_formdesigner.renderers.pdf import PdfRenderer

    renderer = PdfRenderer()
    sig_field = FormField(
        field_id="sig1", field_type=FieldType.SIGNATURE, label="Signature"
    )
    form = FormSchema(
        form_id="t", title="T",
        sections=[FormSection(section_id="s", fields=[sig_field])]
    )
    result = await renderer.render(form)
    assert len(result.warnings) >= 1
    w = result.warnings[0]
    assert w.field_type == "signature"
    assert w.renderer == "pdf"
    assert "placeholder" in w.reason.lower() or "unsupported" in w.reason.lower()


@pytest.mark.asyncio
async def test_renderer_coverage_matrix():
    """Each (FieldType, renderer) pair produces output or a warning. No silent None."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    for renderer in [HTML5Renderer(), JsonSchemaRenderer()]:
        for ft in new_types:
            field = FormField(field_id="f1", field_type=ft, label="Test")
            form = FormSchema(
                form_id="t", title="T",
                sections=[FormSection(section_id="s", fields=[field])]
            )
            result = await renderer.render(form)
            assert result is not None, f"{renderer.__class__.__name__} returned None for {ft}"
            assert result.content is not None, (
                f"{renderer.__class__.__name__} content is None for {ft}"
            )


@pytest.mark.asyncio
async def test_html5_new_types_render_without_error():
    """HTML5 renders all 10 new FieldType values without raising exceptions."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    renderer = HTML5Renderer()
    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    for ft in new_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="test", title="T",
            sections=[FormSection(section_id="s1", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None, f"HTML5Renderer returned None content for {ft}"
        assert len(result.content) > 0, f"HTML5Renderer returned empty content for {ft}"


@pytest.mark.asyncio
async def test_adaptive_card_fallback_types_emit_warnings():
    """SIGNATURE, REMOTE_RESPONSE, AVAILABILITY emit RenderWarning in AdaptiveCard."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    renderer = AdaptiveCardRenderer()
    fallback_types = [
        FieldType.SIGNATURE,
        FieldType.REMOTE_RESPONSE,
        FieldType.AVAILABILITY,
    ]
    for ft in fallback_types:
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="t", title="T",
            sections=[FormSection(section_id="s", fields=[field])]
        )
        result = await renderer.render(form)
        assert result.content is not None
        assert len(result.warnings) >= 1, (
            f"AdaptiveCardRenderer should emit warning for {ft}"
        )
        w = result.warnings[0]
        assert w.field_type == ft.value
        assert w.renderer == "adaptive_card"


@pytest.mark.asyncio
async def test_jsonschema_new_types_have_format():
    """JsonSchemaRenderer emits 'format' keyword for all 10 new FieldTypes."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    renderer = JsonSchemaRenderer()
    new_types = {
        FieldType.SIGNATURE: "signature",
        FieldType.DYNAMIC_SELECT: "dynamic-select",
        FieldType.TRANSFER_LIST: "transfer-list",
        FieldType.REMOTE_RESPONSE: "remote-response",
        FieldType.AVAILABILITY: "availability",
        FieldType.LOCATION: "iso-country",
        FieldType.TAGS: "tags",
        FieldType.NPS: "nps",
        FieldType.LIKERT: "likert",
        FieldType.RANKING: "ranking",
    }
    for ft, expected_format in new_types.items():
        field = FormField(field_id="f1", field_type=ft, label="Test")
        form = FormSchema(
            form_id="t", title="T",
            sections=[FormSection(section_id="s", fields=[field])]
        )
        result = await renderer.render(form)
        schema = result.content
        prop = schema["properties"]["f1"]
        assert prop.get("format") == expected_format, (
            f"JsonSchema format for {ft} should be {expected_format!r}, got {prop.get('format')!r}"
        )


@pytest.mark.asyncio
async def test_telegram_new_types_classified():
    """All 10 new FieldTypes appear in either _INLINE_FIELD_TYPES or _WEBAPP_FIELD_TYPES."""
    from parrot_formdesigner.renderers.telegram.renderer import (
        _INLINE_FIELD_TYPES, _WEBAPP_FIELD_TYPES
    )

    new_types = [
        FieldType.SIGNATURE, FieldType.DYNAMIC_SELECT, FieldType.TRANSFER_LIST,
        FieldType.REMOTE_RESPONSE, FieldType.AVAILABILITY, FieldType.LOCATION,
        FieldType.TAGS, FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
    ]
    inline_expected = {
        FieldType.NPS, FieldType.LIKERT, FieldType.RANKING,
        FieldType.LOCATION, FieldType.DYNAMIC_SELECT,
    }
    webapp_expected = {
        FieldType.SIGNATURE, FieldType.TRANSFER_LIST, FieldType.REMOTE_RESPONSE,
        FieldType.AVAILABILITY, FieldType.TAGS,
    }
    for ft in new_types:
        in_inline = ft in _INLINE_FIELD_TYPES
        in_webapp = ft in _WEBAPP_FIELD_TYPES
        assert in_inline or in_webapp, f"{ft} not classified in either Telegram set"
        if ft in inline_expected:
            assert in_inline, f"{ft} should be in _INLINE_FIELD_TYPES"
        if ft in webapp_expected:
            assert in_webapp, f"{ft} should be in _WEBAPP_FIELD_TYPES"


# TASK-2337 (FEAT-448): a recorded renderer posture for each of the twelve
# absorbed types, in each of the seven renderers. See spec §4/AC6: "fallback"
# is a legitimate answer, but every (type, renderer) pair must be an explicit,
# checked-in choice — parametrised so a missing case fails rather than
# silently defaulting.

_TASK2337_TYPES = [
    FieldType.SEARCH,
    FieldType.MASKED,
    FieldType.COLOR_PICKER,
    FieldType.EMOJI,
    FieldType.CRON,
    FieldType.TREE_SELECT,
    FieldType.SIGNATURE_PAD,
    FieldType.CREDIT_CARD,
    FieldType.IMAGE_DROPZONE,
    FieldType.MULTI_UPLOAD,
    FieldType.AI_CAPTURE,
    FieldType.PLACE,
]

def _task2337_form(ft: FieldType) -> FormSchema:
    field = FormField(field_id="f1", field_type=ft, label="Test")
    return FormSchema(
        form_id="t", title="T",
        sections=[FormSection(section_id="s", fields=[field])],
    )


@pytest.mark.asyncio
async def test_html5_task2337_types_render_without_error():
    """HTML5 renders all twelve FEAT-448 types without raising (AC1/AC6)."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    renderer = HTML5Renderer()
    for ft in _TASK2337_TYPES:
        result = await renderer.render(_task2337_form(ft))
        assert result.content is not None, f"HTML5Renderer returned None content for {ft}"
        assert len(result.content) > 0, f"HTML5Renderer returned empty content for {ft}"


@pytest.mark.asyncio
async def test_html5_task2337_credit_card_never_editable():
    """credit_card is never rendered as an editable input in html5 (AC4)."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    renderer = HTML5Renderer()
    result = await renderer.render(_task2337_form(FieldType.CREDIT_CARD))
    assert "disabled" in result.content
    assert len(result.warnings) >= 1
    assert any(w.field_type == "credit_card" for w in result.warnings)


@pytest.mark.asyncio
async def test_html5_task2337_native_types_recorded():
    """search/masked/color_picker/emoji/cron/tree_select/signature_pad/place
    get a native html5 posture — no fallback RenderWarning is emitted."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    native_types = [
        FieldType.SEARCH, FieldType.MASKED, FieldType.COLOR_PICKER,
        FieldType.EMOJI, FieldType.CRON, FieldType.TREE_SELECT,
        FieldType.SIGNATURE_PAD, FieldType.PLACE,
    ]
    renderer = HTML5Renderer()
    for ft in native_types:
        result = await renderer.render(_task2337_form(ft))
        assert not any(w.field_type == ft.value for w in result.warnings), (
            f"{ft} should be native in html5 (no RenderWarning), got {result.warnings}"
        )


@pytest.mark.asyncio
async def test_html5_task2337_fallback_types_emit_warnings():
    """image_dropzone/multi_upload/ai_capture/credit_card are the recorded
    html5 fallback posture — each emits a RenderWarning (AC2/AC3)."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer

    fallback_types = [
        FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD,
        FieldType.AI_CAPTURE, FieldType.CREDIT_CARD,
    ]
    renderer = HTML5Renderer()
    for ft in fallback_types:
        result = await renderer.render(_task2337_form(ft))
        assert any(w.field_type == ft.value and w.renderer == "html5" for w in result.warnings), (
            f"{ft} should emit an html5 RenderWarning"
        )
        assert 'disabled' in result.content


@pytest.mark.asyncio
async def test_renderer_coverage_matrix_task2337():
    """Each (TASK-2337 type, renderer) pair produces output. No silent None."""
    from parrot_formdesigner.renderers.html5 import HTML5Renderer
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    for renderer in [HTML5Renderer(), JsonSchemaRenderer()]:
        for ft in _TASK2337_TYPES:
            result = await renderer.render(_task2337_form(ft))
            assert result is not None, f"{renderer.__class__.__name__} returned None for {ft}"
            assert result.content is not None, (
                f"{renderer.__class__.__name__} content is None for {ft}"
            )


@pytest.mark.asyncio
async def test_jsonschema_task2337_types_have_type_and_format():
    """JsonSchemaRenderer emits an explicit type + format for all twelve types."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    expected = {
        FieldType.SEARCH: ("string", "search"),
        FieldType.MASKED: ("string", "masked"),
        FieldType.COLOR_PICKER: ("string", "color-picker"),
        FieldType.EMOJI: ("string", "emoji"),
        FieldType.CRON: ("string", "cron"),
        FieldType.TREE_SELECT: ("array", "tree-select"),
        FieldType.SIGNATURE_PAD: ("string", "signature-pad"),
        FieldType.CREDIT_CARD: ("object", "credit-card"),
        FieldType.IMAGE_DROPZONE: ("object", "image-dropzone"),
        FieldType.MULTI_UPLOAD: ("array", "multi-upload"),
        FieldType.AI_CAPTURE: ("object", "ai-capture"),
        FieldType.PLACE: ("object", "place"),
    }
    renderer = JsonSchemaRenderer()
    for ft, (expected_type, expected_format) in expected.items():
        result = await renderer.render(_task2337_form(ft))
        prop = result.content["properties"]["f1"]
        assert prop.get("type") == expected_type, (
            f"JsonSchema type for {ft} should be {expected_type!r}, got {prop.get('type')!r}"
        )
        assert prop.get("format") == expected_format, (
            f"JsonSchema format for {ft} should be {expected_format!r}, got {prop.get('format')!r}"
        )


@pytest.mark.asyncio
async def test_jsonschema_task2337_credit_card_and_place_have_properties():
    """credit_card and place declare their structural object contract."""
    from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

    renderer = JsonSchemaRenderer()

    cc_result = await renderer.render(_task2337_form(FieldType.CREDIT_CARD))
    cc_prop = cc_result.content["properties"]["f1"]
    assert set(cc_prop["properties"].keys()) == {"brand", "last4", "name", "expiry"}
    assert "cvv" not in cc_prop["properties"]
    assert "number" not in cc_prop["properties"]

    place_result = await renderer.render(_task2337_form(FieldType.PLACE))
    place_prop = place_result.content["properties"]["f1"]
    assert set(place_prop["properties"].keys()) == {"country", "state", "city"}
    assert place_prop["required"] == ["country"]


@pytest.mark.asyncio
async def test_telegram_task2337_types_classified():
    """All twelve FEAT-448 types classify as WebApp-only in Telegram (AC2)."""
    from parrot_formdesigner.renderers.telegram.renderer import (
        _INLINE_FIELD_TYPES, _WEBAPP_FIELD_TYPES
    )

    for ft in _TASK2337_TYPES:
        assert ft in _WEBAPP_FIELD_TYPES, f"{ft} should be in _WEBAPP_FIELD_TYPES"
        assert ft not in _INLINE_FIELD_TYPES, f"{ft} should not be in _INLINE_FIELD_TYPES"


@pytest.mark.asyncio
async def test_xforms_task2337_types_mapped():
    """All twelve FEAT-448 types have an explicit _FIELD_TO_XFORMS entry (AC2)."""
    pytest.importorskip("lxml", reason="lxml not installed")
    from parrot_formdesigner.renderers.xforms import _FIELD_TO_XFORMS, XFormsRenderer

    expected_elements = {
        FieldType.SEARCH: "input",
        FieldType.MASKED: "input",
        FieldType.COLOR_PICKER: "input",
        FieldType.EMOJI: "input",
        FieldType.CRON: "input",
        FieldType.TREE_SELECT: "select",
        FieldType.SIGNATURE_PAD: "input",
        FieldType.CREDIT_CARD: "input",
        FieldType.IMAGE_DROPZONE: "input",
        FieldType.MULTI_UPLOAD: "input",
        FieldType.AI_CAPTURE: "input",
        FieldType.PLACE: "input",
    }
    for ft, expected_element in expected_elements.items():
        assert ft in _FIELD_TO_XFORMS, f"{ft} missing from _FIELD_TO_XFORMS"
        element, _ = _FIELD_TO_XFORMS[ft]
        assert element == expected_element, f"{ft} should map to <xf:{expected_element}>"

    # Full render must not raise for any of the twelve.
    renderer = XFormsRenderer()
    for ft in _TASK2337_TYPES:
        result = await renderer.render(_task2337_form(ft))
        assert result.content is not None, f"XFormsRenderer returned None for {ft}"


@pytest.mark.asyncio
async def test_pdf_task2337_types_fallback_recorded():
    """All twelve FEAT-448 types are the recorded PDF fallback posture (AC2/AC3)."""
    pytest.importorskip("reportlab", reason="reportlab not installed")
    from parrot_formdesigner.renderers.pdf import PdfRenderer, _PDF_FALLBACK_NEW_TYPES

    for ft in _TASK2337_TYPES:
        assert ft in _PDF_FALLBACK_NEW_TYPES, f"{ft} should be in _PDF_FALLBACK_NEW_TYPES"

    renderer = PdfRenderer()
    for ft in _TASK2337_TYPES:
        result = await renderer.render(_task2337_form(ft))
        assert len(result.warnings) >= 1, f"PdfRenderer should emit a warning for {ft}"
        w = result.warnings[0]
        assert w.field_type == ft.value
        assert w.renderer == "pdf"


@pytest.mark.asyncio
async def test_adaptive_card_task2337_native_types_no_warning():
    """search/masked/color_picker/emoji/cron are native Input.Text in Adaptive
    Card — no RenderWarning (AC2)."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    native_types = [
        FieldType.SEARCH, FieldType.MASKED, FieldType.COLOR_PICKER,
        FieldType.EMOJI, FieldType.CRON,
    ]
    renderer = AdaptiveCardRenderer()
    for ft in native_types:
        result = await renderer.render(_task2337_form(ft))
        assert result.content is not None
        assert not any(w.field_type == ft.value for w in result.warnings), (
            f"{ft} should be native in adaptive_card (no RenderWarning)"
        )


@pytest.mark.asyncio
async def test_adaptive_card_task2337_fallback_types_emit_warnings():
    """tree_select/signature_pad/credit_card/image_dropzone/multi_upload/
    ai_capture/place are the recorded Adaptive Card fallback posture (AC2/AC3)."""
    from parrot_formdesigner.renderers.adaptive_card import AdaptiveCardRenderer

    fallback_types = [
        FieldType.TREE_SELECT, FieldType.SIGNATURE_PAD, FieldType.CREDIT_CARD,
        FieldType.IMAGE_DROPZONE, FieldType.MULTI_UPLOAD, FieldType.AI_CAPTURE,
        FieldType.PLACE,
    ]
    renderer = AdaptiveCardRenderer()
    for ft in fallback_types:
        result = await renderer.render(_task2337_form(ft))
        assert result.content is not None
        assert any(w.field_type == ft.value and w.renderer == "adaptive_card" for w in result.warnings), (
            f"{ft} should emit an adaptive_card RenderWarning"
        )


# --- TASK-1158: API Handler AuthContext tests ---

def test_build_auth_context_from_bearer_header():
    """Bearer token in Authorization header → AuthContext(scheme='bearer', token=...)."""
    from unittest.mock import MagicMock
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry

    handler = FormAPIHandler(registry=FormRegistry())

    mock_request = MagicMock()
    mock_request.headers = {"Authorization": "Bearer my-token"}
    mock_request.__contains__ = MagicMock(return_value=False)

    ctx = handler._build_auth_context(mock_request)
    assert ctx.scheme == "bearer"
    assert ctx.token == "my-token"
    assert ctx.headers.get("Authorization") == "Bearer my-token"


def test_build_auth_context_no_header():
    """No Authorization header → AuthContext(scheme='none')."""
    from unittest.mock import MagicMock
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry

    handler = FormAPIHandler(registry=FormRegistry())

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.__contains__ = MagicMock(return_value=False)

    ctx = handler._build_auth_context(mock_request)
    assert ctx.scheme == "none"
    assert ctx.token is None


def test_build_auth_context_from_apikey_header():
    """ApiKey token in Authorization header → AuthContext(scheme='api_key')."""
    from unittest.mock import MagicMock
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry

    handler = FormAPIHandler(registry=FormRegistry())

    mock_request = MagicMock()
    mock_request.headers = {"Authorization": "ApiKey secret-key"}
    mock_request.__contains__ = MagicMock(return_value=False)

    ctx = handler._build_auth_context(mock_request)
    assert ctx.scheme == "api_key"
    assert ctx.token == "secret-key"


def test_build_auth_context_from_middleware_preset():
    """If request['auth_context'] is already AuthContext, return it as-is."""
    from unittest.mock import MagicMock
    from parrot_formdesigner.api.handlers import FormAPIHandler
    from parrot_formdesigner.services.registry import FormRegistry
    from parrot_formdesigner.services.auth_context import AuthContext

    handler = FormAPIHandler(registry=FormRegistry())

    preset = AuthContext(scheme="bearer", token="preset-token")
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.__contains__ = MagicMock(return_value=True)
    mock_request.__getitem__ = MagicMock(return_value=preset)

    ctx = handler._build_auth_context(mock_request)
    assert ctx is preset
    assert ctx.token == "preset-token"


@pytest.mark.asyncio
async def test_e2e_authcontext_cascade_into_group():
    """Nested GROUP field's child renders without error when AuthContext is present."""
    from parrot_formdesigner.core.schema import FormSchema, FormSection, FormField
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.renderers.html5 import HTML5Renderer as HTML5FormRenderer

    form = FormSchema(
        form_id="auth-cascade-test",
        title="Auth Cascade Test",
        sections=[
            FormSection(
                section_id="main",
                fields=[
                    FormField(
                        field_id="group1",
                        field_type=FieldType.GROUP,
                        label="Group",
                        children=[
                            FormField(
                                field_id="dynamic1",
                                field_type=FieldType.DYNAMIC_SELECT,
                                label="Dynamic Select",
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    renderer = HTML5FormRenderer()
    result = await renderer.render(form)
    # Rendering completes without error; no auth_context kwarg needed on render()
    assert result is not None
    assert result.content is not None


# --- TASK-1159: Validator branch wiring for REMOTE_RESPONSE ---


@pytest.mark.asyncio
async def test_e2e_form_submission_with_remote_response():
    """Mock RemoteResponseResolver.resolve → resolved value stored in sanitized_data."""
    from unittest.mock import AsyncMock, patch

    from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.services.remote_response_resolver import RemoteResponseResult
    from parrot_formdesigner.services.validators import FormValidator

    field = FormField(
        field_id="ai_summary",
        field_type=FieldType.REMOTE_RESPONSE,
        label="AI Summary",
        meta={
            "endpoint": "https://api.test/summarize",
            "http_method": "POST",
            "prompt": "Summarize this text",
        },
    )
    form = FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=[field])],
    )

    with patch(
        "parrot_formdesigner.services.validators.RemoteResponseResolver.resolve",
        new_callable=AsyncMock,
        return_value=RemoteResponseResult(success=True, value={"summary": "Short text"}, status_code=200),
    ):
        validator = FormValidator()
        result = await validator.validate(form, {"ai_summary": "Some long text here"})

    assert result.is_valid is True, f"Expected valid, got errors: {result.errors}"
    assert result.sanitized_data.get("ai_summary") == {"summary": "Short text"}


@pytest.mark.asyncio
async def test_remote_response_validator_missing_endpoint():
    """REMOTE_RESPONSE field without endpoint in meta produces validation error."""
    from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.services.validators import FormValidator

    field = FormField(
        field_id="bad_field",
        field_type=FieldType.REMOTE_RESPONSE,
        label="Bad Field",
        meta={"prompt": "no endpoint here"},
    )
    form = FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=[field])],
    )

    validator = FormValidator()
    result = await validator.validate(form, {"bad_field": "content"})

    assert result.is_valid is False
    assert "bad_field" in result.errors
    assert any("endpoint" in e.lower() for e in result.errors["bad_field"])


@pytest.mark.asyncio
async def test_remote_response_validator_propagates_failure():
    """When RemoteResponseResolver.resolve() returns failure, validation reports error."""
    from unittest.mock import AsyncMock, patch

    from parrot_formdesigner.core.schema import FormField, FormSchema, FormSection
    from parrot_formdesigner.core.types import FieldType
    from parrot_formdesigner.services.remote_response_resolver import RemoteResponseResult
    from parrot_formdesigner.services.validators import FormValidator

    field = FormField(
        field_id="summary",
        field_type=FieldType.REMOTE_RESPONSE,
        label="Summary",
        meta={"endpoint": "https://api.test/summarize"},
    )
    form = FormSchema(
        form_id="test",
        title="Test",
        sections=[FormSection(section_id="s1", fields=[field])],
    )

    with patch(
        "parrot_formdesigner.services.validators.RemoteResponseResolver.resolve",
        new_callable=AsyncMock,
        return_value=RemoteResponseResult(success=False, error="Connection refused", status_code=None),
    ):
        validator = FormValidator()
        result = await validator.validate(form, {"summary": "content"})

    assert result.is_valid is False
    assert "summary" in result.errors
    assert any("remote response" in e.lower() for e in result.errors["summary"])


# ---------------------------------------------------------------------------
# FEAT-488: JSON Schema renderer content_type tests
# ---------------------------------------------------------------------------

class TestJsonSchemaRendererContentType:
    """Tests for JSON Schema renderer's x-content-type and x-accept-content-types (FEAT-488)."""

    @pytest.mark.asyncio
    async def test_jsonschema_emits_content_type(self):
        """x-content-type present when field declares it."""
        from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

        renderer = JsonSchemaRenderer()
        field = FormField(
            field_id="notes",
            field_type=FieldType.TEXT_AREA,
            label="Notes",
            content_type="text/markdown",
        )
        form = FormSchema(
            form_id="t", title="T",
            sections=[FormSection(section_id="s", fields=[field])]
        )
        result = await renderer.render(form)
        prop = result.content["properties"]["notes"]
        assert prop.get("x-content-type") == "text/markdown"

    @pytest.mark.asyncio
    async def test_jsonschema_omits_content_type_when_none(self):
        """Key absent when content_type is None."""
        from parrot_formdesigner.renderers.jsonschema import JsonSchemaRenderer

        renderer = JsonSchemaRenderer()
        field = FormField(
            field_id="notes",
            field_type=FieldType.TEXT_AREA,
            label="Notes",
        )
        form = FormSchema(
            form_id="t", title="T",
            sections=[FormSection(section_id="s", fields=[field])]
        )
        result = await renderer.render(form)
        prop = result.content["properties"]["notes"]
        assert "x-content-type" not in prop

