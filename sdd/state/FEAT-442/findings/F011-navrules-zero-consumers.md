# F011 — navrules still has zero consumers
**Query**: G005 · **Confidence**: high

`grep -rln navrules packages --include=*.py` excluding its own package → empty. Claim holds; entitlements admission remains its first real consumer.
