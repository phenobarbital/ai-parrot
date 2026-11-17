---
kind: brief
slug: installer-uv-shadowing
key: installer-uv-shadowing
base_branch: main
source:
  type: text
  ref: installer-uv-shadowing
  url: null
jira_issue_key: null
ledger_issue: null
created: '2026-11-08'
---

# Brief: The `--global` installer's pinned uv shadows the user's own uv on PATH

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/installer-uv-shadowing/tasks/. -->

## Problem

Owner report (2026-11-08), verbatim apart from the home directory:

> ```
> $ uv self update
> error: Self-update is only available for uv binaries installed via the standalone installation scripts.
>
> The current executable is at `~/.parrot/bin/uv` but the standalone installer was used to install uv to
> `~/.local/bin`. Are multiple copies of uv installed?
> ```

On the reporting machine there are two identical copies (`uv 0.11.28`): `~/.parrot/bin/uv` and `~/.local/bin/uv`.
`which -a uv` lists `~/.parrot/bin/uv` first. In every shell, `uv` runs parrot's copy, so the user's
own uv cannot self-update, and a newer version the user installs stays hidden. Windows has the same problem: the
PowerShell installer prepends `$PARROT_HOME\bin` to the User PATH and puts `uv.exe` there.

Target behavior agreed with the owner (2026-11-08):

1. A bounded uv version range. If the uv already on the system is inside it, use that uv and download nothing.
2. If there is no uv, or it is outside the range, download parrot's pinned uv to a private directory that is
   **not** on PATH. The runtime calls uv by absolute path, so it never needed to be on PATH. The user's uv is never
   modified, moved or removed.
3. Existing installs migrate off the old layout, both when the installer is re-run and on `parrot self update`.

## Root cause

`install-parrot.sh --global` installs uv and uvx into `$PARROT_HOME/bin`. That is the same directory it prepends to
PATH for the `parrot` / `wikitoolkit` / `bookstore` shims:

- `scripts/install/install-parrot.sh:302`: `run "install uv into $PARROT_HOME/bin (your own uv is never touched)" install_uv_bins "$dl" "$target" "$PARROT_HOME/bin"`
- `scripts/install/install-parrot.sh:248`: `install_uv_bins()` copies both `uv` and `uvx`
- `scripts/install/install-parrot.sh:275`: the profile block writes `export PATH="%s/bin:$PATH"` (prepend)
- `scripts/install/install-parrot.sh:285`: `uv="$PARROT_HOME/bin/uv"`
- `scripts/install/install-parrot.sh:169`: the plan promises "A uv already on your PATH is never used or modified".
  The file is indeed untouched, but the copy in `bin` shadows it.
- PowerShell: `scripts/install/install-parrot.ps1:203` (`$uv = Join-Path $bin 'uv.exe'`), `:221` (place uv and uvx
  in `$bin`), `:167` (prepend `$bin` to the User PATH), `:126` (same plan sentence).

By design, the installer never looks for an existing uv: it always downloads the pinned `UV_VERSION="0.11.28"`
(`install-parrot.sh:48`, `install-parrot.ps1:116`). The Python runtime hard-codes the same location:

- `packages/ai-parrot/src/parrot/self_/components.py:164`: `bundled_uv()` returns `parrot_home()/"bin"/"uv"` and
  falls back to `shutil.which("uv")` without checking the version.
- `packages/ai-parrot/src/parrot/self_/doctor.py:67`: `_check_uv()` requires `bin/uv` and its version to equal
  `PINNED_UV_VERSION` (`doctor.py:28`) exactly.

The runtime only ever calls uv by absolute path (`components.py:229`, `components.py:249`). Putting uv in the PATH
directory had no purpose and causes the shadowing.

## Research findings

- **Blast radius of `bundled_uv`** (wiki `symbols blast`): `install_component` (`components.py:203`) and
  `update_runtime` (`components.py:239`), reached from `parrot self add` / `parrot self update`
  (`self_/cli.py:48-53`). Tests: `tests/self_/test_components.py`. `test_self_cli.py` mocks the components module
  and is unaffected.
- **`_check_uv` runs in every doctor scope**, including `--runtime-only`. The installer runs that scope after
  installing and rolls everything back on failure (`install-parrot.sh` `global_install`; `install-parrot.ps1:248-254`).
- **Version skew between installer and package.** The installers are served from `main` (`RAW_BASE`,
  `install-parrot.sh:51`, `install-parrot.ps1:118`) as soon as a PR merges. They install `ai-parrot` from PyPI, which
  keeps the old doctor until the next release, and `--version <X>` can pin any older release on purpose. An old
  doctor fails when `bin/uv` is missing, so an installer that only knows the new layout would roll back every install.
- **Uninstall.** `RUNTIME_DIRS` (`components.py:22`) = `("bin", "venv", "python")` decides what
  `uninstall_runtime` (`components.py:301`) removes; the new `libexec` directory must be added.
- **uvx.** No code under `packages/*/src` calls `uvx`, so the runtime does not need it.
- **Tests tied to the old layout.** `tests/docs/test_install_posix.py:306` asserts `bin/uv` exists, and `:161-162`
  assert the plan text (including "never used or modified"). `tests/docs/test_install_powershell.py:101`, `:110` and
  `:227` check the same text and pin.
- **The POSIX dry-run tests inherit the host PATH** (`_run_global`, `test_install_posix.py:63`, uses
  `{**os.environ}`). Once the installer looks for a system uv, their output would depend on the developer's own
  uv. The offline harness (`_run_offline_install`, `:247`) already builds its PATH with `_fake_bin` (`:172`), which
  has no uv.
