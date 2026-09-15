# O365 delta pre-merge review

Reviewed delta HEAD ee3b06d06 against dev c9294e127 and contracts fixes 7c61386ba. Recommendation: request changes. No merge or production edits performed.

## P1: Retraction failure reports are ignored

`packages/ai-parrot-tools/src/parrot_tools/contracts/jobs.py:335-338` awaits graph_loader.retract but never checks its returned GraphPublicationReport. The concrete loader catches graph failures and returns errors with published=False. Consequently the job marks the source item deleted and commits the new cursor despite the failed withdrawal. The new rescan then skips that deleted source item on subsequent runs. Check report success and retain retryable source/cursor state. The guarantee in `docs/knowledge/contracts.md:310` is currently false for this failure mode.

Reproduction: artifacts/o365_premerge_probes.py and artifacts/logs/o365-premerge-probes.log. A returned failure report produces errors=[], deleted=True and an advanced cursor.

## P1: Rescan reconciliation can retract a concurrently refreshed contract

`packages/ai-parrot-tools/src/parrot_tools/contracts/jobs.py:510-527` compares last_seen_at from the list_source_items snapshot, then removes the contract without a lock or conditional catalog mutation. A concurrent run can refresh the item after that snapshot; this run still retracts the live contract and advances its cursor. Serialize conflicting ingestion/reconciliation and make the live-reference/last-seen checks atomic with retraction. Cross-source references must be protected as well.

Reproduction: artifacts/o365_premerge_probes.py schedules the refresh after list_source_items reads its rows and before it returns. Output records the newer observation but active=False and the contract in reconciled.

## P1: Parentless root item rejects a valid folder-scoped feed

`packages/ai-parrot-tools/src/parrot_tools/o365/delta.py:609-623` discards the root facet. Folder membership classification at 675-696 then labels a parentless drive-root item UNKNOWN, and strict scope checks reject the entire feed (onedrive.py:701-708; corresponding SharePoint path shares the classifier). Preserve root identity, classify a known drive root relative to the requested scope, and retain refusal for genuinely unresolved items.

Reproduction: the real OneDrive tool with a fake Graph response containing a root-facet parentless folder plus a child directly under folder-x returns status=error for folder_id=folder-x. Observed error: "Folder scope 'folder-x' could not be applied to 1 of 2 item(s)"; the root-probe log is not retained. Microsoft documents that delta responses can include parent hierarchy items and omit parent paths: https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0 . No live Graph service was exercised.

## Integration and validation

Neither delta HEAD nor current dev includes 7c61386ba. The read-only three-way merge preview against that fix commit has no textual conflict markers. Shared changed files are contracts/jobs.py, contracts/catalog_postgres.py, and docs/knowledge/contracts.md. Include the fix commit in the integration and test the combined result; textual compatibility alone does not establish behavioral compatibility.

Existing contracts tools and O365 protocol/tool suites: 377 passed, 5 live tests skipped. Logs: artifacts/logs/o365-premerge-tests.log. Three additional focused probes reproduce the above issues. An independent read-only reviewer cross-checked O365 protocol and scope behavior. No new database container was started for this review.
