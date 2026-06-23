---
id: F007
slug: gigsmart-api-shape
query: "GigSmart API endpoint, GraphQL shape, mutations"
type: web
---

## Finding: GraphQL API confirmed with Relay conventions

### Endpoint:
- `https://api.gigsmart.com/graphql`

### Viewer query:
```graphql
{ viewer { ... on OrganizationRequester { id requester { firstName lastName } organization { name } } } }
```

### Mutation naming: camelCase
- `addOrganizationLocation` (not `createLocation`)
- `postShift` (not `postGig`)
- `transitionGig` (for state changes)

### Input pattern: single `$input` argument (Relay convention)
```graphql
mutation AddLocation($input: AddOrganizationLocationInput!) {
  addOrganizationLocation(input: $input) { ... }
}
```

### Pagination: Relay connection pattern
```graphql
organizationRequesters(first: 20) {
  edges { node { id, displayName } }
}
```

### Gig states confirmed:
- `UPCOMING` (future, published)
- `ACTIVE` (started)
- `IN_PROGRESS` (workers engaged)

### Key corrections to SPEC:
- Mutation names differ: `addOrganizationLocation`, `postShift`, `transitionGig`
- Relay edge/node pagination (not simple `nodes[]`)
- `postShift` creates series + gig in one call
- `placeAutocomplete` query for address lookup (not direct address input)
