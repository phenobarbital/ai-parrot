# TASK-2083: Bedrock model-ID translation for the 2026 model generation

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 1** of the spec. `parrot/models/bedrock_models.py` translates
public model IDs to Bedrock IDs, but it predates the 2026 model generation and is
wrong on three counts. Most importantly, `NovaClient` defaults
`region_prefix="us"` (`clients/nova/client.py:72`) because Nova 2 Lite requires a
geo prefix — but MiniMax M2.5, Kimi K2.5 and GLM-5 have **no** geo or global
inference profiles at all, so that default would produce the invalid
`us.minimax.minimax-m2.5`.

The resolution ([R6]) inverts the rule rather than changing the client: a
`REQUIRES_REGION_PREFIX` map becomes the allowlist. Only mapped models are
prefixed, so `region_prefix` can keep its default without ever leaking.

This is the foundation task — every other Nova task resolves model ids through it.

---

## Scope

- Add `au.` and `global.` to `_REGION_PREFIXES` (currently `("us.", "eu.", "apac.")`).
- Teach the pass-through detector the `minimax.`, `zai.` and `moonshotai.` vendor
  namespaces so those ids are returned verbatim without a warning.
- Add the verified `PUBLIC_TO_BEDROCK` entries listed under "Verified AWS Facts".
  Note Claude Opus 5 and Fable 5 carry **no** `-vN:0` suffix — the existing
  `anthropic.<id>-vN:0` convention does not hold for them.
- Introduce `REQUIRES_REGION_PREFIX: dict[str, str]` mapping model id → default
  prefix, and make `translate()` apply a prefix **only** to mapped models.
- When a caller passes an explicit `region_prefix` for an **unmapped** model, log
  a warning and do not apply it (never silently discard).
- Write unit tests for every rule above.

**NOT in scope**: changing `NovaClient.__init__`'s `region_prefix="us"` default
(TASK-2086 and others rely on it being unchanged); any dev_loop file; profiles;
dispatchers.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/bedrock_models.py` | MODIFY | Prefixes, vendor namespaces, new ids, `REQUIRES_REGION_PREFIX`, prefix policy in `translate()` |
| `packages/ai-parrot/tests/models/test_bedrock_models.py` | CREATE or MODIFY | Unit tests (check whether the file already exists first) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.models.bedrock_models import PUBLIC_TO_BEDROCK, translate
# verified: packages/ai-parrot/src/parrot/models/bedrock_models.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/bedrock_models.py
_REGION_PREFIXES: tuple[str, ...] = ("us.", "eu.", "apac.")   # line 27 — ADD "au.", "global."
PUBLIC_TO_BEDROCK: dict[str, str] = {                          # line 38
    "claude-sonnet-4-6": "anthropic.claude-sonnet-4-6-20260115-v1:0",
    "claude-haiku-4-5":  "anthropic.claude-haiku-4-5-20251001-v1:0",
    "nova-lite":         "amazon.nova-lite-v1:0",
    # ...
}
# line 65: "# claude-fable-5, claude-opus-4-8, claude-opus-4-7 — Bedrock IDs TBD."

def translate(public_id: str, region_prefix: str | None = None) -> str: ...
# Current documented strategy (module docstring, lines 1-19):
#   1. pass-through when the id contains "anthropic."/"amazon.", starts with
#      "arn:", or begins with a known region prefix
#   2. map lookup in PUBLIC_TO_BEDROCK
#   3. prepend "<prefix>." when region_prefix is given
#   4. unknown -> return unchanged + log a warning
```

### Verified AWS Facts (from the Bedrock model cards, 2026-08-03)

