"""XForms 1.1 (W3C) exporter for ``FormSchema``.

Maps a ``FormSchema`` to a W3C XForms 1.1 document using ``lxml``. The
output declares ``xmlns:xf="http://www.w3.org/2002/xforms"`` and
``xmlns:xs="http://www.w3.org/2001/XMLSchema"``. Per Q5 (resolved), V1
emits structural model + UI bindings AND ``<xf:bind>`` constraint
expressions derived from ``FieldConstraints``.

Output format: ``RenderedForm(content=<xml-bytes>,
content_type="application/xml")``.

Limitations:
- ``style`` / ``prefilled`` / ``errors`` arguments are accepted (per the
  base contract) but ignored; they are HTML-only concerns.
- ``DependencyRule`` mapping covers only the simple ``field_id == value``
  case; more complex AND/OR trees fall back to no ``relevant`` attribute.
- ``XFormsRenderer`` does NOT round-trip — there is no parser back to
  ``FormSchema`` (Non-Goal of FEAT-152).
"""

from __future__ import annotations

import logging
from typing import Any

from lxml import etree

from ..core.constraints import (
    ConditionOperator,
    DependencyRule,
    FieldConstraints,
)
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection, RenderedForm
from ..core.style import StyleSchema
from ..core.types import FieldType, LocalizedString
from .base import AbstractFormRenderer


logger = logging.getLogger(__name__)


XF_NS = "http://www.w3.org/2002/xforms"
XS_NS = "http://www.w3.org/2001/XMLSchema"
EV_NS = "http://www.w3.org/2001/xml-events"

NSMAP = {
    "xf": XF_NS,
    "xs": XS_NS,
    "ev": EV_NS,
}


def _qn(local: str) -> str:
    """Return a Clark-notation XForms qualified name (``{ns}local``)."""
    return f"{{{XF_NS}}}{local}"


# Mapping from FieldType → (XForms element local name, XSD type or None).
_FIELD_TO_XFORMS: dict[FieldType, tuple[str, str | None]] = {
    FieldType.TEXT: ("input", "string"),
    FieldType.TEXT_AREA: ("textarea", "string"),
    FieldType.NUMBER: ("input", "decimal"),
    FieldType.INTEGER: ("input", "integer"),
    FieldType.BOOLEAN: ("input", "boolean"),
    FieldType.DATE: ("input", "date"),
    FieldType.DATETIME: ("input", "dateTime"),
    FieldType.TIME: ("input", "time"),
    FieldType.SELECT: ("select1", "string"),
    FieldType.MULTI_SELECT: ("select", "string"),
    FieldType.FILE: ("upload", "anyURI"),
    FieldType.IMAGE: ("upload", "anyURI"),
    FieldType.COLOR: ("input", "string"),
    FieldType.URL: ("input", "anyURI"),
    FieldType.EMAIL: ("input", "string"),
    FieldType.PHONE: ("input", "string"),
    FieldType.PASSWORD: ("secret", "string"),
    FieldType.HIDDEN: ("input", "string"),
    FieldType.GROUP: ("group", None),
    FieldType.ARRAY: ("repeat", None),
}


