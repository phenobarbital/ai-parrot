# Worktree base synchronization

`parrot sdd worktree sync-base` brings a base branch update, or selected base
commits, into exactly one registered linked worktree. It never rebases or
pushes.

## Host usage

Run full-base synchronization from the trusted host, before a worker starts:

```bash
parrot sdd worktree sync-base FEAT-806
parrot sdd worktree sync-base FEAT-806 --ff-only
parrot sdd worktree sync-base FEAT-806 --dry-run --json
```

The host fetches the selected base and then merges it, or fast-forwards with
`--ff-only`. A host cherry-pick is also supported when explicitly requested.

## Sandbox usage

Inside a worker sandbox, only a selected base fix is allowed:

```bash
parrot sdd worktree sync-base FEAT-806 --cherry-pick <sha>
```

The sandbox retrieves commit patches through `gh`, applies one ordered batch
with `git am -3`, and adds `(cherry picked from commit <sha>)` to each applied
commit. Before downloading a patch it asks GitHub's compare API whether the
commit is an ancestor of (or equal to) `<base>`; any other answer is refused
with exit code 5, the same guarantee as the host's `merge-base --is-ancestor`
check. It never runs `git fetch`, `git pull`, `git push`, or `git rebase`.
Full-base synchronization is a host operation.

## Host setup before sandbox launch

Provision push protection on the trusted host before launching a sandbox. Never
perform these writes from a sandbox. First inspect the primary and every linked
worktree for common `core.worktree` and `core.bare` values:

```bash
git worktree list --porcelain
git config --show-origin --get-all core.worktree
git config --show-origin --get-all core.bare
```

If either setting is common, preserve its effective value for the primary and
each linked worktree with worktree-local configuration before enabling
`extensions.worktreeConfig`; do not discard or change that semantic during the
migration. Then enable the extension in common configuration and set only the
target worktree's push URL:

```bash
git config extensions.worktreeConfig true
git -C <target-worktree> config --worktree remote.origin.pushurl no_push
git -C <target-worktree> config --get-all remote.origin.pushurl
```

The final command must report exactly `no_push`. Do not change the common
`remote.origin.pushurl`, and do not alter sibling worktrees' effective
configuration. Missing or inconsistent protection returns exit code 5 with
host setup instructions.

## Safety, failure, and recovery

The command rejects an unresolved, ambiguous, primary, orphaned, or
Git-top-level-mismatched target before it fetches, writes configuration, or
integrates. A normal run also refuses dirty worktrees and foreign live
processes. There is no live-process override.

`--dry-run` changes nothing and skips dirty and live-process guards, but a
sandbox dry run still validates push protection. It reports the commits that
would enter without integrating them.

Each sandbox cherry-pick request is one atomic batch. A conflict triggers the
matching abort operation and is reported as a conflict only after HEAD, index,
and working tree restoration are verified. If abort or restoration fails, the
result is an error with the actual state and recovery guidance; do not use a
destructive reset as a substitute. No mode pushes or rebases.

## Exit codes

| Code | Status | Meaning |
| --- | --- | --- |
| 0 | `synced` or `up-to-date` | Sync succeeded, or no commit needed integration. |
| 2 | `refused` | Target is unresolved, ambiguous, primary, orphaned, or invalid. |
| 3 | `refused` | Worktree has uncommitted changes. |
| 4 | `refused` | A foreign live process is using the worktree. |
| 5 | `error` | Transport or sandbox push-protection prerequisite is unavailable. |
| 6 | `conflict` or `error` | Integration conflicted after verified restoration, or restoration failed. |

Exit code 2 is also argparse's usage-error code. A usage error prints no
`--json` body, so a missing or unparsable body with exit 2 means the command
line was rejected, not the target. A missing `git` or `gh` binary is a
`refused` result with exit 5.

With `--json`, `status` distinguishes a verified conflict from an unrecovered
error even when both originate during integration. The JSON result also records
the pre- and post-sync SHAs, selected transport and mode, commits, and message.

## Advisory at startup

The host launcher and `/sdd-start` run the full-base dry-run as an advisory
before a worker is live. They display its result and continue; no-upstream
launches are exempt and skipped checks are informational. If the advisory says
the base is ahead, have the host operator run `parrot sdd worktree sync-base
<FEAT-ID>` before starting the worker. Do not run this advisory inside the
sandbox.
