"""Prompt-injection guardrail latency + quality benchmark.

Measures the tiers that a future tiered ``PromptInjectionGuardrail`` would
use — regex, embedding-similarity, and a transformer classifier under
torch/ONNX-fp32/ONNX-int8 — on latency, memory, detection quality, and
(the decisive metric) **escalation rate**: how often the cheap tiers
already decide, so the expensive tier never has to run.

See ``sdd/proposals/nlproxy-guardrails.comparison.md`` §4.1/§4.3 and §5.3.
"""
