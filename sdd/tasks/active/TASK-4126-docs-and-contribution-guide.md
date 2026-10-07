# TASK-4126: Output-language guide, "Adding a language" contribution section, and doc updates

**Feature**: FEAT-638 — Bot-Level Output Language Directive
**Spec**: `sdd/specs/jiraspecialist-agent-multilang.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4122, TASK-4123
**Assigned-to**: unassigned

---

## Context

Closes spec §5's documentation criteria and the user's resolution of the last open question
(spec §8): *adding a language needs a contribution-guide section*. The repo has no
`CONTRIBUTING` file, so the guide lives in a new `docs/prompts/output-language.md` next to
the existing prompt docs.

Two existing docs become wrong when this feature lands:
- `docs/jira-specialist-prompt-layers.md` explicitly forbids localising the sentinels (`:151`)
  and calls them verbatim English (`:59-72`) — FEAT-638 reverses both.
- `docs/prompts/layers-reference.md` documents `JIRA_GROUNDING_LAYER` as variable-free and
  does not know `OUTPUT_LANGUAGE_LAYER` exists.

A doc-sync test keeps the guide honest and, more importantly, asserts that **all three
catalogs** (`SUPPORTED_LANGUAGES`, `GROUNDING_SENTINELS`, `JIRA_MESSAGES`) always cover
exactly the same languages — the check that makes "adding a language is a catalog edit" safe.

---

## Scope

- Create `docs/prompts/output-language.md` (behavior + "Adding a language").
- Update the two existing docs.
- Create the doc-sync test.

**NOT in scope**: any source change; FEAT-637's template implementation (only the convention
is documented); release notes outside the repo.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/prompts/output-language.md` | CREATE | Feature guide + "Adding a language" section |
| `docs/jira-specialist-prompt-layers.md` | MODIFY | Sentinel section + anti-pattern reversed |
| `docs/prompts/layers-reference.md` | MODIFY | New layer, variables, registry row, assembled order |
| `packages/ai-parrot/tests/bots/prompts/test_output_language_docs.py` | CREATE | Doc + catalog sync test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.jira_messages import JIRA_MESSAGES                    # TASK-4123
from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS      # TASK-4120
from parrot.bots.prompts.language import SUPPORTED_LANGUAGES           # TASK-4118
```

### Existing Signatures to Use
```text
docs/jira-specialist-prompt-layers.md
  :59   ## Sentinel phrases                          (section runs to the `---` before "## Extending or overriding")
  :151  - **Do not localise the sentinel phrases** — `No results found for` and   (bullet spans :151-153)
docs/prompts/layers-reference.md
  :16   These eight layers form the **default stack** (`PromptBuilder.default()`).
  :429  ### `JIRA_GROUNDING_LAYER`
  :440  | **Variables** | None |        ← NOT unique (4 occurrences); anchor via :442 below
  :442  Covers tool-output authority, empty/not-found results, error handling,
  :513  | `jira_workflow` | `JIRA_WORKFLOW_LAYER` | 16 | CONFIGURE | Jira standup/workflow |
  :537   60  OUTPUT_LAYER            ← output format
