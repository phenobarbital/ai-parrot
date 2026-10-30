# Native Claude sandbox for SDD sessions (FEAT-768)

## What it protects

Bash and descendants only; the retained hook (guard → RTK → bounded shell, file-tool checks); trusted surfaces outside the sandbox; no secret confidentiality — spec non-goals.

## Supported launch paths

`scripts/sdd/launch_worker.sh` (PATH `claude`) and the dev-loop dispatcher (SDK-bundled CLI); direct `claude --agent` invocation is not a qualified native launch.

## Host prerequisites and qualified matrix

Linux, bwrap, socat, AppArmor profile for the seccomp helper (operator, root); table copied from `sdd/state/FEAT-768/native-sandbox-qualification.md`; a CLI/SDK version change requires re-qualification.

| Item | Value |
|---|---|
| OS | elementary OS 8.1 (Ubuntu 24.04 base) |
| `kernel.apparmor_restrict_unprivileged_userns` | 1 (unchanged; remediation is the profile below, not the sysctl) |
| AppArmor profile (operator-installed, root) | `/etc/apparmor.d/bwrap` — `profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }` (the documented Claude Code profile); loaded per `aa-status` |
| Bubblewrap / socat | 0.9.0 / 1.8.0.0 |
| `claude` on PATH (interactive launcher) | 2.1.314 (2.1.312 before an auto-update mid-session on an earlier run) |
| SDK-bundled CLI (`claude_agent_sdk/_bundled/claude`) | 2.1.301 (sdk 0.2.168), 2.1.310 (sdk 0.2.174) |
| Auth for both paths | `ANTHROPIC_API_KEY` (harness forces `CLAUDE_CODE_DISPATCH_AUTH=api-key` under its temporary `HOME`) |

## Network

Empty default; `sandbox_allowed_domains` / `--sandbox-allow-domain`; exact hosts only; HTTPS git/gh need `github.com` + `api.github.com`; no SSH in v1.

## Git inside a native session

Host sets upstream before launch; push with `git push origin <branch>`; config and hooks are read-only by design.

## Failures and rollback

Exit 1 / exit 2 meanings; never restart without protection; rollback = revert deploy.
