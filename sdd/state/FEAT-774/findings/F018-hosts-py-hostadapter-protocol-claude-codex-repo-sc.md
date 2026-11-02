---
id: F018
query_id: Q031
type: read
intent: "Host adapters module"
executed_at: 2026-10-30T15:23:31Z
duration_ms: 0
parent_id: null
depth: 0
merged_from: [FC-018]
---

# F018 — hosts.py: HostAdapter protocol; Claude/Codex repo-scoped, Google user-global; detect_hosts()

## Summary

Full read confirms FC-008: `HostAdapter` protocol (`config_paths`, `is_repo_scoped`, `inspect`, `reconcile`, `sync_approvals`); the three adapters delegate entry writing to the wiki installers (`parrot.knowledge.wiki.claude_code.installer.reconcile_toolkit_entries`, `codex.installer.reconcile_toolkit_tables`, `google.installer.reconcile_toolkit_entries`). `detect_hosts(root)` returns hosts whose config exists. Entries are named `parrot-<name>`.

## Citations

- path: `packages/ai-parrot/src/parrot/mcp/hosts.py`
  lines: 37-56, 95-98, 167-170, 228-245
  symbol: `HostAdapter / reconcile / get_adapter / detect_hosts`
  excerpt: |
    class HostAdapter(Protocol):
        def config_paths(self, root: Path) -> tuple[Path, ...]: ...
        def reconcile(self, root: Path) -> tuple[list[str], list[str]]: ...
    def get_adapter(kind: HostKind) -> HostAdapter:
    def detect_hosts(root: Path) -> list[HostKind]:

## Notes

Installer asset function `toolkit_mcp_json_entry(root, name, section)` (claude_code/assets.py) builds the entry — see FC-031 spec excerpt.
