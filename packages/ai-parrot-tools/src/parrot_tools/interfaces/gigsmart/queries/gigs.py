"""GraphQL query and mutation strings for the GigSmart gigs (shifts) surface."""

VIEWER_QUERY = """
query Viewer {
  viewer {
    __typename
    ... on OrganizationRequester {
      id
      organization {
        id
        name
      }
    }
  }
}
"""

LIST_GIGS = """
query ListGigs($organizationId: ID!, $first: Int, $after: String, $filter: GigFilter) {
  organization(id: $organizationId) {
    gigs(first: $first, after: $after, filter: $filter) {
      edges {
        node {
          id
          name
          startsAt
          endsAt
          slotsAvailable
          currentState {
            name
          }
          payRate
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

GET_GIG = """
query GetGig($id: ID!) {
  node(id: $id) {
    ... on Gig {
      id
      name
      startsAt
      endsAt
      slotsAvailable
      currentState {
        name
      }
      payRate
    }
  }
}
"""

POST_SHIFT = """
mutation PostShift($input: PostShiftInput!) {
  postShift(input: $input) {
    shift {
      id
      name
      startsAt
      endsAt
      slotsAvailable
      currentState {
        name
      }
    }
  }
}
"""

TRANSITION_GIG = """
mutation TransitionGig($input: TransitionGigInput!) {
  transitionGig(input: $input) {
    gig {
      id
      name
      currentState {
        name
      }
    }
  }
}
"""

SEARCH_GIGS = """
query SearchGigs($first: Int, $filter: GigFilter) {
  gigs(first: $first, filter: $filter) {
    edges {
      node {
        id
        name
        startsAt
        endsAt
        slotsAvailable
        currentState {
          name
        }
        payRate
      }
      cursor
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

GET_GIG_SUMMARY = """
query GetGigSummary($id: ID!) {
  node(id: $id) {
    ... on Gig {
      id
      name
      startsAt
      endsAt
      slotsAvailable
      currentState {
        name
      }
      payRate
      engagements {
        totalCount
        edges {
          node {
            id
            currentState {
              name
            }
          }
        }
      }
    }
  }
}
"""
