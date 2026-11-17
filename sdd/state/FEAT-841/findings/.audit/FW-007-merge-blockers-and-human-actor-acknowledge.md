---
id: FW-007
query_id: Q001
type: wiki_page
intent: "Follow-up: the existing ledger merge-blocker service and the human-only acknowledge rule — precedent for a human-signed release decision."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 800
parent_id: FW-001
depth: 2
---

# FW-007 — LedgerService.merge_blockers scopes blocking to issues discovered by the feature, and LedgerService.acknowledge refuses any actor not prefixed human: — the only "human signature" in the ledger is an actor-prefix check

## Summary

`LedgerService.merge_blockers(feature_id)` returns open/claimed, unacknowledged, **critical** issues whose `discovered_from` is `spec:<FEAT>`, `task:<TASK>` or `review:<TASK>` of that feature's per-spec index; `wikitoolkit ledger blockers` (`cli.py:ledger_blockers`) exits 1 when any exist. `LedgerService.acknowledge(issue_id, reason, actor)` appends `issue.acknowledged` only if `actor.startswith("human:")`, else logs and returns False ("acknowledging a critical is a human decision (Module 8)"). Acceptance test `test_merge_blockers_scoped_to_current_feature_and_resolved_by_human_acknowledgement` pins both. This is the exact precedent for an `escrow.approved` that must be produced by a non-worker actor and an `escrow.overridden` that must be `human:` — but note the check is a string prefix, trivially spoofable by any process that can append to the journal; "signed" in the request will need a stronger binding (e.g. verdict bound to `head_sha` + actor identity from `wiki/actor.py`/`identity.py`) if spoofing by the worker is a threat.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  lines: 465-494
  symbol: `LedgerService.merge_blockers`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.merge_blockers
  score: 0.76
  excerpt: |
    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]:
        task_ids = await asyncio.to_thread(self._feature_task_ids, feature_id)
        valid_sources = {f"spec:{feature_id}"}
        valid_sources.update(f"task:{tid}" for tid in task_ids)
        valid_sources.update(f"review:{tid}" for tid in task_ids)
        await self._sync_best_effort()
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  lines: 393-410
  symbol: `LedgerService.acknowledge`
  excerpt: |
    async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool:
        """Record ``issue.acknowledged``. Rejects non-human actors."""
        if not actor.startswith("human:"):
            logger.warning("Refusing issue.acknowledged from non-human actor %r", actor)
            return False
        event = LedgerEvent(kind="issue.acknowledged", subject=issue_id, actor=actor,
                            payload={"acknowledged_by": actor, "reason": reason})
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 1-1
  symbol: `ledger_blockers`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/wiki/cli.py#ledger_blockers
  score: 1.00
  excerpt: |
    ledger_blockers — List unacknowledged critical issues blocking a feature merge.
- path: `tests/sdd/test_ledger_lifecycle_acceptance.py`
  lines: 1-1
  symbol: `TestLedgerLifecycleAcceptance.test_merge_blockers_scoped_to_current_feature_and_resolved_by_human_acknowledgement`
  wiki_page_id: sym:tests/sdd/test_ledger_lifecycle_acceptance.py#TestLedgerLifecycleAcceptance.test_merge_blockers_scoped_to_current_feature_and_resolved_by_human_acknowledgement
  score: 0.79

## Notes

`sdd-worker.md:709` already tells the worker that a deferred `critical` finding "blocks /sdd-done" — so the worker can *block* itself today (file a critical) but cannot *release* itself (acknowledge is human-only). Escrow inverts the default: nothing is released until an external APPROVED exists. [cross-lane: type=grep, intent=codebase lane Q023 should report what `wiki/actor.py` / `identity.py` provide as actor identity (machine id, user) to strengthen the "signed" claim.]
