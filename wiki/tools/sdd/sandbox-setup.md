# SDD Sandbox — OS Setup

The SDD workflow uses [Bubblewrap](https://github.com/containers/bubblewrap)
(`bwrap`) for filesystem sandboxing inside worktrees. Claude Code's native
sandbox also uses `bwrap` internally, so the production setup requires
**nested user namespaces** to work.

## Prerequisites

- Linux kernel ≥ 6.5 (tested on 7.0)
- `bubblewrap` installed (`apt install bubblewrap`)
- AppArmor loaded (Ubuntu 24.04+, most Debian derivatives)

## Quick check

```bash
# Single bwrap — should print "works"
bwrap --ro-bind / / --dev /dev -- echo "works"

# Nested bwrap — must also print "nested works"
bwrap --ro-bind / / --dev /dev -- bwrap --ro-bind / / --dev /dev -- echo "nested works"
```

If single works but nested fails with `apply-seccomp: write
/proc/self/setgroups (nested userns is capability-restricted)`, follow
the steps below.

## Step 1 — Kernel sysctls

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
sudo sysctl -w kernel.unprivileged_userns_clone=1

# Persist across reboots
cat <<'EOF' | sudo tee /etc/sysctl.d/60-apparmor-namespace.conf
kernel.apparmor_restrict_unprivileged_userns=0
kernel.unprivileged_userns_clone=1
EOF
sudo sysctl --system
```

## Step 2 — AppArmor profile for bwrap

On Ubuntu 24.04+ / kernel ≥ 6.5, AppArmor mediates `userns` creation
per-profile. Even with the sysctls above, a nested `bwrap` is denied
unless the binary has an explicit `userns` permission.

```bash
sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
abi <abi/4.0>,
include <tunables/global>

profile bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
  include if exists <local/bwrap>
}
EOF
sudo apparmor_parser -r /etc/apparmor.d/bwrap
```

## Verify

```bash
# Must succeed after both steps
bwrap --ro-bind / / --dev /dev -- bwrap --ro-bind / / --dev /dev -- echo "nested works"
```

If it prints `nested works`, the SDD sandbox (and Claude Code's native
sandbox) will work. Restart any running `parrot sdd launch worker`
sessions to pick up the change.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No permissions to create new namespace` on nested bwrap | Step 2 (AppArmor profile) is missing |
| `apply-seccomp: write /proc/self/setgroups` | Both Step 1 and Step 2 needed |
| Single bwrap also fails | `apt install bubblewrap` and Step 1 |
| Works in terminal but not in `parrot sdd launch` | Restart the worker session after applying the fix |
