---
type: Wiki Summary
title: parrot_tools.massive.models
id: mod:parrot_tools.massive.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic models for MassiveToolkit.
relates_to:
- concept: class:parrot_tools.massive.models.AnalystAction
  rel: defines
- concept: class:parrot_tools.massive.models.AnalystRatingsDerived
  rel: defines
- concept: class:parrot_tools.massive.models.AnalystRatingsInput
  rel: defines
- concept: class:parrot_tools.massive.models.AnalystRatingsOutput
  rel: defines
- concept: class:parrot_tools.massive.models.ConsensusRating
  rel: defines
- concept: class:parrot_tools.massive.models.EarningsDataInput
  rel: defines
- concept: class:parrot_tools.massive.models.EarningsDerived
  rel: defines
- concept: class:parrot_tools.massive.models.EarningsOutput
  rel: defines
- concept: class:parrot_tools.massive.models.EarningsRecord
  rel: defines
- concept: class:parrot_tools.massive.models.GreeksData
  rel: defines
- concept: class:parrot_tools.massive.models.NextEarnings
  rel: defines
- concept: class:parrot_tools.massive.models.OptionsChainInput
  rel: defines
- concept: class:parrot_tools.massive.models.OptionsChainOutput
  rel: defines
- concept: class:parrot_tools.massive.models.OptionsContract
  rel: defines
- concept: class:parrot_tools.massive.models.ShortInterestDerived
  rel: defines
- concept: class:parrot_tools.massive.models.ShortInterestInput
  rel: defines
- concept: class:parrot_tools.massive.models.ShortInterestOutput
  rel: defines
- concept: class:parrot_tools.massive.models.ShortInterestRecord
  rel: defines
- concept: class:parrot_tools.massive.models.ShortVolumeDerived
  rel: defines
- concept: class:parrot_tools.massive.models.ShortVolumeInput
  rel: defines
- concept: class:parrot_tools.massive.models.ShortVolumeOutput
  rel: defines
- concept: class:parrot_tools.massive.models.ShortVolumeRecord
  rel: defines
---

# `parrot_tools.massive.models`

Pydantic models for MassiveToolkit.

Input models define the schema for agent tool calls.
Output models define the structured response format with derived metrics.

## Classes

- **`OptionsChainInput(BaseModel)`** — Input model for get_options_chain_enriched tool.
- **`ShortInterestInput(BaseModel)`** — Input model for get_short_interest tool.
- **`ShortVolumeInput(BaseModel)`** — Input model for get_short_volume tool.
- **`EarningsDataInput(BaseModel)`** — Input model for get_earnings_data tool.
- **`AnalystRatingsInput(BaseModel)`** — Input model for get_analyst_ratings tool.
- **`GreeksData(BaseModel)`** — Greeks data for an options contract.
- **`OptionsContract(BaseModel)`** — Single options contract with Greeks and pricing.
- **`OptionsChainOutput(BaseModel)`** — Output model for get_options_chain_enriched.
- **`ShortInterestRecord(BaseModel)`** — Single short interest record.
- **`ShortInterestDerived(BaseModel)`** — Derived metrics for short interest.
- **`ShortInterestOutput(BaseModel)`** — Output model for get_short_interest.
- **`ShortVolumeRecord(BaseModel)`** — Single short volume record.
- **`ShortVolumeDerived(BaseModel)`** — Derived metrics for short volume.
- **`ShortVolumeOutput(BaseModel)`** — Output model for get_short_volume.
- **`EarningsRecord(BaseModel)`** — Single earnings record.
- **`NextEarnings(BaseModel)`** — Next scheduled earnings.
- **`EarningsDerived(BaseModel)`** — Derived metrics for earnings.
- **`EarningsOutput(BaseModel)`** — Output model for get_earnings_data.
- **`AnalystAction(BaseModel)`** — Single analyst rating action.
- **`ConsensusRating(BaseModel)`** — Consensus rating summary.
- **`AnalystRatingsDerived(BaseModel)`** — Derived metrics for analyst ratings.
- **`AnalystRatingsOutput(BaseModel)`** — Output model for get_analyst_ratings.
