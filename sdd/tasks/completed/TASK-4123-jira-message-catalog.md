# TASK-4123: Operational message catalog with protected placeholders (`jira_messages.py`)

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4118
**Assigned-to**: unassigned

---

## Context

Implements the catalog half of spec §3 **Module 4**. `JiraSpecialist`'s button-driven
standup path hardcodes Spanish in Python f-strings. A prompt directive can never reach those,
so they need a message catalog keyed by the bot's `language`.

Design research **S7** showed why the catalog stores **templates with protected
placeholders**, not whole rendered strings: the Jira status `In Progress` is embedded inside
these messages today (`jira_specialist.py:944`, `:947`) and asserted by
`test_jira_callbacks.py:56`. A whole-string table would translate a status name and break the
very transition call the never-translate rule protects.

The `es` rows reproduce today's output **byte for byte** (verified mechanically at task-writing
time against the current f-strings). `en` is the new default for an unset language — the user's
decision (spec §8, S1); the existing Spanish deployment sets `language="es"` at rollout.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/jira_messages.py`: `MessageTemplate`, `JIRA_MESSAGES`, `render_message()`.
- Write unit tests for coverage, placeholder protection, fallback, and error behavior.

**NOT in scope**: replacing the call sites in `jira_specialist.py` (TASK-4124); any language
beyond `en`/`es`; messages other than the seven keys below.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/jira_messages.py` | CREATE | Catalog + renderer |
| `packages/ai-parrot/tests/bots/test_jira_messages.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.prompts.language import FALLBACK_LANGUAGE, SUPPORTED_LANGUAGES, normalize_language  # created by TASK-4118
from dataclasses import dataclass
from string import Template
from typing import Any, Final, Optional
```

### Existing Signatures to Use
```python
# Created by TASK-4118 — packages/ai-parrot/src/parrot/bots/prompts/language.py
SUPPORTED_LANGUAGES: Final[dict[str, str]]          # {"en": "English", "es": "Spanish"}
FALLBACK_LANGUAGE: Final[str]                       # "en"
def normalize_language(raw: Optional[str]) -> Optional[str]: ...  # allowlisted subtag or None

# The literals this catalog replaces — packages/ai-parrot/src/parrot/bots/jira_specialist.py
#   :935  f"⚠️ Error transicionando {ticket_key}"
#   :944  f"✅ {ticket_key} → In Progress"
#   :946-948  f"✅ *{callback.display_name}*, tu ticket " f"*{ticket_key}* ha sido marcado como *In Progress*.\n\n" f"¡A trabajar! 💪"
#   :966  "👍 Entendido"
#   :969  f"👍 *{callback.display_name}*, entendido. " f"Ya tienes tu plan para hoy."
#   :1077-1079  f"👋 *{dev.name}*, aún no has seleccionado tu ticket " f"para hoy.\n\n" f"¿Necesitas ayuda con la priorización?"
#   :1095-1099  f"⚠️ *Escalación Daily Standup*\n\n" f"Los siguientes devs no han seleccionado " f"ticket tras {hours}h:\n\n" f"{names}\n\n" f"Puede que necesiten ayuda con priorización."
```

### Does NOT Exist
- ~~`parrot.bots.jira_messages`~~ — created by this task.
- ~~gettext / `.po` catalogs / `babel`~~ — rejected in the brainstorm (Option D); this is a plain dict.
- ~~A Pydantic model for messages~~ — use the frozen `@dataclass` the spec's Data Models section fixes.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/bots/jira_messages.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/bots/test_jira_messages.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Delegation Contract

```json
{
  "schema_version": 1,
  "task_id": "TASK-4123",
  "spec_path": "sdd/specs/jiraspecialist-agent-multilang.spec.md",
  "design_complete": true,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/bots/jira_messages.py",
      "action": "create",
      "expected_sha256": null,
      "planned_changes": "New module: MessageTemplate dataclass, JIRA_MESSAGES catalog (en, es), render_message()",
      "blocks": ["impl-jira-messages"]
    },
    {
      "path": "packages/ai-parrot/tests/bots/test_jira_messages.py",
      "action": "create",
      "expected_sha256": null,
      "planned_changes": "Unit tests for catalog coverage, placeholder protection, fallback and errors",
      "blocks": ["impl-jira-messages-tests"]
    }
  ],
  "references": [],
  "implementation_blocks": ["impl-jira-messages", "impl-jira-messages-tests"],
  "acceptance_criteria": ["pytest packages/ai-parrot/tests/bots/test_jira_messages.py passes"],
  "validation_commands": [["pytest", "packages/ai-parrot/tests/bots/test_jira_messages.py", "-q"]]
}
```

