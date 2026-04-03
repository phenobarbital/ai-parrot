---
description: A fresh startup for work
---

---
description: Startup flow — sync repo then install + start dev environment
---

// turbo
1. Confirm we are in the project root (where the Makefile exists). If not, `cd` to the repo root.

2. Check for local changes before pulling:
   - Run `git status --porcelain`.
   - If output is non-empty, STOP and ask whether to commit/stash/discard before continuing.

// turbo
3. Run `git fetch --all`.

// turbo
4. Run `git pull`.

5. Verify if virtualenv is enabled.

//turbo
6. Run `make install`.

//turbo
7. Run `make develop`.
   - If this starts a long-running dev server, leave it running and report:
     - the command output
     - the local URL/port (if shown)
     - any next-step instructions printed by the dev server

8. If any step fails:
   - Paste the error output.
   - Diagnose the most likely cause.
   - Propose the smallest fix.
   - Re-run only the failed step (and any dependent steps if needed).