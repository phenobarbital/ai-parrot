---
type: Concept
title: write_env_vars()
id: func:parrot.setup.scaffolding.write_env_vars
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Write environment variables to a ``.env`` file.
---

# write_env_vars

```python
def write_env_vars(env_vars: Dict[str, str], env_path: Path, environment: str='default') -> None
```

Write environment variables to a ``.env`` file.

If the file doesn't exist, it is first seeded from navconfig's
base template (with ENV, CONFIG_FILE, DEBUG, etc.) so that the
application can boot correctly. Credentials are then appended.

Args:
    env_vars: Mapping of ``VAR_NAME`` → value to write.
    env_path: Absolute (or relative) path to the target ``.env`` file.
    environment: Environment name (used when seeding a new file).
