"""Drop repeated event_id lines across the shared ledger files, keeping the first occurrence in order."""
import json, sys
from pathlib import Path

root = Path(sys.argv[1]); apply = "--apply" in sys.argv
files = sorted((root / "sdd/ledger/archive").glob("events-*.jsonl")) + [root / "sdd/ledger/events.jsonl"]
seen = set()
for f in files:
    data = f.read_bytes()
    out, dropped = [], 0
    for line in data.splitlines(keepends=True):
        if line.strip():
            eid = json.loads(line)["event_id"]
            if eid in seen:
                dropped += 1
                continue
            seen.add(eid)
        out.append(line)
    print(f.relative_to(root), "dropped", dropped, "kept", sum(1 for l in out if l.strip()))
    if apply and dropped:
        f.write_bytes(b"".join(out))
