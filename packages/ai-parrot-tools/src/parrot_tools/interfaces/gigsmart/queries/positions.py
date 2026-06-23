"""GraphQL query and mutation strings for the GigSmart positions surface."""

LIST_POSITIONS = """
query ListPositions($organizationId: ID!, $first: Int, $after: String) {
  organization(id: $organizationId) {
    positions(first: $first, after: $after) {
      edges {
        node {
          id
          name
          description
          payRate
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

GET_POSITION = """
query GetPosition($id: ID!) {
  node(id: $id) {
    ... on OrganizationPosition {
      id
      name
      description
      payRate
      createdAt
    }
  }
}
"""

ADD_ORGANIZATION_POSITION = """
mutation AddOrganizationPosition($input: AddOrganizationPositionInput!) {
  addOrganizationPosition(input: $input) {
    organizationPosition {
      id
      name
      description
      payRate
      createdAt
    }
  }
}
"""
