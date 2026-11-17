# Auto-mode rewrites: shell prefix qualification

Auto mode reviews Bash input before `PreToolUse` hooks run.  A hook response with `updatedInput` is consequently
refused once and must be resent verbatim.  This replay used the original Bash calls only (not their resends), calling
`hook_response` with the transcript working directory.  The scratch replay script is intentionally not committed.

| Transcript | Backend before prefix | Before rewrites | After prefix-policy rewrites |
|---|---|---:|---:|
| `135df69e-0d8f-4032-8edc-9d61a6757d69` (FEAT-860 legacy) | `bubblewrap` | 90 / 90 | 0 ordinary calls |
| `03ebac40` (FEAT-793 native) | `claude-native` | 40 / 40 | 0 ordinary calls |

The legacy baseline rewrote every one of its 90 original calls because the hook constructed a Bubblewrap command
after review.  The native baseline was the 40 original commands recorded in the prior deterministic replay.  With a
valid generated policy and its token, the hook leaves legacy Bubblewrap commands unchanged and skips RTK because both
transformations are now performed by the prefix.  The same token suppresses duplicate RTK handling for the native
replay; native launches do not themselves depend on prefix invocation, per the task-3 probe.

Remaining rewrites are intentional and are not ordinary prefix work: a scope-guard rewrite or verdict, a command
with an explicit `timeout` or `run_in_background`, and any session not started by the launcher (no valid policy
token).  A malformed, absent, or unsafe policy fails closed in the prefix with exit status 2; it never restores the
old unguarded path.