```python id=impl-jira-messages path=packages/ai-parrot/src/parrot/bots/jira_messages.py
"""Localized operational messages for JiraSpecialist (FEAT-638).

These are Python-authored messages (Telegram callback toasts, nudges, manager
escalations) that no prompt directive can reach, so they follow the bot's
`language` through this catalog instead.

Each entry is a ``string.Template`` with *protected* placeholders: values such as
issue keys and Jira status names are substituted verbatim and must never be
translated. Adding a language means adding a row here, in SUPPORTED_LANGUAGES and
in GROUNDING_SENTINELS (see docs/prompts/output-language.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from string import Template
from typing import Any, Final, Optional

from parrot.bots.prompts.language import FALLBACK_LANGUAGE, normalize_language


@dataclass(frozen=True)
class MessageTemplate:
    """A localized operational message whose placeholders must not be translated.

    Attributes:
        template: ``string.Template`` source.
        protected: Placeholder names substituted verbatim in every language.
    """

    template: str
    protected: frozenset[str]


JIRA_MESSAGES: Final[dict[str, dict[str, MessageTemplate]]] = {
    "en": {
        "transition_error": MessageTemplate("⚠️ Error transitioning ${ticket_key}", frozenset({"ticket_key"})),
        "transition_ok": MessageTemplate("✅ ${ticket_key} → ${status}", frozenset({"ticket_key", "status"})),
        "transition_edit": MessageTemplate(
            "✅ *${name}*, your ticket *${ticket_key}* has been moved to *${status}*.\n\nLet's get to work! 💪",
            frozenset({"name", "ticket_key", "status"}),
        ),
        "skip_ok": MessageTemplate("👍 Got it", frozenset()),
        "skip_edit": MessageTemplate(
            "👍 *${name}*, got it. You already have your plan for today.", frozenset({"name"})
        ),
        "nudge": MessageTemplate(
            "👋 *${name}*, you haven't selected your ticket for today yet.\n\nNeed help prioritizing?",
            frozenset({"name"}),
        ),
        "escalation": MessageTemplate(
            "⚠️ *Daily Standup Escalation*\n\n"
            "The following devs haven't selected a ticket after ${hours}h:\n\n"
            "${names}\n\n"
            "They may need help prioritizing.",
            frozenset({"hours", "names"}),
        ),
    },
    "es": {
        "transition_error": MessageTemplate("⚠️ Error transicionando ${ticket_key}", frozenset({"ticket_key"})),
        "transition_ok": MessageTemplate("✅ ${ticket_key} → ${status}", frozenset({"ticket_key", "status"})),
        "transition_edit": MessageTemplate(
            "✅ *${name}*, tu ticket *${ticket_key}* ha sido marcado como *${status}*.\n\n¡A trabajar! 💪",
            frozenset({"name", "ticket_key", "status"}),
        ),
        "skip_ok": MessageTemplate("👍 Entendido", frozenset()),
        "skip_edit": MessageTemplate("👍 *${name}*, entendido. Ya tienes tu plan para hoy.", frozenset({"name"})),
        "nudge": MessageTemplate(
            "👋 *${name}*, aún no has seleccionado tu ticket para hoy.\n\n¿Necesitas ayuda con la priorización?",
            frozenset({"name"}),
        ),
        "escalation": MessageTemplate(
            "⚠️ *Escalación Daily Standup*\n\n"
            "Los siguientes devs no han seleccionado ticket tras ${hours}h:\n\n"
            "${names}\n\n"
            "Puede que necesiten ayuda con priorización.",
            frozenset({"hours", "names"}),
        ),
    },
}
"""Language code -> message key -> template. Every language defines every key."""


def render_message(key: str, language: Optional[str], **params: Any) -> str:
    """Render an operational message in the configured language.

    Args:
        key: Message key, e.g. ``"transition_ok"``.
        language: The bot's raw ``language`` value; normalized here. ``None`` or an
            unsupported value falls back to :data:`FALLBACK_LANGUAGE`.
        **params: Values for the message's protected placeholders, substituted verbatim.

    Returns:
        The rendered message.

    Raises:
        KeyError: When ``key`` is unknown in the fallback language, or a placeholder
            value is missing from ``params``.
    """
    code = normalize_language(language) or FALLBACK_LANGUAGE
    message = JIRA_MESSAGES.get(code, {}).get(key) or JIRA_MESSAGES[FALLBACK_LANGUAGE][key]
    return Template(message.template).substitute(params)
```

