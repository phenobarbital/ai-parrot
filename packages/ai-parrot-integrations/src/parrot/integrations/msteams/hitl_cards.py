"""
Adaptive Card renderer for the Teams HITL channel.

Maps every :class:`~parrot.human.models.InteractionType` value to an
Adaptive Card dict that includes ``interaction_id`` in every
``Action.Submit.data`` payload.  The cards are designed for
deterministic correlation: even when multiple pending interactions
exist in the same 1:1 chat, the ``interaction_id`` field uniquely
binds each card submit to its originating interaction.

Card structure (all cards):
- Header ``TextBlock`` with the question.
- Type-specific input controls.
- One or more ``Action.Submit`` buttons where every ``data`` payload
  carries at minimum::

      {
          "hitl": true,
          "interaction_id": "<uuid>",
          # type-specific fields
      }

Policy-bound interactions can optionally include an "Escalar" action
(``data.value == ESCALATE_OPTION_KEY``) when the channel's
``render_reject_button`` flag is ``True``.

OQ-5 resolution -- ``form_schema`` -> ``Input.*`` mapping:
  - ``"string"`` -> ``Input.Text`` (single-line unless ``multiline: true``)
  - ``"text"`` or ``"textarea"`` -> ``Input.Text`` (multiline)
  - ``"integer"`` or ``"number"`` -> ``Input.Number``
  - ``"boolean"`` -> ``Input.Toggle``
  - ``"choice"`` or ``"select"`` -> ``Input.ChoiceSet`` (compact, single)
  - ``"multi_choice"`` or ``"multi_select"`` -> ``Input.ChoiceSet`` (multi)
  - ``"date"`` -> ``Input.Date``
  - ``"time"`` -> ``Input.Time``
  - unknown / unrecognised -> ``Input.Text`` (fallback)
  Field ``required`` and ``placeholder`` keys are forwarded if present.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from parrot.human.channels.base import ESCALATE_OPTION_KEY, escalate_option
from parrot.human.models import ChoiceOption, HumanInteraction, InteractionType
from parrot.outputs.cards import (
    ActionSubmit,
    CardSpec,
    FormFieldSpec,
    InputChoice,
    InputChoiceSet,
    InputText,
    RawElementsSection,
    TextBlock,
    render as render_card,
)
from parrot.outputs.cards.elements import ACElement
from parrot.outputs.cards.sections import CardSection
from parrot.outputs.cards.sections import FormSection as CardFormSection

# Adaptive Card schema version targeted.
_AC_VERSION = "1.5"
_AC_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"

# Map HITL schema field types to shared-builder field type strings.
_HITL_TYPE_MAP: Dict[str, str] = {
    "string": "text",
    "text": "text_area",
    "textarea": "text_area",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "choice": "select",
    "select": "select",
    "multi_choice": "multi_select",
    "multi_select": "multi_select",
    "date": "date",
    "time": "time",
}


class TeamsCardRenderer:
    """Pure renderer: :class:`~parrot.human.models.HumanInteraction` -> Adaptive Card dict.

    All methods are synchronous (no I/O).  The returned dict is JSON-
    serialisable and can be passed directly to ``CardFactory.adaptive_card``
    or used in an ``Attachment`` body.

    Args:
        render_reject_button: When ``True``, policy-bound interactions receive
            an "escalate" submit action.  Matches
            ``TeamsHumanChannel.render_reject_button``.
    """

    def __init__(self, render_reject_button: bool = True) -> None:
        self._render_reject_button = render_reject_button

    # -- Public API ---------------------------------------------------------

    def render(
        self,
        interaction: HumanInteraction,
        render_reject_button: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Render an Adaptive Card for the given interaction.

        Args:
            interaction: The pending human interaction.
            render_reject_button: Override the instance-level flag for this
                call only.  Defaults to the constructor value.

        Returns:
            An Adaptive Card dict ready for ``CardFactory.adaptive_card``.
        """
        should_escalate = (
            render_reject_button
            if render_reject_button is not None
            else self._render_reject_button
        )
        policy_bound = interaction.policy is not None

        sections, actions = self._render_by_type(interaction)

        if should_escalate and policy_bound:
            escalate = escalate_option()
            actions.append(
                ActionSubmit(
                    title=escalate.label,
                    style="destructive",
                    data={
                        "hitl": True,
                        "interaction_id": interaction.interaction_id,
                        "value": ESCALATE_OPTION_KEY,
                    },
                )
            )

        spec = CardSpec(sections=sections, actions=actions)
        return render_card(spec)

    def render_disabled(
        self,
        interaction_id: str,
        reason: str = "expired",
    ) -> Dict[str, Any]:
        """Render a disabled/expired card variant for cancel/update.

        Used by ``TeamsHumanChannel.cancel_interaction`` to replace the
        live card with a tombstone indicating the interaction is no longer
        active.

        Args:
            interaction_id: The ID of the expired interaction.
            reason: Short human-readable reason (e.g. ``"expired"``,
                ``"withdrawn"``, ``"timeout"``).

        Returns:
            An Adaptive Card dict in a greyed-out disabled style.
        """
        spec = CardSpec(
            sections=[
                RawElementsSection(elements=[
                    TextBlock(
                        text=(
                            "Esta solicitud ha expirado o fue retirada"
                            f" ({reason})."
                        ),
                        is_subtle=True,
                        color="Warning",
                    ),
                    TextBlock(
                        text=f"ID: {interaction_id}",
                        is_subtle=True,
                        size="Small",
                    ),
                ]),
            ],
        )
        card = render_card(spec)
        # Ensure actions key is present for backward compatibility.
        card["actions"] = []
        return card

    # -- Internal renderers per InteractionType -----------------------------

    def _render_by_type(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """Dispatch to the correct renderer by interaction type.

        Args:
            interaction: The interaction to render.

        Returns:
            A tuple ``(card_sections, action_list)``.
        """
        itype = interaction.interaction_type
        dispatch = {
            InteractionType.FREE_TEXT: self._render_free_text,
            InteractionType.APPROVAL: self._render_approval,
            InteractionType.SINGLE_CHOICE: self._render_single_choice,
            InteractionType.MULTI_CHOICE: self._render_multi_choice,
            InteractionType.FORM: self._render_form,
            InteractionType.POLL: self._render_poll,
        }
        renderer = dispatch.get(itype, self._render_free_text)
        return renderer(interaction)  # type: ignore[operator]

    def _header_block(self, question: str) -> TextBlock:
        """Build a header TextBlock for the card body.

        Args:
            question: The interaction question text.

        Returns:
            A TextBlock element.
        """
        return TextBlock(
            text=question,
            weight="Bolder",
            size="Medium",
        )

    def _submit_action(
        self,
        interaction_id: str,
        title: str = "Enviar",
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> ActionSubmit:
        """Build a generic ``Action.Submit`` with HITL correlation data.

        Args:
            interaction_id: The interaction's UUID.
            title: Button label.
            extra_data: Additional fields merged into ``data``.

        Returns:
            An ActionSubmit instance.
        """
        data: Dict[str, Any] = {
            "hitl": True,
            "interaction_id": interaction_id,
        }
        if extra_data:
            data.update(extra_data)
        return ActionSubmit(title=title, data=data)

    def _choice_entries(
        self, options: Optional[List[ChoiceOption]]
    ) -> List[InputChoice]:
        """Convert ChoiceOption list to InputChoice instances.

        Args:
            options: List of choice options from the interaction.

        Returns:
            List of InputChoice instances.
        """
        if not options:
            return []
        return [InputChoice(title=opt.label, value=opt.key) for opt in options]

    def _render_free_text(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """FREE_TEXT -> multiline Input.Text + Submit.

        Args:
            interaction: The pending interaction.

        Returns:
            ``(card_sections, actions)``.
        """
        sections: List[CardSection] = [
            RawElementsSection(elements=[
                self._header_block(interaction.question),
                InputText(
                    id="response_text",
                    placeholder="Escribe tu respuesta…",
                    is_multiline=True,
                ),
            ]),
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Enviar",
                extra_data={"field": "response_text"},
            )
        ]
        return sections, actions

    def _render_approval(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """APPROVAL -> two Action.Submit buttons (Approve / Reject).

        Args:
            interaction: The pending interaction.

        Returns:
            ``(card_sections, actions)``.
        """
        sections: List[CardSection] = [
            RawElementsSection(elements=[
                self._header_block(interaction.question),
            ]),
        ]
        actions: List[ActionSubmit] = [
            ActionSubmit(
                title="Aprobar",
                style="positive",
                data={
                    "hitl": True,
                    "interaction_id": interaction.interaction_id,
                    "value": "approve",
                },
            ),
            ActionSubmit(
                title="Rechazar",
                style="destructive",
                data={
                    "hitl": True,
                    "interaction_id": interaction.interaction_id,
                    "value": "reject",
                },
            ),
        ]
        return sections, actions

    def _render_single_choice(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """SINGLE_CHOICE -> compact Input.ChoiceSet + Submit.

        Args:
            interaction: The pending interaction.

        Returns:
            ``(card_sections, actions)``.
        """
        sections: List[CardSection] = [
            RawElementsSection(elements=[
                self._header_block(interaction.question),
                InputChoiceSet(
                    id="selected_option",
                    style="compact",
                    is_multi_select=False,
                    choices=self._choice_entries(interaction.options),
                ),
            ]),
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Confirmar",
                extra_data={"field": "selected_option"},
            )
        ]
        return sections, actions

    def _render_multi_choice(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """MULTI_CHOICE -> Input.ChoiceSet (isMultiSelect=true) + Submit.

        Args:
            interaction: The pending interaction.

        Returns:
            ``(card_sections, actions)``.
        """
        sections: List[CardSection] = [
            RawElementsSection(elements=[
                self._header_block(interaction.question),
                InputChoiceSet(
                    id="selected_options",
                    style="expanded",
                    is_multi_select=True,
                    choices=self._choice_entries(interaction.options),
                ),
            ]),
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Confirmar seleccion",
                extra_data={"field": "selected_options"},
            )
        ]
        return sections, actions

    def _render_form(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """FORM -> form_schema -> FormSection with FormFieldSpec entries + Submit.

        OQ-5 resolution: maps each schema field's ``type`` to the
        appropriate shared-builder ``FormFieldSpec``.  See module
        docstring for the full mapping table.

        Args:
            interaction: The pending interaction (must have ``form_schema``).

        Returns:
            ``(card_sections, actions)``.
        """
        sections: List[CardSection] = [
            RawElementsSection(elements=[
                self._header_block(interaction.question),
            ]),
        ]

        schema = interaction.form_schema or {}
        properties = schema.get("properties", schema)  # support nested or flat

        field_specs: List[FormFieldSpec] = []
        for field_name, field_def in properties.items():
            if not isinstance(field_def, dict):
                continue
            field_specs.append(self._form_field_to_spec(field_name, field_def))

        if field_specs:
            sections.append(CardFormSection(fields=field_specs))

        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Enviar formulario",
            )
        ]
        return sections, actions

    def _form_field_to_spec(
        self, field_id: str, field_def: Dict[str, Any]
    ) -> FormFieldSpec:
        """Convert a single form-schema field to a FormFieldSpec.

        Args:
            field_id: JSON key for the field (used as the Input ``id``).
            field_def: Field definition dict with at least ``type``.

        Returns:
            A FormFieldSpec for the shared card builder.
        """
        field_type = field_def.get("type", "string").lower()
        label = field_def.get("label", field_def.get("title", field_id))
        placeholder = field_def.get("placeholder", "")
        is_required = field_def.get("required", False)

        mapped_type = _HITL_TYPE_MAP.get(field_type, "text")

        # Build options for choice types
        options: List[InputChoice] | None = None
        if mapped_type in ("select", "multi_select"):
            raw_choices = field_def.get("choices", field_def.get("enum", []))
            options = [
                InputChoice(
                    title=(
                        c
                        if isinstance(c, str)
                        else c.get("label", c.get("value", str(c)))
                    ),
                    value=(
                        c if isinstance(c, str) else c.get("value", str(c))
                    ),
                )
                for c in raw_choices
            ]

        return FormFieldSpec(
            field_id=field_id,
            field_type=mapped_type,
            label=label + (" *" if is_required else ""),
            placeholder=placeholder,
            required=is_required,
            options=options,
            is_multiline=mapped_type == "text_area",
        )

    def _render_poll(
        self, interaction: HumanInteraction
    ) -> tuple[List[CardSection], List[ActionSubmit]]:
        """POLL -> compact Input.ChoiceSet + Submit (mirrors SINGLE_CHOICE visually).

        Args:
            interaction: The pending interaction.

        Returns:
            ``(card_sections, actions)``.
        """
        sections: List[CardSection] = [
            RawElementsSection(elements=[
                self._header_block(interaction.question),
                InputChoiceSet(
                    id="poll_choice",
                    style="expanded",
                    is_multi_select=False,
                    choices=self._choice_entries(interaction.options),
                ),
            ]),
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Votar",
                extra_data={"field": "poll_choice"},
            )
        ]
        return sections, actions
