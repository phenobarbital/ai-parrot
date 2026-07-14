---
type: Wiki Summary
title: parrot_tools.workday.models
id: mod:parrot_tools.workday.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Workday Response Models and Structured Output Parser
relates_to:
- concept: class:parrot_tools.workday.models.Address
  rel: defines
- concept: class:parrot_tools.workday.models.Compensation
  rel: defines
- concept: class:parrot_tools.workday.models.ContactModel
  rel: defines
- concept: class:parrot_tools.workday.models.EmailAddress
  rel: defines
- concept: class:parrot_tools.workday.models.JobProfile
  rel: defines
- concept: class:parrot_tools.workday.models.Manager
  rel: defines
- concept: class:parrot_tools.workday.models.OrganizationModel
  rel: defines
- concept: class:parrot_tools.workday.models.PhoneNumber
  rel: defines
- concept: class:parrot_tools.workday.models.Position
  rel: defines
- concept: class:parrot_tools.workday.models.TimeOffBalance
  rel: defines
- concept: class:parrot_tools.workday.models.TimeOffBalanceModel
  rel: defines
- concept: class:parrot_tools.workday.models.WorkdayReference
  rel: defines
- concept: class:parrot_tools.workday.models.WorkdayResponseParser
  rel: defines
- concept: class:parrot_tools.workday.models.WorkerModel
  rel: defines
---

# `parrot_tools.workday.models`

Workday Response Models and Structured Output Parser

Provides clean Pydantic models for Workday objects with:
1. Default models per object type (Worker, Organization, etc.)
2. Support for custom output formats
3. Automatic parsing from verbose Zeep responses

## Classes

- **`WorkdayReference(BaseModel)`** — Standard Workday reference object.
- **`EmailAddress(BaseModel)`** — Email address with metadata.
- **`PhoneNumber(BaseModel)`** — Phone number with metadata.
- **`Address(BaseModel)`** — Physical address.
- **`JobProfile(BaseModel)`** — Job profile information.
- **`Position(BaseModel)`** — Worker position information.
- **`Manager(BaseModel)`** — Manager reference.
- **`Compensation(BaseModel)`** — Compensation information.
- **`TimeOffBalance(BaseModel)`** — Individual time off balance for a specific time off type.
- **`TimeOffBalanceModel(BaseModel)`** — Clean Time Off Balance model - Default output for time off information.
- **`WorkerModel(BaseModel)`** — Clean, structured Worker model - Default output format.
- **`OrganizationModel(BaseModel)`** — Clean Organization model.
- **`ContactModel(BaseModel)`** — Clean Contact model - Default output for contact information.
- **`WorkdayResponseParser`** — Parser that transforms verbose Zeep responses into clean Pydantic models.