- **Checksums.** `scripts/install/SHA256SUMS` is checked in CI (`.github/workflows/ci.yml:249-255`,
  `tests/docs/test_ci_install_wiring.py:31`) and must be regenerated after any installer change:
  `cd scripts/install && sha256sum install-parrot.sh install-parrot.ps1 > SHA256SUMS`.
- **Docs.** `docs/getting-started.md:136-176` describes the pinned uv download and the `~/.parrot/bin` writes.
- **Branches.** `main` and `dev` are identical for every file touched here. PR #2035, which accepted the `pageindex`
  component in both installers, is on both branches.
- **Related open ledger issues, out of scope:** `issue:6e31d9355edc` (the uv checksum is fetched from the same
  release instead of being pinned), `issue:3b2432011ac9` (FEAT-586 breadcrumb comment), `issue:73295db52ee4`
  (`--install-cli` ignored under `--global`), `issue:a786fec203e1` (PowerShell `-Python` default).

## Decisions

Owner answers (2026-11-08):

1. **Compatible range `>=0.11.28,<0.12`.** uv is still 0.x, where a minor bump may break. The pinned download stays
   at `0.11.28`. The single source of truth is the constants in the new `parrot/self_/uv.py`; both installers embed
   copies, and parity tests keep them equal.
2. **System uv in range:** the installer downloads nothing and records the uv's absolute path in
   `$PARROT_HOME/libexec/uv-path`, a one-line text file. The owner chose a recorded path over searching PATH at
   run time. A text file instead of a symlink, because Windows symlinks need privileges. Store the path absolute but
   **not** symlink-resolved: Homebrew's `bin/uv` points into a versioned Cellar directory that disappears on upgrade.
3. **No uv, or out of range:** download the pinned uv to `$PARROT_HOME/libexec/uv` (`uv.exe` on Windows), never to
   `bin`. `uvx` is no longer installed.
4. **The user's uv is never modified, moved or removed.** The installers only remove what an installer created.
5. **Run-time resolution order** (`resolve_uv`), where each candidate counts only if its version is in range:
   `libexec/uv`, then the recorded `uv-path`, then `uv` on PATH (excluding `$PARROT_HOME/bin` and `libexec`, for dev
   setups without the bootstrap), then the legacy `bin/uv` (old installs keep working). If none qualifies,
   `FileNotFoundError` naming every candidate checked and the fix, "re-run install-parrot --global".
6. **Migration:** both a re-run of the installer and `parrot self update` move an install off the legacy
   `bin/uv` / `bin/uvx` (owner choice). `parrot self doctor` stays read-only; a new informational check reports the
   legacy layout and the fix.

## Assumptions

Decided during research and not asked; each follows from the decisions above:

- **A. Version-skew guard.** After `uv pip install`, the installer checks whether the managed venv can
  `import parrot.self_.uv`. If it cannot (a release from before this fix, including `--version <old>`), the
  installer falls back to the legacy layout: it also places the pinned uv in `bin` so the old doctor passes, and
  warns that `parrot self update` will migrate the install once a release with the fix is installed.
- **B. The first `parrot self update` from a pre-fix release does not migrate.** It runs the old update code, so
  migration happens on the next `parrot self update` or on a re-run of the installer. The informational doctor check
  says so.
- **C. The installer removes the legacy `bin/uv` / `bin/uvx` only after the runtime doctor has passed.** The rollback
  trap can delete what a run created but cannot restore deleted files.
- **D. The PATH fallback also requires the range.** Before this fix it accepted any uv. A dev setup with an
  out-of-range uv now gets an error naming the version found and the range.
- **E. Windows gets the same logic.** Windows is not officially supported. Its tests are mostly static text checks;
  the pwsh harness is skipped when `pwsh` is absent.
- **F. Release promptly after the merge** (`/release`), so the legacy fallback from assumption A is needed only
  briefly.

## Fix plan

- **HOTFIX-installer-uv-shadowing-1.** Python runtime: new module `parrot/self_/uv.py` (range constants, version
  probe, `resolve_uv`, `record_system_uv`, `migrate_legacy_uv`). `bundled_uv()` delegates to it, `RUNTIME_DIRS` gains
  `libexec`, and `update_runtime()` migrates first. The doctor's `_check_uv` uses the range, and a new informational
  `_check_uv_layout` is added. Tests for all of it.
- **HOTFIX-installer-uv-shadowing-2** (depends on 1). POSIX installer: range constants plus a parity test, system-uv
  detection outside `$PARROT_HOME`, the `libexec` layout, the `uv-path` record, the version-skew guard and legacy
  cleanup. Plan text and tests, regenerated `SHA256SUMS`, and the POSIX part of `docs/getting-started.md`.
- **HOTFIX-installer-uv-shadowing-3** (depends on 2). The same changes for `install-parrot.ps1`, with its tests,
  `SHA256SUMS` and the Windows part of `docs/getting-started.md`. It runs after task 2 because both tasks rewrite
  `SHA256SUMS` and the same doc page.

## Validation commands

- `pytest packages/ai-parrot/tests/self_/test_uv.py -q`
- `pytest packages/ai-parrot/tests/self_/test_components.py -q`
- `pytest packages/ai-parrot/tests/self_/test_doctor.py -q`
- `pytest packages/ai-parrot/tests/self_/test_self_cli.py -q`
- `pytest packages/ai-parrot/tests/docs/test_install_posix.py -q`
- `pytest packages/ai-parrot/tests/docs/test_install_powershell.py -q`
- `pytest packages/ai-parrot/tests/docs/test_ci_install_wiring.py -q`