| Model | Bedrock ID | Geo IDs | Global ID | Prefix policy |
|---|---|---|---|---|
| Claude Opus 5 | `anthropic.claude-opus-5` | `us.` / `eu.` / `au.` | `global.anthropic.claude-opus-5` | **REQUIRES** (default `us`) |
| Claude Fable 5 | `anthropic.claude-fable-5` | — | `global.anthropic.claude-fable-5` | **REQUIRES** (default `global`) |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-20251001-v1:0` | `us.` | — | **REQUIRES** (default `us`) |
| MiniMax M2.5 | `minimax.minimax-m2.5` | Not supported | Not supported | **NEVER** |
| Kimi K2.5 | `moonshotai.kimi-k2.5` | Not supported | Not supported | **NEVER** |
| Z.ai GLM-5 | `zai.glm-5` | Not supported | Not supported | **NEVER** |

### Does NOT Exist

- ~~`REQUIRES_REGION_PREFIX`~~ — this task introduces it
- ~~`PUBLIC_TO_BEDROCK["claude-opus-5"]`~~ / ~~`["claude-fable-5"]`~~ / ~~`["minimax-m2.5"]`~~ / ~~`["kimi-k2.5"]`~~ / ~~`["glm-5"]`~~ — all absent today
- ~~`"au."` or `"global."` in `_REGION_PREFIXES`~~ — only `us.`, `eu.`, `apac.` today
- ~~A `-vN:0` suffix on Claude Opus 5 or Fable 5~~ — these ids have none; do not append one
- ~~"Claude Opus 5.8"~~ — no such model card exists; do not add an entry

---

## Implementation Notes

### Pattern to Follow

The module is deliberately **data + a small pure function**. Keep it that way:
extend the existing dict-and-tuple constants and the `translate()` branch chain;
do not introduce classes, I/O, or AWS calls.

```python
# Prefix policy — the ALLOWLIST inversion ([R6]):
#   model in REQUIRES_REGION_PREFIX  -> use caller's prefix, else the map default
#   model NOT in the map             -> NEVER prefix, whatever region_prefix says
#                                       (warn if the caller passed one explicitly)
```

### Key Constraints

- `NovaClient.region_prefix="us"` must keep working unchanged for Nova 2
  Lite/Premier — this task must not require any caller to change.
- Unknown/future ids must still warn-and-passthrough, never raise.
- Google-style docstrings; module-level `logger`, already present at line 23.
- Pure functions — no network, no boto3 import.

### References in Codebase

- `packages/ai-parrot/src/parrot/models/bedrock_models.py` — the file itself; its
  docstring (lines 1-19) documents the current 4-step strategy to extend
- `packages/ai-parrot/src/parrot/clients/nova/client.py:72` — the `region_prefix`
  default this task must NOT change

---

## Acceptance Criteria

- [ ] `translate("minimax.minimax-m2.5", region_prefix="us")` returns
      `"minimax.minimax-m2.5"` — **the day-one bug is unreachable**
- [ ] `translate("moonshotai.kimi-k2.5", region_prefix="us")` and
      `translate("zai.glm-5", region_prefix="us")` likewise return the bare id
- [ ] `au.` and `global.` are recognised pass-through prefixes
- [ ] `minimax.`, `zai.`, `moonshotai.` ids pass through with **no** warning
- [ ] A mapped model uses the caller's prefix when given, the map default otherwise
- [ ] An explicit prefix for an unmapped model logs a warning and is not applied
- [ ] Claude Opus 5 / Fable 5 map without a `-vN:0` suffix
- [ ] Unknown ids still warn-and-passthrough (no exception)
- [ ] `pytest packages/ai-parrot/tests/models/test_bedrock_models.py -v` passes
- [ ] `ruff check packages/ai-parrot/src/parrot/models/bedrock_models.py` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/models/test_bedrock_models.py
import pytest
from parrot.models.bedrock_models import REQUIRES_REGION_PREFIX, translate


class TestPrefixPolicy:
    def test_unmapped_model_never_prefixed(self):
        """THE day-one bug: region_prefix must not leak onto MiniMax."""
        assert translate("minimax.minimax-m2.5", region_prefix="us") == "minimax.minimax-m2.5"

    @pytest.mark.parametrize("model_id", ["moonshotai.kimi-k2.5", "zai.glm-5"])
    def test_other_prefixless_models(self, model_id):
        assert translate(model_id, region_prefix="us") == model_id

    def test_mapped_model_uses_caller_prefix(self):
        assert translate("claude-opus-5", region_prefix="eu").startswith("eu.")

    def test_mapped_model_falls_back_to_map_default(self):
        assert "claude-opus-5" in REQUIRES_REGION_PREFIX
        assert translate("claude-opus-5").startswith(
            f"{REQUIRES_REGION_PREFIX['claude-opus-5']}."
        )

    def test_explicit_prefix_on_unmapped_model_warns(self, caplog):
        result = translate("minimax.minimax-m2.5", region_prefix="us")
        assert result == "minimax.minimax-m2.5"
        assert any("prefix" in r.message.lower() for r in caplog.records)


class TestPassThrough:
    @pytest.mark.parametrize("prefix", ["us.", "eu.", "apac.", "au.", "global."])
    def test_known_prefixes_pass_through(self, prefix):
        already = f"{prefix}anthropic.claude-opus-5"
        assert translate(already) == already

    @pytest.mark.parametrize("model_id", [
        "minimax.minimax-m2.5", "zai.glm-5", "moonshotai.kimi-k2.5",
    ])
    def test_vendor_namespaces_no_warning(self, model_id, caplog):
        assert translate(model_id) == model_id
        assert not [r for r in caplog.records if r.levelname == "WARNING"]


class TestNewMapEntries:
    def test_opus5_has_no_version_suffix(self):
        assert translate("claude-opus-5", region_prefix=None) == "anthropic.claude-opus-5"

    def test_fable5_has_no_version_suffix(self):
        assert "claude-fable-5" in str(translate("claude-fable-5"))
        assert "-v1:0" not in translate("claude-fable-5")

    def test_unknown_id_warns_and_passes_through(self, caplog):
        assert translate("totally-made-up-model") == "totally-made-up-model"
        assert any(r.levelname == "WARNING" for r in caplog.records)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, Module 1, §7 Known Risks)
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `_REGION_PREFIXES` is still at/near line 27 and `PUBLIC_TO_BEDROCK` near line 38
   - Confirm `translate()`'s current signature and branch order
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2083-bedrock-model-id-translation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-03
**Notes**: Added `au.`/`global.` to `_REGION_PREFIXES`; added `_VENDOR_NAMESPACES`
("minimax.", "zai.", "moonshotai.") to `_is_bedrock_id()` pass-through detection;
added `PUBLIC_TO_BEDROCK["claude-opus-5"]`/`["claude-fable-5"]` with no `-vN:0`
suffix; introduced `REQUIRES_REGION_PREFIX` allowlist (`claude-opus-5`→`us`,
`claude-fable-5`→`global`, `claude-haiku-4-5`→`us`). `translate()` now: (1)
pass-through ids warn (not silently drop) an explicit `region_prefix` that
isn't in the allowlist; (2) an explicit `region_prefix` on a MAPPED model
still applies unconditionally (preserves 100% backward compat with existing
Nova/Claude tests, e.g. `nova-canvas` + `region_prefix="us"` still prefixes);
(3) when no explicit prefix is given, the allowlist default applies — models
absent from it are NEVER auto-prefixed (closes the day-one MiniMax bug).
`NovaClient.__init__`'s `region_prefix="us"` default is unchanged. All 43
tests pass (`pytest packages/ai-parrot/tests/models/ packages/ai-parrot/tests/test_bedrock_models.py -v`),
`ruff check` clean, no new mypy errors in the changed file.

**Deviations from spec**: The task's own "Test Specification" scaffold
contained a self-contradiction — `test_mapped_model_falls_back_to_map_default`
expects `translate("claude-opus-5")` (no args) to include the default `us.`
prefix, while `test_opus5_has_no_version_suffix` expects
`translate("claude-opus-5", region_prefix=None)` (the same call, since the
default arg value is `None`) to equal `"anthropic.claude-opus-5"` with NO
prefix. Both cannot hold simultaneously. Resolved in favor of the
Acceptance Criteria text ("A mapped model uses the caller's prefix when
given, the map default otherwise"): the no-suffix assertion was rewritten as
`test_opus5_bedrock_id_has_no_version_suffix` / `test_fable5_bedrock_id_has_no_version_suffix`,
checking `PUBLIC_TO_BEDROCK` directly instead of round-tripping through
`translate()` with no prefix, and a new `test_opus5_default_prefix_applied`
was added to lock in the "map default otherwise" behavior explicitly.
