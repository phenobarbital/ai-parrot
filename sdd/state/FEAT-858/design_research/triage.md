# Design research triage

Reviewer: /root/design_review (inherited session model). All affected paths were resolved inside the repository, checked for existence and evidence re-read.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Await scope initialization explicitly (architecture) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 recovery; M4 |
| S2 | Coordinate recovery and imports with operation locks (risk) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 lock protocol; M4 |
| S3 | Check expected revision against returned read (api) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 guard; M1 |
| S4 | Decorate only against matching generation (risk) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 evidence; M1 |
| S5 | Handle empty filters and request-local notes (api) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 origin; M3 |
| S6 | Clip and validate against the stored revision (risk) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §2 origin; M3 |
| S7 | Pin gold fixtures and specify deterministic tuning (testing) | CONFIRM | Verified source supports the correction; preserves accepted intent. | §4 host evaluation; M6 |

7 confirmed; 0 rejected; 0 escalated.
