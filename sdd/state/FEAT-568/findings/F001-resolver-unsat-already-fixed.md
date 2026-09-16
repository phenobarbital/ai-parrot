# F001 — P0 resolver-unsat (async-notify/aarch64) is ALREADY FIXED

**Query**: Q002/Q003/Q004 (pyproject.toml, uv.lock, async-notify)
**Confidence**: high

## Evidence

- `pyproject.toml:77-86` (`[tool.uv]`):
  ```
  environments = [
      "sys_platform == 'linux' and platform_machine != 'aarch64'",
  ]
  ```
  with an explicit comment: *"aarch64 is excluded too: async-notify has never
  published a linux/aarch64 wheel (or an sdist) for any version, so that fork
  is permanently unresolvable while async-notify>=1.6.0 is required; all
  release/CI targets are x86_64 anyway."*
- `git log -L 77,86:pyproject.toml` shows this line was added in commit
  `6e10be590` ("fix: resolve dependency graph gaps blocking uv sync in CI"),
  dated **2026-09-15** (today) — i.e. it landed on `dev` after Copilot's
  investigation transcript was produced and is now included after this
  session's `git pull --ff-only origin dev`.
- Live verification: `gh run view 35037813473` (latest push to `dev`, HEAD
  `3ba22952c`) shows `Lint & Registry Check`, `Test ai-parrot-tools
  (3.11/3.12)`, `Test ai-parrot-loaders (3.11/3.12)`, and `Test navrules
  (rust=on/off)` **all green** — none of the jobs Copilot listed as blocked
  by the resolver (`No solution found ... split ...`) are failing anymore.

## Conclusion

Copilot's P0 finding was accurate **at the time it ran**, but has already
been remediated on `dev`. No action needed in this proposal beyond
confirming/verifying it stays fixed. Restating or "re-fixing" it would be
redundant and risks re-introducing an already-solved problem.
