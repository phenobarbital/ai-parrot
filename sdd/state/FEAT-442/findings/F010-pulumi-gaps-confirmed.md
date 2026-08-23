# F010 — Pulumi gaps confirmed verbatim
**Query**: G004 · **Confidence**: high

- `parrot_tools/pulumi/executor.py:469, :512`: docstrings literally say `config_values: Configuration values to set (not yet implemented).` — still discarded.
- `toolkit.py:124,184` pass `config_values=config` down (callers ready, executor drops it).
- `config.py:26,47`: `state_backend` declared (default "local"), never used; no `pulumi login` / `_ensure_login` anywhere.
