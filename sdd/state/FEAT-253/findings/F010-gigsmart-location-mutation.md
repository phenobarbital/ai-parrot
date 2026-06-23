---
id: F010
slug: gigsmart-location-mutation
query: "GigSmart location creation flow"
type: web
---

## Finding: Location creation is a 3-step flow

### Step 1 — Address lookup via `placeAutocomplete`:
```graphql
query SearchAddress($input: PlaceAutocompleteInput!) {
  placeAutocomplete(input: $input) {
    label, placeId, placeProvider
    place { street, locality, administrativeAreaLevel1 }
  }
}
```

### Step 2 — Look up contacts and payment methods:
- `organization { organizationRequesters(first: 20) { edges { node { id, displayName } } } }`
- `organization { paymentMethods(first: 20) { edges { node { externalId, last4, ... } } } }`

### Step 3 — Create via `addOrganizationLocation`:
```graphql
mutation AddLocation($input: AddOrganizationLocationInput!) {
  addOrganizationLocation(input: $input) {
    newOrganizationLocationEdge {
      node { id, name, state, primaryContact { id }, place { ... }, location { latitude, longitude } }
    }
  }
}
```

### Input fields:
- `organizationId` (ID!, required)
- `name` (String!, required)
- `state` (OrganizationLocationState, ACTIVE)
- `primaryContactId` (ID)
- `paymentMethodId` (String)
- `placeId` (String) OR `address` (String)
- `arrivalInstructions` (String)
- `locationInstructions` (String)

### Correction to SPEC:
- SPEC uses a flat `Address` model — actual API uses `placeId` from autocomplete
- Location creation requires `organizationId` — not implicit from auth
- Response uses Relay edge pattern: `newOrganizationLocationEdge { node { ... } }`
