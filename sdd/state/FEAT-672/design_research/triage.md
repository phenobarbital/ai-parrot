# Design research triage — github-reviewer-local-repo-wiki

Model: `gpt-5.6-luna` (codex-cli 0.162.1) · 12 suggestions · all `affected_paths`
passed containment + existence checks and each claim was spot-checked in the source.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Make external storage an explicit build input (architecture) | CONFIRM | Verified: `build` calls `save_project_config(root, base_config)` unconditionally (`cli.py:1724`) and may write an env overlay, so `--path` alone cannot place the plane outside the clone. Owner chose the additive `--storage-dir` flag over seeding a config into the clone. | §2 Overview, §3 M1, §5 AC-1 |
| S2 | Lock shared across processes, not just coroutines (architecture) | CONFIRM | Correct: the deployment is gunicorn with multiple workers, so an `asyncio.Lock` serializes only one process. Refines (does not reverse) the owner's per-repo serialization decision. | §3 M2, §7 Risks |
| S3 | Validate the cached clone's remote and branch (risk) | CONFIRM | Verified: `clone_repo` treats any dir with `.git` as the cache (`gittoolkit.py:1619`) and `pull_repo` runs `pull --ff-only` without checkout or remote verification (`:1671-1673`). | §3 M2, §5 AC-4 |
| S4 | Do not let incidental `gh` break private auth (risk) | CONFIRM | Verified: `if private and self._gh_available()` picks `gh repo clone` (`gittoolkit.py:1627-1631`), which never sees the PAT / App token the toolkit holds. | §3 M4, §7 Risks |
| S5 | Cancellable subprocess timeouts (risk) | CONFIRM | Verified: `_run_subprocess` awaits `communicate()` with no timeout (`gittoolkit.py:1576-1588`); `asyncio.wait_for` alone would orphan the child. | §3 M3, §3 M4, §5 AC-6 |
| S6 | Preserve a last-known-good plane (architecture) | CONFIRM (reduced) | Real: the build writes into the live plane under the writer lock, so a crash can leave it partially ingested. Adopted as a last-good marker + documented risk; a full generation-swap publish is deferred to §8 Q1 rather than built now. | §3 M3, §7 Risks, §8 Q1 |
| S7 | Treat the full wiki surface as a mutation capability (risk) | CONFIRM (owner variant) | Independent second flag on a decision the owner had already made deliberately. Owner kept the full tool surface but turned on `confine_sources=True`, removing the path-sensitive half. | §2 Overview, §3 M5, §7 Risks |
| S8 | Canonicalize repository identity (api) | CONFIRM | Verified: `review_pull_request` reads `payload.get("repository") or self.repository` (`github_reviewer.py:809`), so a manual payload could select another cache entry. | §3 M5, §5 AC-7 |
| S9 | Resolve the dev-vs-main branch contract (api) | CONFIRM | Verified: `_build_git_toolkit` reads `GIT_DEFAULT_BRANCH` with fallback `"main"` (`github_reviewer.py:601`) and `GitToolkit.__init__` defaults `default_branch="main"`. The clone must track the reviewed repo's own default branch, not that fallback. | §3 M2, §3 M5, §5 AC-3 |
| S10 | Bound and label injected context (api) | CONFIRM | Correct and already the brainstorm's sharpest edge; makes the token budget and the base-branch label acceptance criteria rather than prose. | §3 M6, §5 AC-8 |
| S11 | Deterministic degradation and lifecycle tests (testing) | CONFIRM | The listed gaps (reused clone, private auth, concurrent events, build timeout, partial plane, warm-up cancellation) are exactly the paths this feature adds. | §4 Unit + Integration |
| S12 | Own and cancel warm-up tasks (architecture) | CONFIRM | Verified: `post_configure` (`github_reviewer.py:503`) owns no background task today; an un-awaited build task would orphan subprocesses on reload. | §3 M5, §5 AC-5 |

Summary: **12** confirmed · **0** rejected · **0** escalated.
Two confirmations (S1, S7) were routed through the owner because they touched
decisions already resolved in the brainstorm; both were answered before drafting.
