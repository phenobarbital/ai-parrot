# TASK-2278: `QueryClassifier` decision list + `RetrievalRoutingDecision` + replay tests

**Feature**: FEAT-435 — GraphIndex Retrieval Layer
**Spec**: `sdd/specs/graphindex-retriever.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L
**Depends-on**: TASK-2277, TASK-2276
**Assigned-to**: unassigned
**Spec task ref**: T4 (spec §10)

---

## Context

Spec §4.3. Deliberately a decision list, not a model — "auditable, zero
warm-up, zero drift". Ordered, first-match-wins, seven rules. INV-3 makes it a
pure function of `(query_text, GraphStats, RetrievalBudget)`: no I/O, no LLM, no
clock, same inputs → same decision, always replayable offline.

**Naming:** the model is `RetrievalRoutingDecision`, not `RoutingDecision` —
that name is already taken by `parrot/bots/mixins/intent_router.py:378` for LLM
intent routing (spec §5.0). Getting this wrong creates a confusing collision in
a codebase that already has one router.

---

## Scope

- `QueryClass(StrEnum)`: `DIRECT_SYMBOL LOCAL_FACT RELATIONAL RATIONALE
  GLOBAL_SUMMARY COMPARATIVE UNKNOWN`.
- `RetrievalRoutingDecision` (frozen, `extra="forbid"`): `query_class`,
  `policy`, `matched_rule: str`, `features: QueryFeatures`,
  `escalations: tuple[EscalationStep, ...] = ()`.
- `QueryClassifier.classify(query, stats, budget) -> RetrievalRoutingDecision`
  implementing R1–R7 **in order, first match wins**, exactly as §4.3 writes
  them:
  - R1 `anchor_count == 1 and token_count <= 6 and not has_relational_verb` →
    `DIRECT_SYMBOL`
  - R2 `has_causal_marker` → `RATIONALE`
  - R3 `anchor_count >= 2` → `COMPARATIVE`
  - R4 `has_relational_verb and anchor_count >= 1` → `RELATIONAL`
  - R5 `has_aggregation_marker and not has_code_literal` → `GLOBAL_SUMMARY`
  - R6 `anchor_count >= 1 or has_code_literal` → `LOCAL_FACT`
  - R7 otherwise → `UNKNOWN`
- `matched_rule` carries the literal rule id (`"R4"`) so a decision is
  replayable and auditable.
- `policy_override` on the request bypasses classification and sets
  `matched_rule = "OVERRIDE"`, **and is logged** (§4.5).
- `shadow_mode` flag: classify and log without acting, for offline calibration
  against the golden set before routing is trusted (§4.5).
- Default policy per class per the §4.1 table. For classes whose policy is not
  in the v1 cut (`RELATIONAL`→PPR, `COMPARATIVE`→Steiner,
  `GLOBAL_SUMMARY`→Ancestry, `RATIONALE`→Rationale), fall back to
  `VectorSeedPolicy` and **record the substitution** in the decision — do not
  silently pretend the intended policy ran.

**NOT in scope**:

- `SectionSelector` — TASK-2279.
- `SufficiencyCheck` / escalation execution — TASK-2282. This task only defines
  the `escalations` field.
- Any policy implementation.

---

## Files to Create / Modify

- `packages/ai-parrot/src/parrot/knowledge/retrieval/classifier.py` — new.
- `packages/ai-parrot/tests/knowledge/retrieval/test_classifier.py` — new.

---

## Codebase Contract (Anti-Hallucination)

Verified on `dev` @ `bfa056bc7`, 2026-08-20. Spec §14 holds the full contract;
this is the slice this task needs. **Re-verify before you rely on it** — run
the greps yourself if anything looks stale.

### Verified Imports

```python
from parrot.knowledge.retrieval.features import QueryFeatures, extract_features
from parrot.knowledge.retrieval.symbols import DerivedSymbolIndex
from parrot.knowledge.retrieval.models import RetrievalBudget
```

### Existing Signatures to Use

```python
# parrot/knowledge/retrieval/features.py  (TASK-2277)
class QueryFeatures(BaseModel):   # frozen, extra="forbid"
    resolved_symbols: tuple[NodeRef, ...]; anchor_count: int
    has_relational_verb: bool; has_causal_marker: bool
    has_aggregation_marker: bool; has_code_literal: bool
    token_count: int; interrogative: Interrogative
