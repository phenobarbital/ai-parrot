---
type: Wiki Summary
title: parrot.flows.dev_loop.models
id: mod:parrot.flows.dev_loop.models
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pydantic v2 contracts for the dev-loop orchestration flow (FEAT-129).
relates_to:
- concept: class:parrot.flows.dev_loop.models.ClaudeCodeDispatchProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.ClaudeCodeReviewProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.CodeReviewFinding
  rel: defines
- concept: class:parrot.flows.dev_loop.models.CodeReviewVerdict
  rel: defines
- concept: class:parrot.flows.dev_loop.models.CodexCodeDispatchProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.CodexCodeReviewProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.CriterionResult
  rel: defines
- concept: class:parrot.flows.dev_loop.models.DevelopmentOutput
  rel: defines
- concept: class:parrot.flows.dev_loop.models.DispatchEvent
  rel: defines
- concept: class:parrot.flows.dev_loop.models.FlowtaskCriterion
  rel: defines
- concept: class:parrot.flows.dev_loop.models.GeminiCodeDispatchProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.GeminiCodeReviewProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.GrokCodeDispatchProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.LLMCodeDispatchProfile
  rel: defines
- concept: class:parrot.flows.dev_loop.models.LogSource
  rel: defines
- concept: class:parrot.flows.dev_loop.models.ManualCriterion
  rel: defines
- concept: class:parrot.flows.dev_loop.models.QAReport
  rel: defines
- concept: class:parrot.flows.dev_loop.models.RepoSpec
  rel: defines
- concept: class:parrot.flows.dev_loop.models.ResearchOutput
  rel: defines
- concept: class:parrot.flows.dev_loop.models.RevisionBrief
  rel: defines
- concept: class:parrot.flows.dev_loop.models.ShellCriterion
  rel: defines
- concept: class:parrot.flows.dev_loop.models.WorkBrief
  rel: defines
- concept: class:parrot.flows.dev_loop.models.ZaiCodeDispatchProfile
  rel: defines
---

# `parrot.flows.dev_loop.models`

Pydantic v2 contracts for the dev-loop orchestration flow (FEAT-129).

This module is the foundation for ``parrot.flows.dev_loop``. Every other
sub-module (dispatcher, nodes, flow factory, streaming multiplexer)
imports its data structures from here.

The module intentionally has **zero internal dependencies** beyond the
Pydantic v2 runtime. In particular, it MUST NOT import anything from
``claude_agent_sdk`` at top level so that ``import parrot.flows.dev_loop``
succeeds even when the optional ``[claude-agent]`` extra is not installed.

See ``sdd/specs/dev-loop-orchestration.spec.md`` §2 "Data Models" for the
authoritative contracts.
See ``sdd/specs/feat-129-upgrades.spec.md`` §3 Module 1 for the FEAT-132
``WorkBrief`` rename and ``kind`` field.

## Classes

- **`FlowtaskCriterion(_AcceptanceCriterionBase)`** — Run a Flowtask YAML/JSON pipeline and assert its exit code.
- **`ShellCriterion(_AcceptanceCriterionBase)`** — Run an allow-listed shell command and assert its exit code.
- **`ManualCriterion(BaseModel)`** — Human-readable acceptance statement that the QA subagent must NOT run.
- **`LogSource(BaseModel)`** — A pointer to a log location that ``ResearchNode`` will fetch.
- **`WorkBrief(BaseModel)`** — User-facing input contract for the dev-loop flow.
- **`RepoSpec(BaseModel)`** — A git repository the dev-loop run operates on.
- **`RevisionBrief(BaseModel)`** — Input to a revision-mode run (no new PR; update an existing one).
- **`ResearchOutput(BaseModel)`** — Structured output from the ``sdd-research`` dispatch.
- **`DevelopmentOutput(BaseModel)`** — Structured output from the ``sdd-worker`` dispatch.
- **`CriterionResult(BaseModel)`** — Result of running a single acceptance criterion in QA.
- **`QAReport(BaseModel)`** — Structured output from the ``sdd-qa`` dispatch.
- **`ClaudeCodeDispatchProfile(BaseModel)`** — Declarative profile consumed by ``ClaudeCodeDispatcher.dispatch()``.
- **`CodexCodeDispatchProfile(BaseModel)`** — Declarative profile consumed by ``CodexCodeDispatcher.dispatch()``.
- **`GeminiCodeDispatchProfile(BaseModel)`** — Declarative profile consumed by ``GeminiCodeDispatcher.dispatch()``.
- **`LLMCodeDispatchProfile(BaseModel)`** — Declarative profile consumed by ``LLMCodeDispatcher.dispatch()``.
- **`GrokCodeDispatchProfile(BaseModel)`** — Declarative profile consumed by ``GrokCodeDispatcher.dispatch()``.
- **`ZaiCodeDispatchProfile(LLMCodeDispatchProfile)`** — Declarative profile consumed by ``ZaiCodeDispatcher.dispatch()``.
- **`CodeReviewFinding(BaseModel)`** — A single finding from the code review (FEAT-270).
- **`CodeReviewVerdict(BaseModel)`** — Extended verdict emitted by all code review dispatchers (FEAT-270).
- **`ClaudeCodeReviewProfile(ClaudeCodeDispatchProfile)`** — Review profile for the Claude Code review dispatcher (FEAT-270).
- **`CodexCodeReviewProfile(CodexCodeDispatchProfile)`** — Review profile for the Codex code review dispatcher (FEAT-270).
- **`GeminiCodeReviewProfile(GeminiCodeDispatchProfile)`** — Review profile for the Gemini code review dispatcher (FEAT-270).
- **`DispatchEvent(BaseModel)`** — Envelope for stream-json events published to Redis.
