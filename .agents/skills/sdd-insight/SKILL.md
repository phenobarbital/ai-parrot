---
name: sdd-insight
description: Analyze Claude Code transcripts and repo-level SDD Process Discipline from the sdd/ artifact tree using the local Insight engine.
---

# SDD Insight

## Full procedure and Codex adaptations

Before executing, read the [full sdd-insight procedure](../../../.claude/commands/sdd-insight.md)
and the [Codex adaptation contract](../../../docs/sdd/CODEX.md#codex-adaptation-contract).
Follow the full procedure for details omitted from this summary. The adaptation
contract and the Codex-specific instructions below override Claude runtime syntax
and legacy shell examples; retain all workflow gates and evidence requirements.

Use this skill when the user asks to analyze AI fluency, review prompt collaboration patterns, or evaluate repo-level SDD Process Discipline adherence.

Invocation: `$sdd-insight [TRANSCRIPT_PATH] [--no-open] [--sdd-dir PATH | --no-sdd]`.

## Purpose

Execute `scripts/sdd/insight.py` to produce a two-layer analytical report:
1. Personal AI-fluency skill map (score, archetype, competencies, growth levers) from transcripts.
2. Repo-level SDD Process Discipline panel (pipeline progression, decomposition quality, AC coverage, cycle closure, review rigor) computed deterministically from `sdd/`.

## Guardrails

- Transcripts and `sdd/` files are read strictly read-only.
- Always run within the virtual environment (`source .venv/bin/activate`).
- The engine reads Claude Code JSONL transcripts (default `~/.claude/projects`).
  Native Codex session logs are not supported by this workflow; never present
  Claude-derived personal scores as measurements of Codex sessions.
- Use a fresh report directory under `artifacts/` so old analysis cannot leak
  into a new run. Do not delete previous reports.

## Workflow

1. Parse the optional transcript path and supported flags into a shell argument
   array `insight_args`. Preserve paths as single quoted arguments; never eval
   user text. With no arguments, use `insight_args=()`.
2. Run deterministic measurement from the repository root:
   ```bash
   source .venv/bin/activate
   mkdir -p artifacts
   insight_run_dir=$(mktemp -d artifacts/sdd-insight.XXXXXX)
   python3 scripts/sdd/insight.py --evidence "$insight_run_dir/evidence.json" --sdd-dir sdd --no-open --quiet -o "$insight_run_dir/report.html" "${insight_args[@]}"
   ```
   Check the exit status and evidence/report files. If no compatible transcripts
   are found, report that limitation and stop; do not invent scores or promise
   a standalone SDD report that this engine did not produce.
3. If the `sdd-insight` analysis workflow capability is available, give it the
   absolute evidence path and `reference/sdd-insight/ai-fluency-framework.md`.
   Save its JSON to this run's `analysis.json`, then render with matching evidence:
   ```bash
   python3 scripts/sdd/insight.py --analysis "$insight_run_dir/analysis.json" --analysis-evidence "$insight_run_dir/evidence.json" --sdd-dir sdd -o "$insight_run_dir/report.html" "${insight_args[@]}"
   ```
   Otherwise use the complete deterministic report. A fingerprint mismatch also
   falls back to deterministic output; disclose which report was produced.
4. Link the final HTML report and present its findings, identifying the transcript source:
   - Personal score and archetype.
   - Top growth lever.
   - Repo SDD Process Discipline score and weakest dimension.

## References

- `scripts/sdd/insight.py`
- `reference/sdd-insight/ai-fluency-framework.md`
- `sdd/WORKFLOW.md`
