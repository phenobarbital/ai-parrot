# FEAT-603 AC14 — msgraph extra install-resolution evidence

Recorded: 2026-10-16T00:02:55Z
Ledger:   issue:13b20d91cb61
Base:     b6cc5f509af71c2f626f30b5f237755eb54b900f
uv:       uv 0.12.15 (x86_64-unknown-linux-gnu)

AC14 requires that `uv pip install -e "packages/ai-parrot[msgraph]"` resolving be
recorded under artifacts/logs/. Captured as a `--dry-run` resolve: it exercises the
full dependency resolution of the extra without mutating the shared .venv, which is
used concurrently by other sessions and worktrees (see .claude/rules/worktree-management.md).

The resolve also shows why an unguarded real install is not safe here: it would
DOWNGRADE pydantic, google-cloud-core, navigator-auth and referencing for every
session sharing this environment. The msgraph packages themselves (azure-identity,
msgraph-sdk, microsoft-kiota-authentication-azure) are already present and are not
in the would-install set — the extra is satisfied.

## Extra under test (packages/ai-parrot/pyproject.toml)

```toml
msgraph = [
    "azure-identity>=1.18.0",
    "msgraph-sdk>=1.8.0",
    "microsoft-kiota-authentication-azure>=1.2.0",
]
```

## Command

```
uv pip install --dry-run -e "packages/ai-parrot[msgraph]"
```

## Output

```
Resolved 244 packages in 2.23s
Would download 1 package
Would uninstall 6 packages
Would install 6 packages
 - ai-parrot==1.0.5 (from file:///home/jesuslara/proyectos/ai-parrot/packages/ai-parrot)
 + ai-parrot @ file:///home/jesuslara/proyectos/ai-parrot/packages/ai-parrot
 - google-cloud-core==2.7.0
 + google-cloud-core==2.4.3
 - navigator-auth==0.28.2
 + navigator-auth==0.28.7
 - pydantic==2.13.5
 + pydantic==2.12.5
 - pydantic-core==2.46.5
 + pydantic-core==2.41.5
 - referencing==0.37.0
 + referencing==0.36.2
exit=0
```
