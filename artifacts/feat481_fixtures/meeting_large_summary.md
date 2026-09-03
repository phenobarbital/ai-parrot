# FieldSync / Verizon Launch — Weekly Project Sync

**Date:** 2026-08-27 · **Duration:** 71 minutes · **Recurrence:** weekly

## Overview

The team convened for the standing FieldSync weekly project sync, five weeks out
from the October 1 Verizon launch date. Attendance was full except for Priya
Raghavan (PTO), whose Workday integration items were covered by Daniel Okoye.
The agenda covered six standing areas — Epson field testing, the form builder
access regression, the phased UX rollout, training material readiness, the
Workday integration test plan, and launch-readiness gating — plus two ad hoc
topics raised at the top of the call (a support staffing gap and an unresolved
question about who signs off on the retail-store pilot checklist).

## Epson field testing

Marcus Bell reported that the Epson TM-M30III field trial completed its second
week across the four pilot districts (Dallas North, Dallas South, Fort Worth,
and Arlington). Of the 48 devices deployed, 44 are reporting telemetry on the
expected cadence. Four devices in Arlington have not checked in since August
22. Marcus's working theory is that the Arlington store cluster is behind a
captive-portal WiFi configuration that silently drops the device's outbound
heartbeat, not a firmware fault — the same pattern the team saw in the Plano
pilot last quarter. He has asked the Arlington district manager for a network
capture but has not received one, and flagged that without it he cannot confirm
the theory. Lauren Chen pushed back on treating this as low severity: if the
same captive-portal pattern exists in any Verizon store, the launch would ship
with a known silent-failure mode. Marcus agreed to escalate and committed to
having either a network capture or an on-site visit scheduled by September 3.

Print reliability numbers were better than the previous week: 2,140 print jobs
issued, 2,118 confirmed complete, for a 98.97% success rate against the 99.5%
launch bar. The 22 failures cluster into two causes — 15 were paper-out events
that the app currently reports as a generic print failure rather than a
distinguishable "consumable" state, and 7 were genuine timeouts. Marcus argued
the paper-out events should not count against the reliability bar because they
are an operator condition, not a system fault; Lauren countered that until the
app distinguishes them the metric cannot be trusted either way. No decision was
recorded on whether to re-baseline the metric. The team agreed the app needs a
distinct paper-out state before launch, and Marcus will size that work.

## Form builder access regression

Sofia Marquez walked through the form builder access issue first reported on
August 19. The regression is that users with the `field_supervisor` role can
open the form builder but receive a 403 on save, so work is lost with no
warning. Root cause is confirmed: the July permissions refactor moved the
builder's save endpoint behind a new `forms:write` scope, and the supervisor
role template was never updated to include it. The role template lives in the
provisioning service, not in FieldSync, which is why the FieldSync-side tests
did not catch it.

