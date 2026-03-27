# OpenAI model refresh plan

## Scope
- Update `packages/ai-parrot/src/parrot/models/openai.py` to reflect currently supported OpenAI model IDs.
- Update `packages/ai-parrot/src/parrot/clients/gpt.py` for any enum-driven routing or compatibility lists impacted by the new model IDs.

## Assumptions
- Remove only models explicitly marked deprecated by OpenAI.
- Keep legacy or older-but-still-supported models to avoid unnecessary compatibility breakage.

## Risks
- Removing enum members can break callers that still reference them.
- Adding new model IDs without updating client routing could cause endpoint mismatches.

## Verification
- Sanity-check enum references with `rg`.
- Run a lightweight syntax validation on touched Python files.