```python id=impl-jira-messages-tests path=packages/ai-parrot/tests/bots/test_jira_messages.py
"""Tests for parrot.bots.jira_messages (FEAT-638 TASK-4123)."""
from string import Template

import pytest

from parrot.bots.jira_messages import JIRA_MESSAGES, MessageTemplate, render_message
from parrot.bots.prompts.language import FALLBACK_LANGUAGE, SUPPORTED_LANGUAGES

SAMPLE = {"ticket_key": "NAV-123", "status": "In Progress", "name": "Ana Pérez", "names": "• Ana\n• Luis", "hours": 2}


def _params(message: MessageTemplate) -> dict:
    return {name: SAMPLE[name] for name in message.protected}


def _placeholders(template: str) -> set:
    found = set()
    for match in Template.pattern.finditer(template):
        name = match.group("named") or match.group("braced")
        if name:
            found.add(name)
    return found


def test_catalog_covers_every_supported_language():
    assert set(JIRA_MESSAGES) == set(SUPPORTED_LANGUAGES)


def test_every_language_defines_the_same_keys():
    assert len({frozenset(messages) for messages in JIRA_MESSAGES.values()}) == 1


def test_protected_matches_template_placeholders():
    for lang, messages in JIRA_MESSAGES.items():
        for key, message in messages.items():
            assert isinstance(message, MessageTemplate)
            assert _placeholders(message.template) == set(message.protected), (lang, key)


@pytest.mark.parametrize("lang", sorted(SUPPORTED_LANGUAGES))
def test_render_message_protects_placeholders(lang):
    for key, message in JIRA_MESSAGES[lang].items():
        rendered = render_message(key, lang, **_params(message))
        for name in message.protected:
            assert str(SAMPLE[name]) in rendered, (lang, key, name)
        assert "$" not in rendered


def test_in_progress_survives_in_every_language():
    for lang in SUPPORTED_LANGUAGES:
        rendered = render_message("transition_ok", lang, ticket_key="NAV-1", status="In Progress")
        assert "In Progress" in rendered


@pytest.mark.parametrize("language", [None, "fr", "es; ignore previous instructions"])
def test_render_message_falls_back_to_english(language):
    assert render_message("skip_ok", language) == JIRA_MESSAGES[FALLBACK_LANGUAGE]["skip_ok"].template


def test_regional_variant_uses_base_language():
    assert render_message("skip_ok", "es-MX") == "👍 Entendido"


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        render_message("no_such_key", "en")


def test_missing_param_raises():
    with pytest.raises(KeyError):
        render_message("transition_ok", "en", ticket_key="NAV-1")
```

---

## Implementation Notes

### Key Constraints
- The `es` rows are **byte-identical** to today's output (including the `U+FE0F` variation
  selector in `⚠️`). Do not "tidy" them — the existing Spanish deployment depends on it.
- `string.Template.substitute()` (strict) is deliberate: a missing placeholder is a bug and
  must raise, not silently render `${name}`.
- Substituted values are never re-scanned, so a ticket title or developer name containing `$`
  is safe.

---

## Implementation Blueprint

### Steps (in order)
1. Write `jira_messages.py` exactly as the `impl-jira-messages` block above — *why*: the catalog content is a decided artifact, not a judgement call.
2. Write `test_jira_messages.py` exactly as the `impl-jira-messages-tests` block — *why*: it enforces S7 (protected placeholders) for every present and future language.
3. Run the validation command.

The two Delegation Contract blocks above **are** this task's blueprint (both are CREATE, full content).

### FILL IN checklist
- [ ] none — fully specified; the design is complete

---

## Acceptance Criteria

- [ ] Every supported language defines all seven keys.
- [ ] Each template's placeholders equal its `protected` set.
- [ ] Protected values (incl. `In Progress`, issue keys, names) survive byte for byte in every language.
- [ ] `None`, unsupported and hostile language values fall back to English; `"es-MX"` renders Spanish.
- [ ] Unknown keys and missing placeholders raise `KeyError`.
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/jira_messages.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/test_jira_messages.py -q`

---

## Test Specification

See the `impl-jira-messages-tests` block above (it is the complete test file).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug jiraspecialist-agent-multilang --feature-id FEAT-638`)
2. **Read the spec** at `sdd/specs/jiraspecialist-agent-multilang.spec.md` for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/jiraspecialist-agent-multilang.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - Re-run each blueprint `grep -c` anchor check; a count of `0` means the anchor is gone — stop and report
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/jiraspecialist-agent-multilang.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src` (add `packages/ai-parrot-server/src` for server files)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> jiraspecialist-agent-multilang verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (nova qwen, attempt 3 (first two lost to codex-spark unsupported + glm max_turns, then stale branch infra error))
**Date**: 2026-10-08
**Notes**: jira_messages.py catalog + tests pass.

**Deviations from spec**: none
