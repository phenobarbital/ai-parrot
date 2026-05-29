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

OQ-5 resolution — ``form_schema`` → ``Input.*`` mapping:
  - ``"string"`` → ``Input.Text`` (single-line unless ``multiline: true``)
  - ``"text"`` or ``"textarea"`` → ``Input.Text`` (multiline)
  - ``"integer"`` or ``"number"`` → ``Input.Number``
  - ``"boolean"`` → ``Input.Toggle``
  - ``"choice"`` or ``"select"`` → ``Input.ChoiceSet`` (compact, single)
  - ``"multi_choice"`` or ``"multi_select"`` → ``Input.ChoiceSet`` (multi)
  - ``"date"`` → ``Input.Date``
  - ``"time"`` → ``Input.Time``
  - unknown / unrecognised → ``Input.Text`` (fallback)
  Field ``required`` and ``placeholder`` keys are forwarded if present.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from parrot.human.channels.base import ESCALATE_OPTION_KEY, escalate_option
from parrot.human.models import ChoiceOption, HumanInteraction, InteractionType

# Adaptive Card schema version targeted.
_AC_VERSION = "1.5"
_AC_SCHEMA = "http://adaptivecards.io/schemas/adaptive-card.json"


class TeamsCardRenderer:
    """Pure renderer: :class:`~parrot.human.models.HumanInteraction` → Adaptive Card dict.

    All methods are synchronous (no I/O).  The returned dict is JSON-
    serialisable and can be passed directly to ``CardFactory.adaptive_card``
    or used in an ``Attachment`` body.

    Args:
        render_reject_button: When ``True``, policy-bound interactions receive
            an "↑ Escalar" submit action.  Matches
            ``TeamsHumanChannel.render_reject_button``.
    """

    def __init__(self, render_reject_button: bool = True) -> None:
        self._render_reject_button = render_reject_button

    # ── Public API ─────────────────────────────────────────────────────────

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

        body, actions = self._render_by_type(interaction)

        if should_escalate and policy_bound:
            escalate = escalate_option()
            actions.append(
                {
                    "type": "Action.Submit",
                    "title": escalate.label,
                    "style": "destructive",
                    "data": {
                        "hitl": True,
                        "interaction_id": interaction.interaction_id,
                        "value": ESCALATE_OPTION_KEY,
                    },
                }
            )

        card: Dict[str, Any] = {
            "type": "AdaptiveCard",
            "$schema": _AC_SCHEMA,
            "version": _AC_VERSION,
            "body": body,
            "actions": actions,
        }
        return card

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
        return {
            "type": "AdaptiveCard",
            "$schema": _AC_SCHEMA,
            "version": _AC_VERSION,
            "body": [
                {
                    "type": "TextBlock",
                    "text": f"Esta solicitud ha expirado o fue retirada ({reason}).",
                    "wrap": True,
                    "isSubtle": True,
                    "color": "Warning",
                },
                {
                    "type": "TextBlock",
                    "text": f"ID: {interaction_id}",
                    "wrap": True,
                    "isSubtle": True,
                    "size": "Small",
                },
            ],
            "actions": [],
        }

    # ── Internal renderers per InteractionType ─────────────────────────────

    def _render_by_type(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Dispatch to the correct renderer by interaction type.

        Args:
            interaction: The interaction to render.

        Returns:
            A tuple ``(body_elements, action_list)``.
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

    def _header_block(self, question: str) -> Dict[str, Any]:
        """Build a header TextBlock for the card body.

        Args:
            question: The interaction question text.

        Returns:
            An Adaptive Card TextBlock element.
        """
        return {
            "type": "TextBlock",
            "text": question,
            "wrap": True,
            "weight": "Bolder",
            "size": "Medium",
        }

    def _submit_action(
        self,
        interaction_id: str,
        title: str = "Enviar",
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a generic ``Action.Submit`` with HITL correlation data.

        Args:
            interaction_id: The interaction's UUID.
            title: Button label.
            extra_data: Additional fields merged into ``data``.

        Returns:
            An Adaptive Card ``Action.Submit`` element.
        """
        data: Dict[str, Any] = {
            "hitl": True,
            "interaction_id": interaction_id,
        }
        if extra_data:
            data.update(extra_data)
        return {
            "type": "Action.Submit",
            "title": title,
            "data": data,
        }

    def _render_free_text(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """FREE_TEXT → multiline Input.Text + Submit.

        Args:
            interaction: The pending interaction.

        Returns:
            ``(body_elements, actions)``.
        """
        body = [
            self._header_block(interaction.question),
            {
                "type": "Input.Text",
                "id": "response_text",
                "placeholder": "Escribe tu respuesta…",
                "isMultiline": True,
            },
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Enviar",
                extra_data={"field": "response_text"},
            )
        ]
        return body, actions

    def _render_approval(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """APPROVAL → two Action.Submit buttons (Approve / Reject).

        Args:
            interaction: The pending interaction.

        Returns:
            ``(body_elements, actions)``.
        """
        body = [self._header_block(interaction.question)]
        actions = [
            {
                "type": "Action.Submit",
                "title": "Aprobar",
                "style": "positive",
                "data": {
                    "hitl": True,
                    "interaction_id": interaction.interaction_id,
                    "value": "approve",
                },
            },
            {
                "type": "Action.Submit",
                "title": "Rechazar",
                "style": "destructive",
                "data": {
                    "hitl": True,
                    "interaction_id": interaction.interaction_id,
                    "value": "reject",
                },
            },
        ]
        return body, actions

    def _choice_entries(
        self, options: Optional[List[ChoiceOption]]
    ) -> List[Dict[str, str]]:
        """Convert ChoiceOption list to Adaptive Card choice format.

        Args:
            options: List of choice options from the interaction.

        Returns:
            List of ``{"title": ..., "value": ...}`` dicts.
        """
        if not options:
            return []
        return [{"title": opt.label, "value": opt.key} for opt in options]

    def _render_single_choice(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """SINGLE_CHOICE → compact Input.ChoiceSet + Submit.

        Args:
            interaction: The pending interaction.

        Returns:
            ``(body_elements, actions)``.
        """
        body = [
            self._header_block(interaction.question),
            {
                "type": "Input.ChoiceSet",
                "id": "selected_option",
                "style": "compact",
                "isMultiSelect": False,
                "choices": self._choice_entries(interaction.options),
            },
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Confirmar",
                extra_data={"field": "selected_option"},
            )
        ]
        return body, actions

    def _render_multi_choice(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """MULTI_CHOICE → Input.ChoiceSet (isMultiSelect=true) + Submit.

        Args:
            interaction: The pending interaction.

        Returns:
            ``(body_elements, actions)``.
        """
        body = [
            self._header_block(interaction.question),
            {
                "type": "Input.ChoiceSet",
                "id": "selected_options",
                "style": "expanded",
                "isMultiSelect": True,
                "choices": self._choice_entries(interaction.options),
            },
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Confirmar selección",
                extra_data={"field": "selected_options"},
            )
        ]
        return body, actions

    def _render_form(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """FORM → form_schema → Input.* fields + Submit.

        OQ-5 resolution: maps each schema field's ``type`` to the
        appropriate Adaptive Card ``Input.*`` element.  See module
        docstring for the full mapping table.

        Args:
            interaction: The pending interaction (must have ``form_schema``).

        Returns:
            ``(body_elements, actions)``.
        """
        body: List[Dict[str, Any]] = [self._header_block(interaction.question)]

        schema = interaction.form_schema or {}
        properties = schema.get("properties", schema)  # support nested or flat

        for field_name, field_def in properties.items():
            if not isinstance(field_def, dict):
                continue
            input_el = self._form_field_to_input(field_name, field_def)
            body.append(input_el)

        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Enviar formulario",
            )
        ]
        return body, actions

    def _form_field_to_input(
        self, field_id: str, field_def: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Convert a single form-schema field to an Adaptive Card Input element.

        Args:
            field_id: JSON key for the field (used as the Input ``id``).
            field_def: Field definition dict with at least ``type``.

        Returns:
            An Adaptive Card ``Input.*`` element dict.
        """
        field_type = field_def.get("type", "string").lower()
        label = field_def.get("label", field_def.get("title", field_id))
        placeholder = field_def.get("placeholder", "")
        is_required = field_def.get("required", False)

        # Label block
        label_block: Dict[str, Any] = {
            "type": "TextBlock",
            "text": label + (" *" if is_required else ""),
            "wrap": True,
            "size": "Small",
            "weight": "Bolder",
        }

        # Input element based on type mapping (OQ-5)
        if field_type in ("text", "textarea"):
            input_el: Dict[str, Any] = {
                "type": "Input.Text",
                "id": field_id,
                "isMultiline": True,
                "placeholder": placeholder,
                "isRequired": is_required,
            }
        elif field_type in ("integer", "number"):
            input_el = {
                "type": "Input.Number",
                "id": field_id,
                "placeholder": placeholder or "0",
                "isRequired": is_required,
            }
        elif field_type == "boolean":
            input_el = {
                "type": "Input.Toggle",
                "id": field_id,
                "title": label,
                "valueOn": "true",
                "valueOff": "false",
                "isRequired": is_required,
            }
        elif field_type in ("choice", "select"):
            choices = [
                {"title": c if isinstance(c, str) else c.get("label", c.get("value", str(c))),
                 "value": c if isinstance(c, str) else c.get("value", str(c))}
                for c in field_def.get("choices", field_def.get("enum", []))
            ]
            input_el = {
                "type": "Input.ChoiceSet",
                "id": field_id,
                "style": "compact",
                "isMultiSelect": False,
                "choices": choices,
                "isRequired": is_required,
            }
        elif field_type in ("multi_choice", "multi_select"):
            choices = [
                {"title": c if isinstance(c, str) else c.get("label", c.get("value", str(c))),
                 "value": c if isinstance(c, str) else c.get("value", str(c))}
                for c in field_def.get("choices", field_def.get("enum", []))
            ]
            input_el = {
                "type": "Input.ChoiceSet",
                "id": field_id,
                "style": "expanded",
                "isMultiSelect": True,
                "choices": choices,
                "isRequired": is_required,
            }
        elif field_type == "date":
            input_el = {
                "type": "Input.Date",
                "id": field_id,
                "placeholder": placeholder or "YYYY-MM-DD",
                "isRequired": is_required,
            }
        elif field_type == "time":
            input_el = {
                "type": "Input.Time",
                "id": field_id,
                "placeholder": placeholder or "HH:MM",
                "isRequired": is_required,
            }
        else:
            # Default: single-line Input.Text (covers "string" and unknowns)
            input_el = {
                "type": "Input.Text",
                "id": field_id,
                "isMultiline": False,
                "placeholder": placeholder,
                "isRequired": is_required,
            }

        return {"type": "Container", "items": [label_block, input_el]}

    def _render_poll(
        self, interaction: HumanInteraction
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """POLL → compact Input.ChoiceSet + Submit (mirrors SINGLE_CHOICE visually).

        Args:
            interaction: The pending interaction.

        Returns:
            ``(body_elements, actions)``.
        """
        body = [
            self._header_block(interaction.question),
            {
                "type": "Input.ChoiceSet",
                "id": "poll_choice",
                "style": "expanded",
                "isMultiSelect": False,
                "choices": self._choice_entries(interaction.options),
            },
        ]
        actions = [
            self._submit_action(
                interaction.interaction_id,
                title="Votar",
                extra_data={"field": "poll_choice"},
            )
        ]
        return body, actions
