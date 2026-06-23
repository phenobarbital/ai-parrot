"""GraphQL query and mutation strings for the GigSmart locations surface."""

PLACE_AUTOCOMPLETE = """
query PlaceAutocomplete($input: PlaceAutocompleteInput!) {
  placeAutocomplete(input: $input) {
    results {
      label
      placeId
      placeProvider
    }
  }
}
"""

LIST_LOCATIONS = """
query ListLocations($organizationId: ID!, $first: Int, $after: String) {
  organization(id: $organizationId) {
    locations(first: $first, after: $after) {
      edges {
        node {
          id
          name
          state
          latitude
          longitude
          createdAt
        }
        cursor
      }
      pageInfo {
        hasNextPage
        hasPreviousPage
        startCursor
        endCursor
      }
    }
  }
}
"""

GET_LOCATION = """
query GetLocation($id: ID!) {
  node(id: $id) {
    ... on OrganizationLocation {
      id
      name
      state
      latitude
      longitude
      createdAt
    }
  }
}
"""

ADD_ORGANIZATION_LOCATION = """
mutation AddOrganizationLocation($input: AddOrganizationLocationInput!) {
  addOrganizationLocation(input: $input) {
    organizationLocation {
      id
      name
      state
      latitude
      longitude
      createdAt
    }
  }
}
"""
