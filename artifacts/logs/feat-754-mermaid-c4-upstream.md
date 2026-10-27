# FEAT-754 Mermaid C4 upstream parse evidence

## Environment

- Date: 2026-10-27
- Command attempted: `npx --offline @mermaid-js/mermaid-cli --version`
- Result: unavailable. npm returned `ENOTCACHED`; no Mermaid CLI package or
  version was present in the external Node environment. A global-package scan
  found only `@google/gemini-cli` and `nsolid-cli`.

## Verification status

The required upstream parse check could not run in this task worktree because
the external Mermaid CLI was unavailable and the shared npm cache is read-only.
No project dependency was added. The canonical macro examples therefore remain
unverified upstream in this environment and must be run in a provisioned
external Mermaid environment before M2 acceptance.
