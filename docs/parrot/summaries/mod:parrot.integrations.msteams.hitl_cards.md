---
type: Wiki Summary
title: parrot.integrations.msteams.hitl_cards
id: mod:parrot.integrations.msteams.hitl_cards
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Adaptive Card renderer for the Teams HITL channel.
relates_to:
- concept: class:parrot.integrations.msteams.hitl_cards.TeamsCardRenderer
  rel: defines
- concept: mod:parrot.human.channels.base
  rel: references
- concept: mod:parrot.human.models
  rel: references
---

# `parrot.integrations.msteams.hitl_cards`

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

## Classes

- **`TeamsCardRenderer`** — Pure renderer: :class:`~parrot.human.models.HumanInteraction` → Adaptive Card dict.
