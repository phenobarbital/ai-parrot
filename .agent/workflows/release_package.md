---
description: Release Package
---

---
description: Automated Release Workflow
---

You have access to a release automation script located at `scripts/release.py`.

**Trigger:**
When the user asks to "bump version", "release [patch/minor/major]", or "increase version".

**Context:**
- **Source of Truth:** `{package}/version.py` (Python)
- **Follower:** `yaml-rs/Cargo.toml` (Rust)
- The script handles the synchronization automatically.

**Procedure:**
1.  **Analyze the Request:** Determine if the user wants a `patch` (default), `minor`, or `major` bump.
//turbo
2.  **Execute:** Run the python script.
//turbo
    * Command: `python scripts/release.py [patch|minor|major]`
3.  **Verify:** After execution, confirm the git commit was created.

**Constraints:**
- Do not manually edit versions; rely on the script to keep Python and Rust in sync.
- If the Rust package moves, update the `CARGO_TOML_PATH` constant in `scripts/release.py`.