Two fixes were discussed. The narrow fix is to add `forms:write` to the
supervisor role template, which Daniel estimated at under a day including the
provisioning deploy. The broader fix is to make the builder check the scope on
open rather than on save, so an unauthorized user sees a read-only view instead
of losing work — roughly a three-day change touching the builder's permission
gate and its autosave path. The team decided to do both: ship the narrow fix
immediately so supervisors are unblocked, and schedule the broader fix for the
sprint after launch rather than risk a builder change during the freeze. Sofia
noted that 31 supervisors across the pilot districts have hit this at least
once, and that at least four have reported losing more than twenty minutes of
work. Customer support has not been told there is a known workaround (save a
draft under a supervisor's manager account), and Sofia flagged this as a
communication gap she will close.

## Phased UX rollout

Lauren Chen presented the phased UX plan. Phase 1 (navigation restructure and
the new task list) is behind a feature flag at 20% of pilot users as of August
25. Early signal is positive: median time-to-first-task dropped from 41 seconds
to 27, and the task-abandonment rate is flat. Phase 2 (the redesigned form
runner) is code complete but blocked on the accessibility audit, which has not
been scheduled because the vendor's August capacity was already booked. Lauren
asked whether Phase 2 could ship behind the flag without the audit and roll the
audit into September; Daniel objected on the grounds that the Verizon MSA has an
accessibility conformance clause and shipping unaudited UI into a Verizon-facing
surface creates contractual exposure. The team did not resolve this. Lauren will
get a firm vendor date by September 2 and, if the date lands after September 15,
the group will decide whether Phase 2 is cut from the launch scope entirely.

Phase 3 (offline mode indicators) has not started. Lauren was explicit that
Phase 3 is not a launch commitment and asked that it be removed from the launch
tracker so it stops appearing as at-risk in the executive summary. No one
objected, but the tracker was not updated during the call.

## Training material readiness

Amara Osei reported that 6 of the 9 training modules are final, one is in
review, and two have not started. The two that have not started both cover the
Phase 2 form runner, so they cannot be written until the Phase 2 scope decision
above is made — Amara flagged this as a hard dependency and noted that if the
Phase 2 decision slips past September 5, the training modules will not be ready
for the September 22 train-the-trainer session, which would in turn put the
October 1 launch date at risk. She asked for the Phase 2 decision to be treated
as a launch blocker rather than a UX decision. There was general agreement in
the room but no formal owner was assigned to make the call.

The train-the-trainer session is confirmed for September 22 in the Dallas
office with 14 registered district trainers. Amara still needs a decision on
whether Verizon's own field trainers attend that session or a separate one; she
has asked the Verizon program manager twice without an answer. Marcus offered
to raise it through the Verizon technical channel as a backup path.

## Workday integration testing

Daniel Okoye covered Priya's items. The Workday integration test plan has 34
scenarios; 22 have passed in the sandbox, 6 have failed, and 6 are blocked on
sandbox data that Workday has not provisioned. Of the 6 failures, 5 are the same
underlying issue — the worker-position effective-dating logic returns the
position as of the sync timestamp rather than as of the assignment date, so any
worker who changed position within the sync window is assigned to the wrong
district. This is a correctness bug with real operational impact: a supervisor
would see the wrong roster. Daniel has a fix drafted but wants Priya to review
it because the effective-dating semantics were her design. The sixth failure is
a flaky timeout that Daniel believes is a sandbox artifact rather than a product
issue, though he has not proven that.

The 6 blocked scenarios all need Workday to provision test workers with
multi-position assignments. The request has been open for eleven days. Daniel
escalated it once through the integration partner channel and has not had a
response. He asked whether the team should plan for launching without those six
scenarios verified. Lauren said that should be an explicit, documented risk
acceptance rather than a silent gap, and asked that it be written up. Nobody was
named as the owner of that write-up.

## Launch readiness and gating

The group reviewed the launch gate checklist. Of the 18 gate criteria, 11 are
green, 4 are amber, and 3 are red. The three red criteria are: the accessibility
audit (Phase 2), the Workday multi-position scenarios, and the print reliability
bar (98.97% against a 99.5% target). The four amber criteria are training
completion, the Arlington device telemetry gap, support staffing, and the retail
pilot checklist sign-off.

On support staffing: the launch support model assumes two dedicated tier-2
engineers for the first three weeks. Only one has been identified. Sofia raised
that the second seat has been "being worked on" for a month with no name
attached, and that if it is not filled by September 10 the team should plan for
a single-engineer rotation with an explicit longer response-time SLA rather than
pretending the second seat exists. There was no pushback and no decision.

On the retail-store pilot checklist: nobody in the room could say who owns
sign-off. Marcus believes it is the Verizon retail operations lead; Lauren
believes FieldSync's own program office signs off and Verizon counter-signs.
This has been ambiguous for three weeks. The group agreed the ambiguity itself
is a launch risk and that it needs to be settled, but the action was not
assigned to anyone before the call ended.

## Closing

The meeting ran eleven minutes over and the last agenda item (the post-launch
support handover plan) was deferred to next week. Lauren asked that the Phase 2
scope decision, the support staffing decision, and the checklist sign-off
question all be resolved before the next sync rather than re-discussed in it.

## Appendix A — action items raised during the call

- Marcus Bell: obtain an Arlington network capture or schedule an on-site visit
  by September 3, and report back whether the captive-portal theory holds.
- Marcus Bell: size the work to give the app a distinct paper-out / consumable
  state so print reliability can be measured against genuine system faults.
- Sofia Marquez: ship the narrow `forms:write` scope fix to the supervisor role
  template and confirm the provisioning deploy landed in all pilot districts.
- Sofia Marquez: brief customer support on the existing draft-under-manager
  workaround and correct the gap that left support unaware of it.
- Lauren Chen: get a firm accessibility-audit date from the vendor by
  September 2 and bring it back to the group.
- Lauren Chen: remove Phase 3 (offline mode indicators) from the launch tracker
  so it stops surfacing as at-risk in the executive summary.
- Amara Osei: confirm with the Verizon program manager whether Verizon field
  trainers join the September 22 train-the-trainer session or a separate one.
- Daniel Okoye: hand the effective-dating fix to Priya Raghavan for review on
  her return, since the semantics were her design.
- Daniel Okoye: re-escalate the Workday multi-position sandbox data request,
  which has now been open eleven days without a response.
- Unassigned: write up the explicit risk acceptance for launching without the
  six blocked Workday scenarios verified.
- Unassigned: settle who signs off on the retail-store pilot checklist —
  Verizon retail operations or the FieldSync program office.
- Unassigned: decide the support tier-2 staffing model if the second seat is
  not filled by September 10.

## Appendix B — open questions carried forward

1. Does the Arlington telemetry gap represent a captive-portal configuration
   that also exists in Verizon retail stores? If so, does that constitute a
   launch blocker rather than a pilot-district defect?
2. Should paper-out events count against the 99.5% print reliability bar, and
   if not, does the bar need to be re-baselined before launch or after?
3. Can Phase 2 (form runner) ship behind a feature flag without a completed
   accessibility audit, given the conformance clause in the Verizon MSA? Who
   has the authority to accept that contractual exposure?
4. If the accessibility audit lands after September 15, is Phase 2 cut from
   launch scope entirely, or does the launch date move?
5. Who owns the Phase 2 scope decision? It is currently discussed as a UX
   decision but is functionally a launch blocker via the training dependency.
6. Do Verizon field trainers attend the September 22 train-the-trainer session?
7. Is the sixth Workday test failure genuinely a sandbox artifact, or has that
   simply not been investigated?
8. Who signs off on the retail-store pilot checklist?
9. If the second tier-2 support seat is not filled, what response-time SLA is
   the team committing to for the first three weeks after launch?

## Appendix C — risks noted

- Training modules for Phase 2 cannot be written until the Phase 2 scope
  decision is made; a decision after September 5 puts the September 22
  train-the-trainer session, and therefore the October 1 launch, at risk.
- Shipping unaudited UI into a Verizon-facing surface may breach the
  accessibility conformance clause of the Verizon MSA.
- Six Workday integration scenarios may go unverified at launch, leaving
  multi-position worker assignment untested against real data shapes.
- The Arlington device telemetry gap may be a silent-failure mode that also
  affects Verizon stores.
- The launch support model assumes two tier-2 engineers; only one is
  identified, and the second seat has been open for a month.
- Print reliability is 98.97% against a 99.5% gate, and the measurement itself
  is disputed because operator conditions are not distinguished from faults.
- Ownership of the retail-store pilot checklist sign-off has been ambiguous for
  three weeks, with two different and incompatible assumptions in the room.

## Appendix D — decisions recorded

- Both the narrow and the broad form-builder permission fixes will be done: the
  narrow scope fix ships immediately, the broader open-time permission check is
  deferred to the sprint after launch rather than changing the builder during
  the freeze.
- Phase 3 (offline mode indicators) is explicitly not a launch commitment.
- The post-launch support handover plan is deferred to the next weekly sync.
- Launching without the six blocked Workday scenarios verified, if it happens,
  must be a documented risk acceptance rather than a silent gap.

## Appendix E — potential contradictions observed

- Marcus states that the retail-store pilot checklist is signed off by Verizon
  retail operations; Lauren states that the FieldSync program office signs off
  and Verizon counter-signs. Both cannot be true, and the discrepancy has
  persisted across three weekly syncs without resolution.
- Marcus argues paper-out events should be excluded from the print reliability
  metric; Lauren argues the metric is untrustworthy in either direction until
  the app distinguishes the states. The recorded reliability figure of 98.97%
  is therefore reported against a definition the group does not agree on.
- Lauren proposes shipping Phase 2 behind a flag without the accessibility
  audit; Daniel states this creates contractual exposure under the Verizon MSA.
  No adjudication was reached, yet the launch tracker still lists Phase 2 as a
  launch-scope item.
