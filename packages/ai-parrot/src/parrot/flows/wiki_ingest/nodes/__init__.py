"""Pipeline nodes for the Fireflies → Obsidian LLM-Wiki ingest flow.

Each contract §-section maps to one node module here (spec §3.1),
orchestrated by :mod:`~parrot.flows.wiki_ingest.runner` per the §27
ordered pipeline:

- :mod:`.fetch_gate` — §2/§14 dedup gate (Module 2)
- :mod:`.raw_bundle` — §13/§14 pairing, hashing, immutable moves (Module 3)
- :mod:`.classify` — §15 summary-first classification (Module 7)
- :mod:`.meeting_page` — §17 canonical meeting source page (Module 8)
- :mod:`.project_reconcile` — §16/§19 project reconcile + new-project (Module 9)
- :mod:`.entities` / :mod:`.concepts` — §20/§21 match-before-create (Module 10)
- :mod:`.contradictions` — §22 contradiction protocol (Module 11)
- :mod:`.daily` / :mod:`.indexes` / :mod:`.review_queue` / :mod:`.log` —
  §23/§24/§18/§26/§33 connective tissue (Module 12)
- :mod:`.query` — §28 query workflow (Module 13)
- ``.health`` / ``.lint`` / ``.archive`` / ``.graph_report`` — §29-§32
  workflows (Module 14, added by a later task)
- ``.email`` — retained-but-disabled digests (Module 15, added by a
  later task)
"""

from __future__ import annotations
