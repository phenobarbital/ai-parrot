---
id: F011
slug: gigsmart-post-shift
query: "GigSmart gig/shift posting flow"
type: web
---

## Finding: postShift is the primary mutation (not postGig)

### Quick start — `postShift` creates series + gig in one call:
```graphql
mutation PostShift($input: PostShiftInput!) {
  postShift(input: $input) {
    gig { id, name, startsAt, endsAt, currentState { name } }
  }
}
```

### PostShiftInput fields:
- `organizationId` (ID!, required)
- `organizationPositionId` (ID!, required)
- `organizationLocationId` (ID!, required)
- `startsAt` (DateTime!, required)
- `endsAt` (DateTime!, required)
- `payRate` (Money, optional — defaults to position rate)
- `slotsAvailable` (Int, optional — defaults to 1)
- `description` (String, optional)

### Object model hierarchy:
Location + Position = Gig Series → Gig → Engagement

### Gig states:
- `UPCOMING` (future, published)
- `ACTIVE` (started)
- `IN_PROGRESS` (workers engaged)

### State transitions via `transitionGig`:
```graphql
transitionGig(input: { gigId: "...", action: "PUBLISH" })
```

### Advanced: Gig Series flow
- Three layers: Gig Series (template) → Gig (individual) → Shift (time slot)
- Supports recurring series, custom audience, addon configuration

### Correction to SPEC:
- SPEC §6.4 uses `PostGigInput` — should be `PostShiftInput`
- SPEC uses `workers_needed` — actual field is `slotsAvailable`
- SPEC uses `time_window` with start_at/end_at — actual uses `startsAt`/`endsAt` directly
- `payRate` is a Money type (not `pay_rate_override_cents`)
