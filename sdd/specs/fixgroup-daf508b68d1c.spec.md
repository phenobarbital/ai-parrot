---
type: feature
base_branch: dev
projects: [ai-parrot-server]
tags: [a2ui, testing, tech-debt]
---

# Feature Specification: A2UI stream contract tests match the reformatted handler

**Feature ID**: FEAT-767
**Date**: 2026-10-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch
**Discovered-from**: `issue:46f02d0469bb`

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` guards the
AgentTalk chunked-stream wire contract by grepping the source of
`parrot/handlers/agent.py`. Two tests fail on `dev`:

- `test_chunked_wire_contract_unchanged` looks for `'X-Parrot-Stream': 'chunked-aimessage'`.
- `test_a2ui_envelope_added_to_final_stream_dict` looks for
  `a2ui_envelope = getattr(ai_message, 'a2ui_envelope', None)` and
  `envelope['a2ui_envelope'] = a2ui_envelope`.

The handler still has this behavior, but `black` reformatted it to double
quotes (`"X-Parrot-Stream": "chunked-aimessage"`,
`getattr(ai_message, "a2ui_envelope", None)`,
`envelope["a2ui_envelope"] = a2ui_envelope`). The contract is unchanged; only
the tests' literal strings are out of date.

### Goals
- The contract tests pass against the current handler and still fail if the header, separator or envelope key is removed.
- The tests stop depending on the handler's quote style.

### Non-Goals (explicitly out of scope)
- Changing `parrot/handlers/agent.py` or the wire contract.
- Replacing source inspection with runtime tests.

---

## 2. Architectural Design

### Overview
Match the contract snippets with regular expressions that accept either quote
style (`["']`) instead of exact single-quoted literals. Apply this to the two
failing tests, and to the separator assertion in the same test so it does not
break on the next reformat.

---

## 3. Module Breakdown

### Module 1: Contract test update (TASK-4876)
- `packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` (MODIFY)

---

## 4. Test Specification

### Unit Tests
- `TestA2UIStreamContract::test_chunked_wire_contract_unchanged` passes on the current handler.
- `TestA2UIStreamContract::test_a2ui_envelope_added_to_final_stream_dict` passes on the current handler.
- The other tests in the file keep passing.

### Validation Contract
`pytest packages/ai-parrot-server/tests/handlers/test_agent_a2ui_stream.py` with `PYTHONPATH=packages/ai-parrot-server/src`.
