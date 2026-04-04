---
description: Create a new feature from main branch
---

---
description: Start a new feature branch synchronized with main
---

1. Ask the user for the name of the feature (e.g., "user-auth") and optional jira ticket, if jira ticket is issued, use as prefix for branch name (e.g. "NAV-1234-user-auth").

// turbo
2. Confirm we are in the project root (where the Makefile exists). If not, `cd` to the repo root.


// turbo
3. Run `git checkout main`

// turbo
4. Run `git pull origin main`


6. Create and switch to the new feature branch.

// turbo
7. Run `git checkout -b feature/[feature-name]`

8. If any step fails:
   - Paste the error output.
   - Diagnose the most likely cause.
   - Propose the smallest fix.
   - Re-run only the failed step (and any dependent steps if needed).