Test path: packages/ai-parrot/tests/bots/prompts/<file>.py → repo root is Path(__file__).resolve().parents[5]
```

### Does NOT Exist
- ~~`CONTRIBUTING.md`~~ / ~~`docs/CONTRIBUTING.md`~~ — no contribution file exists; do not create one.
- ~~Template files for FEAT-637~~ — only the naming convention is documented here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "docs/prompts/output-language.md", "action": "CREATE"},
    {"path": "docs/jira-specialist-prompt-layers.md", "action": "MODIFY"},
    {"path": "docs/prompts/layers-reference.md", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/bots/prompts/test_output_language_docs.py", "action": "CREATE"}
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- The guide must state the verification bound plainly: tests prove the directive is *present*
  in the prompt, never that the model *obeyed* it (spec Non-Goals).
- Every code/symbol name in the docs must exist after TASK-4118..4124; do not invent APIs.

---

## Implementation Blueprint

### Steps (in order)
1. Create the guide — *why*: the user's §8 resolution.
2. Update `jira-specialist-prompt-layers.md` — *why*: it currently forbids what FEAT-638 does.
3. Update `layers-reference.md` — *why*: the reference must list the new layer and the grounding variables.
4. Create the doc-sync test.

### `docs/prompts/output-language.md` (CREATE)
````markdown
# Output Language (FEAT-638)

Every bot has a `language` attribute (ISO 639-1). It controls the language of the
**artifacts the agent writes** — tickets, issue descriptions, comments, reports,
standup and escalation messages — while the agent keeps **replying to the user in
the language the user wrote in**.

```python
agent = JiraSpecialist(language="en")        # Spanish chat, English Jira tickets
```

It can also be a class attribute (`language = "es"`) or the `language` column of a
DB-backed bot (`navigator.ai_bots` / `navigator.users_bots`).

## Behavior

| `language` | Prompt | Python-authored messages | Grounding sentinels |
|---|---|---|---|
| unset (`None`) | unchanged — the directive layer is removed | English | English |
| `"en"` / `"es"` | `OUTPUT_LANGUAGE_LAYER` directive | that language | that language |
| `"es-MX"` | treated as `"es"` (base subtag) | Spanish | Spanish |
| unsupported (`"fr"`, garbage) | treated as unset, logged at WARNING | English | English |

The directive always keeps identifiers verbatim (issue keys, project keys, status and
transition names, labels, components, usernames, JQL, URLs, code blocks) and keeps
quoted existing content in its original language.

Supported today: `en` (English), `es` (Spanish).

**Builders**: `default()`, `agent()`, `rag()`, `voice()` and the `identity` preset
install the layer; `minimal()` deliberately does not — add it yourself with
`builder.add(get_domain_layer("output_language"))`.

**Verification bound**: the tests prove the directive is present in the rendered
prompt. They do not prove the model obeys it.

## Adding a language

A language is three catalog entries — no other code changes. Example for Portuguese (`pt`):

1. `parrot/bots/prompts/language.py` — add `"pt": "Portuguese"` to `SUPPORTED_LANGUAGES`.
2. `parrot/bots/prompts/domain_layers.py` — add a `"pt"` row to `GROUNDING_SENTINELS`
   with both `not_found` and `error`. These are assertion targets; keep them short and literal.
3. `parrot/bots/jira_messages.py` — add a `"pt"` block to `JIRA_MESSAGES` defining
   **every** key the other languages define, with the **same `protected` set** per key.
   Never translate a protected placeholder (`${ticket_key}`, `${status}`, `${name}`,
   `${names}`, `${hours}`): their values are identifiers or data, substituted verbatim.
4. Run the catalog tests — they fail until all three catalogs agree:
   `test_language.py`, `test_output_language_layer.py`, `test_jira_grounding_layer.py`,
   `test_jira_messages.py`, `test_output_language_docs.py`.
5. Add the language to the "Supported today" line above.

**Templated Jira writes (FEAT-637)**: Jinja templates are authored by files, not the
LLM, so this directive cannot reach them. Localize them by convention — template lookup
falls back from `<name>.<lang>.j2` to `<name>.j2`.
````
**Why this shape**: the "Adding a language" steps name the exact three symbols the doc-sync
test checks for, so the guide cannot silently drift from the code.

### `docs/jira-specialist-prompt-layers.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -cF '## Sentinel phrases' docs/jira-specialist-prompt-layers.md)
     REPLACE the whole section from `## Sentinel phrases` (:59) up to (not including) the `---`
     before `## Extending or overriding` with: -->
## Sentinel phrases

`JIRA_GROUNDING_LAYER` mandates two reply prefixes. Since FEAT-638 their wording follows
the bot's `language`: the template carries `$sentinel_not_found` / `$sentinel_error`,
which `AbstractBot._configure_prompt_builder()` fills from `GROUNDING_SENTINELS`
(English when `language` is unset). The anti-hallucination rules are identical in every language.

| Situation | `en` (default) | `es` |
|---|---|---|
| Tool returns `status="not_found"` or `status="empty"` | `No results found for <KEY\|JQL>.` | `No se encontraron resultados para <KEY\|JQL>.` |
| Tool returns `status="error"` or raises | `Jira lookup failed: <message>.` | `La consulta a Jira falló: <message>.` |

The phrases are **assertion targets**: `test_jira_grounding_layer.py` and
`test_jira_specialist_grounding.py` read them from `GROUNDING_SENTINELS`, so change them only
there. To add a language see [`prompts/output-language.md`](prompts/output-language.md).

<!-- occurrences: 1 (verified: grep -cF '- **Do not localise the sentinel phrases** — `No results found for` and' ...)
     REPLACE the whole bullet (:151-153) with: -->
- **Do not hardcode the sentinel phrases** — read them from `GROUNDING_SENTINELS`
  (`parrot/bots/prompts/domain_layers.py`). Localising them is supported since FEAT-638;
  a literal edited in a test or a layer instead of the table will drift out of sync.
```

### `docs/prompts/layers-reference.md` (MODIFY — 5 edits)
```markdown
<!-- (a) AFTER the paragraph starting at :16 (`These eight layers form the **default stack**…`, occurrences: 1), add: -->
Since FEAT-638, `default()` (and therefore `agent()`, `rag()`, the `identity` preset) and
`voice()` also install the domain layer `OUTPUT_LANGUAGE_LAYER`; it is removed at configure
time when the bot has no `language`. `minimal()` does not install it.

