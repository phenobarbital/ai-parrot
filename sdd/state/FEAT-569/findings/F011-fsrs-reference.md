---
id: F011
query_id: Q011
type: read
intent: Verify FSRS semantics against primary sources
executed_at: 2026-09-17T21:50:09.640444+00:00
parent_id: null
depth: 1
---

# F011 — Reference verification and limits of agent adaptation

## Summary

The official algorithm specifies 21 parameters and requires same-day successful reviews not to decrease stability. The brainstorm omits that clamp. The reference scheduler uses whole elapsed days, a positive stability floor, and bounded parameters. Fractional agent time is an adaptation requiring explicit parity boundaries. The documented optimizer consumes ReviewLog objects; an arbitrary CSV is not automatically its input. Agent outcome ratings measure usefulness proxies, not demonstrated human recall probabilities: calibration remains unproven.

## Citations

- URL: https://github.com/open-spaced-repetition/awesome-fsrs/wiki/The-Algorithm
  section: FSRS-6, formulas and default parameters (web lines 152-175)
  fact: 21 parameters; same-day successful stability multiplier is at least one.
- URL: https://raw.githubusercontent.com/open-spaced-repetition/py-fsrs/main/fsrs/scheduler.py
  symbol: Scheduler.get_card_retrievability / _short_term_stability / _validate_parameters
  lines: 178-218, 637-652
  fact: Whole elapsed days, bounded parameters, and same-day clamp.
- URL: https://github.com/open-spaced-repetition/py-fsrs
  section: Optimizer and license
  fact: MIT license; optional optimizer accepts ReviewLog objects.
- URL: https://raw.githubusercontent.com/open-spaced-repetition/py-fsrs/main/fsrs/review_log.py
  symbol: ReviewLog
  lines: 33-47
  fact: Integer card_id, rating, UTC review datetime and optional duration; export needs stable ID mapping.

## Notes

Accessed 2026-09-17; upstream main is mutable. Pin a release/commit and preserve license before vendoring. No parity suite, replay simulation, optimizer run or attribution experiment was performed.
