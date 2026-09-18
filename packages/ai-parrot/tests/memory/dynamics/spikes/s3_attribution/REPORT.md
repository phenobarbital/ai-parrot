# S3 (TASK-3384) — Attribution Precision and Verified-Outcome Evidence Schema — Gate Report

## Commands

```
PARROT_SPIKE_FULL=1 python3 -m pytest packages/ai-parrot/tests/memory/dynamics/spikes/s3_attribution/test_s3_harness.py::test_corpus_evaluation_writes_report -q
```

## Corpus Provenance

- Total judged items: 50
- Real traces: 0
- Synthetic (labeled, declared): 50
- Judge: model:claude-sonnet-5

## Metrics per strategy x cap

| Strategy | Cap | Precision | False reinforcement | Missed attribution | Collision rate | Unknown labels |
|---|---|---|---|---|---|---|
| cited | 1 | 1.000 | 0.000 | 0.300 | 0.000 | 50 |
| cited | 3 | 1.000 | 0.000 | 0.300 | 0.000 | 50 |
| cited | 5 | 1.000 | 0.000 | 0.300 | 0.000 | 50 |
| cited | unbounded | 1.000 | 0.000 | 0.300 | 0.000 | 50 |
| overlap_tokens | 1 | 1.000 | 0.000 | 0.080 | 0.000 | 50 |
| overlap_tokens | 3 | 0.920 | 0.080 | 0.080 | 0.080 | 50 |
| overlap_tokens | 5 | 0.920 | 0.080 | 0.080 | 0.080 | 50 |
| overlap_tokens | unbounded | 0.920 | 0.080 | 0.080 | 0.080 | 50 |
| overlap_error_signature | 1 | 1.000 | 0.000 | 0.560 | 0.000 | 50 |
| overlap_error_signature | 3 | 1.000 | 0.000 | 0.560 | 0.000 | 50 |
| overlap_error_signature | 5 | 1.000 | 0.000 | 0.560 | 0.000 | 50 |
| overlap_error_signature | unbounded | 1.000 | 0.000 | 0.560 | 0.000 | 50 |
| recovery_linkage | 1 | 1.000 | 0.000 | 0.720 | 0.000 | 50 |
| recovery_linkage | 3 | 1.000 | 0.000 | 0.720 | 0.000 | 50 |
| recovery_linkage | 5 | 1.000 | 0.000 | 0.720 | 0.000 | 50 |
| recovery_linkage | unbounded | 1.000 | 0.000 | 0.720 | 0.000 | 50 |
| combined | 1 | 1.000 | 0.000 | 0.080 | 0.000 | 50 |
| combined | 3 | 0.920 | 0.080 | 0.080 | 0.080 | 50 |
| combined | 5 | 0.920 | 0.080 | 0.080 | 0.080 | 50 |
| combined | unbounded | 0.920 | 0.080 | 0.080 | 0.080 | 50 |

## Untrusted-vs-Trusted Outcome Sources (spec §2 Review Admission step 2)

### Untrusted (never sufficient alone)

| Source | Line ref | Why untrusted |
|---|---|---|
| EpisodicMemoryMixin._safe_record_ask outcome=EpisodeOutcome.SUCCESS, importance=3 | core/memory/episodic/mixin.py:477,479 | hard-coded for every conversation; no verification of the response's correctness |
| record_tool_episode success = getattr(tool_result, "success", True) | core/memory/episodic/store.py:260 | a tool_result without a `success` attribute silently defaults to success |
| record_tool_episode status = getattr(tool_result, "status", "success") | core/memory/episodic/store.py:262 | same default-to-success gap for the outcome status mapping |
| ToolInvocation.status default | core/memory/compaction/models.py:71 | ToolStatus.COMPLETED is the dataclass default, not an observed result |
| empty corrections list | spec §2 step 2 | absence of a correction is not proof of a correct first attempt |
| CoderReview.fix_commits reachability check alone (no memory ids) | core/flows/dev_loop/sdd_coder/engine.py:1476-1486 | proves a fix commit exists and is reachable, not that it applied any cited memory |
| exposure text-marker `"[coder-feedback:" in context` | core/flows/dev_loop/sdd_coder/engine.py:1488-1492 | binary with_feedback/without_feedback cohort flag, carries no memory ids |

### Proposed trusted-receipt adapters

| Source | Adapter |
|---|---|
| tool_runtime | runtime tool executor must supply an explicit success/failure with an error signature (when failed) and correction count observed across retries of the SAME tool call — never derived from getattr(...) defaults. |
| coder_engine | SddCoderEngine.record_review's fix-commit reachability check (engine.py:1476-1486) plus the review's relevant passed-check ids; a bare merge or zero fix_commits is NOT sufficient — completion must be paired with at least one relevant passed check. |

## Pass/Fail vs U3

- U3 (the target precision/false-reinforcement rubric) is an owner acceptance decision (spec §8 U3) — this gate reports the measured numbers above; PASS/FAIL is PENDING until the owner sets a target in amendment.md.

## Limitations

- No coder-review/coder-feedback ledger data or episodic-store dumps were available in this worktree to mine real traces (no sdd/state ledger sqlite plane, no episodic backend snapshot committed); the corpus is 100% synthetic (0 real, 50 synthetic), each item hand -constructed to exercise one grade-table branch (again/easy/hard/good/no_review) and one attribution edge case (cross-scope citation, prose-equivalent-but-unlinked recovery, token-overlap collision). This is a declared gate limitation per spec §3 G3 'Insufficient real trace coverage is a gate limitation' — numbers below characterize the candidate strategies' behavior on controlled scenarios, not empirical field precision.
- Overlap-token threshold (0.3) and candidate caps (1/3/5/unbounded) are experiment inputs per spec §2, not frozen defaults; see amendment.md for the proposed freeze.

See `amendment.md` in this directory for the proposed spec freeze.
