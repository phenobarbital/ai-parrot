# F003 — Counts exist only as free text
- 1301 of 4538 sdd/tasks/completed/*.md contain "<N> passed" in Completion Notes (e.g. "4293 passed", "12 passed") — unstructured, inconsistent scope (task vs full suite).
- scripts/sdd/select_tests.py --run delegates to dev_loop/test_scope/select.py:163 subprocess pytest; no junit/count parsing found.