def _localize(value: LocalizedString | None, locale: str, default: str = "") -> str:
    """Resolve a ``LocalizedString`` to a plain string."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if locale in value:
        return value[locale]
    lang = locale.split("-")[0]
    if lang in value:
        return value[lang]
    if "en" in value:
        return value["en"]
    return next(iter(value.values()), default)


def _constraint_xpath(constraints: FieldConstraints | None) -> str | None:
    """Build the XPath expression for an ``<xf:bind constraint=...>``."""
    if constraints is None:
        return None
    parts: list[str] = []
    if constraints.min_length is not None:
        parts.append(f"string-length(.) >= {constraints.min_length}")
    if constraints.max_length is not None:
        parts.append(f"string-length(.) <= {constraints.max_length}")
    if constraints.min_value is not None:
        parts.append(f". >= {constraints.min_value}")
    if constraints.max_value is not None:
        parts.append(f". <= {constraints.max_value}")
    if constraints.pattern is not None:
        # Single-quote-escape any embedded apostrophes.
        pat = constraints.pattern.replace("'", "&apos;")
        parts.append(f"regex(., '{pat}')")
    return " and ".join(parts) if parts else None


def _relevant_xpath(rule: DependencyRule | None) -> str | None:
    """Build the XPath expression for an ``<xf:bind relevant=...>``.

    Supports only the simple single-condition equality case
    (``field_id == value``). Returns ``None`` for anything more complex —
    a logger.debug message records the skip.
    """
    if rule is None or not rule.conditions:
        return None
    if len(rule.conditions) != 1:
        logger.debug(
            "Skipping `relevant` for multi-condition rule (%d conditions)",
            len(rule.conditions),
        )
        return None
    cond = rule.conditions[0]
    if cond.operator != ConditionOperator.EQ:
        logger.debug(
            "Skipping `relevant` for non-eq operator: %s", cond.operator
        )
        return None
    val = cond.value
    if isinstance(val, str):
        val_str = "'" + val.replace("'", "&apos;") + "'"
    else:
        val_str = str(val)
    return f"../{cond.field_id} = {val_str}"


class XFormsRenderer(AbstractFormRenderer):
    """Render a ``FormSchema`` as an XForms 1.1 (W3C) document.

    Output: ``RenderedForm(content=<xml-bytes>, content_type="application/xml")``.

    The renderer ignores ``style`` / ``prefilled`` / ``errors`` parameters
    (HTML-only concerns) but preserves them for base-class compatibility.
    """

    async def render(
        self,
        form: FormSchema,
        style: StyleSchema | None = None,
        *,
        locale: str = "en",
        prefilled: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> RenderedForm:
        """Render ``form`` as an XForms 1.1 XML document.

        Args:
            form: The form schema.
            style: Ignored (HTML concern).
            locale: BCP 47 locale tag for label resolution.
            prefilled: Ignored.
            errors: Ignored.

        Returns:
            ``RenderedForm`` carrying the XML bytes and ``application/xml``.
        """
        root = etree.Element(_qn("model"), nsmap=NSMAP)

        # Build <xf:instance> with the data tree.
        instance = etree.SubElement(root, _qn("instance"))
        data = etree.SubElement(instance, "data")

        # Build <xf:bind> entries (collected as we walk fields).
        binds: list[etree._Element] = []

        for section in form.sections:
            section_el = etree.SubElement(data, section.section_id)
            for field in section.fields:
                self._build_data_node(section_el, field)
                self._collect_binds(binds, section.section_id, field)

        # Place all binds inside <xf:model>.
        for bind in binds:
            root.append(bind)

        # Wrap into an outer <xf:model> + UI tree:
        # We return a single-document layout with title + sections.
        # XForms 1.1: top-level can be just a model, but to be a complete
        # form document, we wrap in <html>... For testability we expose
        # the model+UI as a single doc rooted at <xf:model>'s parent.
        wrapper = etree.Element(_qn("xforms"), nsmap=NSMAP)
        wrapper.append(root)

        title_el = etree.SubElement(wrapper, _qn("label"))
        title_el.text = _localize(form.title, locale, default=form.form_id)

        for section in form.sections:
            wrapper.append(self._build_ui_group(section, locale))

        xml_bytes = etree.tostring(
            wrapper, pretty_print=True, xml_declaration=True, encoding="UTF-8"
        )
        return RenderedForm(content=xml_bytes, content_type="application/xml")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_data_node(
        self,
        parent: etree._Element,
        field: FormField,
    ) -> None:
        """Append a data-tree node for ``field`` under ``parent``."""
        node = etree.SubElement(parent, field.field_id)
        if field.field_type == FieldType.GROUP and field.children:
            for child in field.children:
                self._build_data_node(node, child)
        elif field.field_type == FieldType.ARRAY and field.item_template:
            # Provide one empty row by default — matches XForms <xf:repeat>
            # semantics where the data tree contains the row template.
            self._build_data_node(node, field.item_template)
        else:
            if field.default is not None:
                node.text = str(field.default)

    def _collect_binds(
        self,
        binds: list[etree._Element],
        path: str,
        field: FormField,
    ) -> None:
        """Append ``<xf:bind>`` element(s) for ``field`` to ``binds``."""
        nodeset = f"{path}/{field.field_id}"
        attrs: dict[str, str] = {"nodeset": nodeset}

        _, xsd_type = _FIELD_TO_XFORMS.get(field.field_type, ("input", None))
        if xsd_type is not None:
            attrs["type"] = f"xs:{xsd_type}"

        if field.required:
            attrs["required"] = "true()"
        if field.read_only:
            attrs["readonly"] = "true()"

        constraint = _constraint_xpath(field.constraints)
        if constraint is not None:
            attrs["constraint"] = constraint

        relevant = _relevant_xpath(field.depends_on)
        if relevant is not None:
            attrs["relevant"] = relevant

        bind = etree.Element(_qn("bind"), attrib=attrs)
        binds.append(bind)

        # Recurse into containers
        if field.field_type == FieldType.GROUP and field.children:
            for child in field.children:
                self._collect_binds(binds, nodeset, child)

    def _build_ui_group(
        self, section: FormSection, locale: str
    ) -> etree._Element:
        """Build the ``<xf:group>`` UI element for ``section``."""
        group = etree.Element(_qn("group"), attrib={"id": section.section_id})
        title = _localize(section.title, locale, default=section.section_id)
        if title:
            label = etree.SubElement(group, _qn("label"))
            label.text = title
        for field in section.fields:
            group.append(self._build_ui_control(section.section_id, field, locale))
        return group

    def _build_ui_control(
        self, path: str, field: FormField, locale: str
    ) -> etree._Element:
        """Build the XForms UI element for ``field``."""
        local, _ = _FIELD_TO_XFORMS.get(field.field_type, ("input", None))
        ref = f"{path}/{field.field_id}"
        el = etree.Element(_qn(local), attrib={"ref": ref})

        # <xf:label>
        label_text = _localize(field.label, locale, default=field.field_id)
        label = etree.SubElement(el, _qn("label"))
        label.text = label_text

        # <xf:hint> — placeholder
        if field.placeholder is not None:
            hint = etree.SubElement(el, _qn("hint"))
            hint.text = _localize(field.placeholder, locale)

        # SELECT / MULTI_SELECT options
        if field.field_type in (FieldType.SELECT, FieldType.MULTI_SELECT) and field.options:
            for option in field.options:
                self._add_xf_item(el, option, locale)

        # FILE / IMAGE — mediatype hint
        if field.field_type == FieldType.IMAGE:
            el.set("mediatype", "image/*")
        elif field.field_type == FieldType.FILE:
            el.set("mediatype", "*/*")

        # HIDDEN — XForms 1.1 has no native hidden, mark via class.
        if field.field_type == FieldType.HIDDEN:
            el.set("class", "hidden")

        # GROUP — recurse into children
        if field.field_type == FieldType.GROUP and field.children:
            for child in field.children:
                el.append(self._build_ui_control(ref, child, locale))

        # ARRAY — emit <xf:repeat> body using the item template
        if field.field_type == FieldType.ARRAY and field.item_template:
            el.append(self._build_ui_control(ref, field.item_template, locale))

        return el

    def _add_xf_item(
        self,
        parent: etree._Element,
        option: FieldOption,
        locale: str,
    ) -> None:
        """Append an ``<xf:item>`` element under ``parent`` for ``option``."""
        item = etree.SubElement(parent, _qn("item"))
        label = etree.SubElement(item, _qn("label"))
        label.text = _localize(option.label, locale, default=option.value)
        value = etree.SubElement(item, _qn("value"))
        value.text = option.value