```

### Does NOT Exist

- **`parrot.knowledge.retrieval` does not exist yet.** You may be the task that
  creates it. There is nothing to extend, no base class waiting for you.
- **`RoutingDecision` EXISTS but is NOT ours.** It belongs to
  `parrot/bots/mixins/intent_router.py:378` (LLM intent routing). This feature's
  model is **`RetrievalRoutingDecision`**. Never import or extend the former.
- **`UniversalNode` has no `repo`, `rev`, `digest`, `line_span`, or `qualname`
  field.** Verified: `parrot/knowledge/graphindex/schema.py`. Do not write code
  that reads them. Line spans live in `domain_tags["lineno"/"end_lineno"]`;
  symbol kind lives in `domain_tags["symbol_type"]`.
- **There is no symbol trie or symbol table.** `graphindex/resolve.py` is a
  cross-domain *embedding-similarity* stage emitting `mentions` edges — it does
  NOT resolve names. Do not `from parrot.knowledge.graphindex.resolve import`
  anything expecting lookup.
- **`NodeKind` has no `Module`/`Class`/`Function` members.** The real set is
  `DOCUMENT SECTION SYMBOL CONCEPT RATIONALE SKILL WIKI_PAGE RUN CLAIM`.
- **`RoutingDecision` is NOT this model.** `parrot/bots/mixins/
  intent_router.py:378` owns that name and constructs it at `:378, :386, :407,
  :505`. Do not import it, do not extend it, do not rename it. Use
  `RetrievalRoutingDecision`.
- **`GraphStats` does not exist yet.** INV-3 names it as a classify() input.
  Define a minimal frozen model here (node count, edge count, per-kind counts)
  or accept `None`; do not hunt for it in `graphindex/analytics.py` and wire up
  something heavier than the classifier's latency budget allows.
- **`EscalationStep` does not exist yet.** Define the field's type here (or a
  placeholder) — TASK-2282 populates it.
- **No ML/model-based classifier.** §4.3 rejects it explicitly. No sklearn, no
  embeddings, no LLM call.

---

## Implementation Notes

### Pattern to Follow

Implement as an ordered list of `(rule_id, predicate, query_class)` tuples
iterated in sequence, so the rule table reads like §4.3 and a reviewer can diff
them line by line. That structure also makes the "every rule is reachable" test
trivial to write and makes future rule changes visibly ordered rather than
buried in an `if/elif` chain.

### Key Constraints

- **Frozen Pydantic v2 everywhere**: `model_config = ConfigDict(frozen=True,
  extra="forbid")`. Every model in spec §3 declares this; match it.
- **Google-style docstrings + strict type hints** on every public function and
  class (project rule, `CLAUDE.md`).
- `self.logger = logging.getLogger(__name__)` — never `print`.
- `async`/`await` throughout; `aiosqlite` for SQLite, never blocking `sqlite3`.
- No `requests`/`httpx` — `aiohttp` only (project rule).
- **INV-3 is the hard constraint.** `classify()` must do no I/O, no LLM call,
  and read no clock. Test it by patching `open`, `socket.socket`, and
  `datetime.datetime.now` to raise.

### References in Codebase

- Spec §4.3 (the rule table — implement verbatim), §4.1 (class → policy),
  §4.5 (escape hatches), INV-3, §5.0 (naming).

---

## Acceptance Criteria

- [ ] Each of R1–R7 has a fixture that matches it, and `matched_rule` names
      that exact rule.
- [ ] First-match-wins verified: an input satisfying both R2 and R3 yields R2.
- [ ] `classify()` is byte-identical across repeated calls on the same input.
- [ ] Patching `open`/`socket`/`datetime.now` to raise does not break
      `classify()` (INV-3).
- [ ] `policy_override` → `matched_rule == "OVERRIDE"` and a log record is
      emitted.
- [ ] `shadow_mode` returns a decision without it being acted upon.
- [ ] A class whose intended policy is deferred records the substitution rather
      than misreporting the policy.
- [ ] The model is named `RetrievalRoutingDecision`; grep proves no import of
      `bots.mixins.intent_router`.
- [ ] `ruff` + `mypy` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/retrieval/test_classifier.py
@pytest.mark.parametrize("rule,query,expected", [
    ("R1", "`PayRateEngine.resolve`", QueryClass.DIRECT_SYMBOL),
    ("R2", "¿por qué el rate se congela en clock-out?", QueryClass.RATIONALE),
    ("R3", "diferencia entre el bus viejo y `navigator-eventbus`",
     QueryClass.COMPARATIVE),
    ("R4", "¿quién llama a `NoApplicableRule`?", QueryClass.RELATIONAL),
    ("R5", "¿cómo funciona el módulo de outputs?", QueryClass.GLOBAL_SUMMARY),
    ("R6", "`resolve()`", QueryClass.LOCAL_FACT),
    ("R7", "hola", QueryClass.UNKNOWN),
])
def test_every_rule_reachable_and_named(rule, query, expected): ...
def test_first_match_wins_r2_beats_r3(): ...
def test_classify_is_pure_inv3(monkeypatch): ...
def test_override_sets_matched_rule_and_logs(caplog): ...
def test_shadow_mode_does_not_act(): ...
def test_deferred_policy_substitution_is_recorded(): ...
```

---

## Agent Instructions

1. Read the spec section(s) named in **Context** before writing code. The spec
   is the SSOT; this task file is a view onto it.
2. Write the tests first (see **Test Specification**), watch them fail, then
   implement. TDD is not optional here — every one of these tasks encodes an
   invariant.
3. Do NOT modify anything under `parrot/knowledge/graphindex/` or
   `parrot_tools/multistoresearch/`. L0 is consumed **read-only** (spec §1.2)
   and FEAT-217/FEAT-379 are untouched by design (spec §5.0). If you believe a
   change there is required, STOP and record it in the Completion Note instead.
4. Run `pytest packages/ai-parrot/tests/knowledge/retrieval/ -v`, then `ruff check` and `mypy` on the files you
   touched. Paste real output into the Completion Note — no claims without
   evidence.
5. Commit once, message: `feat(FEAT-435): <what> (TASK-<NNN>)`.
6. Fill in the Completion Note. If you hit an ambiguity, record it there rather
   than inventing a resolution.

---

## Completion Note

*(Agent fills this in when done — include real command output, not claims.)*

**Completed by**:
**Date**:
