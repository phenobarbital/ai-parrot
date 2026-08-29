# FEAT-470 TASK-2547 — Producer first-shot catalog-valid rate (Module 9 spike)

**Spec requirement** (§4 Integration Tests, §5 Acceptance Criteria): 20 display-UI
prompts fed through `parrot.outputs.a2ui.producer.generate_envelope` with
`max_attempts=1` (no retry — measuring genuine *first-shot* validity), catalog-valid
rate >= 85%.

## Status: harness implemented, NOT executed in this sandboxed run

No live LLM credentials (`ANTHROPIC_API_KEY` or equivalent) were available in this
worktree's sandbox, so the spike could not actually be run end-to-end against a real
model. Fabricating a pass rate would violate the task's explicit instruction to be
honest about this limitation, so none is reported here.

What IS in place and ready to run:

- `packages/ai-parrot/tests/outputs/a2ui/test_producer.py::TestE2ELLMProducerFirstShotRate::test_first_shot_rate_at_least_85_percent`
  — marked `@pytest.mark.real_llm` (repo convention: `tests/conftest.py` skips any
  test carrying this marker unless `PARROT_TEST_REAL_LLM=1` is set — this is the
  same marker/skip convention already used elsewhere in the repo, e.g.
  `tests/agents/test_obsidian.py`).
- 20 distinct display-UI prompts (`_SPIKE_PROMPTS`), covering InfoCard/KPICard/
  Chart/DataTable requests.
- Uses `parrot.clients.claude.AnthropicClient()` (repo default model
  `claude-sonnet-4-5`, matching the spec's "`claude-sonnet-4-5` o el modelo por
  defecto del repo").
- Each prompt goes through `generate_envelope(client, prompt, max_attempts=1)` —
  `result.degraded is False` counts as a first-shot catalog-valid success.
- On completion, the test itself appends its live result to this file (see
  `_append_rate_log` in the test module) — the next section will show a real
  `## Live run — …` entry the first time it actually executes.

## How to run it for real

```bash
source .venv/bin/activate
export PARROT_TEST_REAL_LLM=1
export ANTHROPIC_API_KEY=<key>
pytest packages/ai-parrot/tests/outputs/a2ui/test_producer.py::TestE2ELLMProducerFirstShotRate -v
```

## Acceptance criterion status

The spec's "spike first-shot rate >= 85%, evidence in
`artifacts/logs/feat-470-producer-rate.md`" acceptance criterion is **NOT verified**
by this task run — the harness is implemented and correct per spec, but no live
numbers were obtained. This is called out explicitly (not silently marked done) in
the TASK-2547 Completion Note; see `sdd/tasks/completed/TASK-2547-producer-emission-toolkits-v1.md`.