<!-- (b) BEFORE `### `JIRA_GROUNDING_LAYER`` (:429, occurrences: 1), insert: -->
### `OUTPUT_LANGUAGE_LAYER`

Bot-level output language (FEAT-638). Artifacts the agent writes follow the configured
language; replies follow the user; identifiers and quoted content stay verbatim.

| Field | Value |
|---|---|
| **Name** | `output_language` |
| **Priority** | `59` (OUTPUT − 1) |
| **Phase** | CONFIGURE |
| **Cacheable** | `True` |
| **Condition** | None — when `language` is unset the layer is **removed** at configure time |
| **Variables** | `$output_language` (display name from `SUPPORTED_LANGUAGES`) |

See [`output-language.md`](output-language.md).

---

<!-- (c) The `| **Variables** | None |` row of JIRA_GROUNDING_LAYER is NOT unique (4 occurrences).
     Anchor on `Covers tool-output authority, empty/not-found results, error handling,` (:442,
     occurrences: 1) and REPLACE the `| **Variables** | None |` row two lines ABOVE it with: -->
| **Variables** | `$sentinel_not_found`, `$sentinel_error` (from `GROUNDING_SENTINELS`, FEAT-638) |

<!-- (d) AFTER the registry row `| `jira_workflow` | … | Jira standup/workflow |` (:513, occurrences: 1), add: -->
| `output_language` | `OUTPUT_LANGUAGE_LAYER` | 59 | CONFIGURE | Bot-level output language (FEAT-638) |

<!-- (e) BEFORE ` 60  OUTPUT_LAYER            ← output format` (:537, occurrences: 1), add (keep column alignment): -->
 59  OUTPUT_LANGUAGE_LAYER   ← (when the bot sets `language`)
```

### `packages/ai-parrot/tests/bots/prompts/test_output_language_docs.py` (CREATE)
```python
"""Keeps the output-language docs and catalogs in sync (FEAT-638 TASK-4126)."""
from pathlib import Path

from parrot.bots.jira_messages import JIRA_MESSAGES
from parrot.bots.prompts.domain_layers import GROUNDING_SENTINELS
from parrot.bots.prompts.language import SUPPORTED_LANGUAGES

REPO = Path(__file__).resolve().parents[5]
GUIDE = REPO / "docs" / "prompts" / "output-language.md"
JIRA_LAYERS_DOC = REPO / "docs" / "jira-specialist-prompt-layers.md"
REFERENCE = REPO / "docs" / "prompts" / "layers-reference.md"


def test_every_catalog_covers_exactly_the_supported_languages():
    assert set(GROUNDING_SENTINELS) == set(SUPPORTED_LANGUAGES)
    assert set(JIRA_MESSAGES) == set(SUPPORTED_LANGUAGES)


def test_guide_lists_every_supported_language():
    text = GUIDE.read_text(encoding="utf-8")
    for code, name in SUPPORTED_LANGUAGES.items():
        assert f"`{code}`" in text and name in text, code


def test_guide_has_contribution_section_naming_all_catalogs():
    text = GUIDE.read_text(encoding="utf-8")
    assert "## Adding a language" in text
    for symbol in ("SUPPORTED_LANGUAGES", "GROUNDING_SENTINELS", "JIRA_MESSAGES"):
        assert symbol in text, symbol


def test_jira_layers_doc_no_longer_forbids_localising_sentinels():
    assert "Do not localise the sentinel phrases" not in JIRA_LAYERS_DOC.read_text(encoding="utf-8")


def test_layers_reference_documents_output_language():
    text = REFERENCE.read_text(encoding="utf-8")
    assert "OUTPUT_LANGUAGE_LAYER" in text and "`output_language`" in text
    assert "$sentinel_not_found" in text
```

### FILL IN checklist
- [ ] none — content is decided; if any doc anchor count is not 1 (except the documented non-unique `Variables` row), stop and report drift

---

## Acceptance Criteria

- [ ] `docs/prompts/output-language.md` exists with the behavior table and an `## Adding a language` section naming all three catalogs.
- [ ] `docs/jira-specialist-prompt-layers.md` no longer forbids localising the sentinels and shows both languages.
- [ ] `docs/prompts/layers-reference.md` documents `OUTPUT_LANGUAGE_LAYER`, the grounding variables, the registry row and priority 59 in the assembled order.
- [ ] All three catalogs cover exactly `SUPPORTED_LANGUAGES` (asserted).
- [ ] The guide states the verification bound (presence, not compliance).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/bots/prompts/test_output_language_docs.py -q`

---

## Test Specification

See the `test_output_language_docs.py` blueprint block above (complete file).

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

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
