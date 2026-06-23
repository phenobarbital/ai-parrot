"""GraphQL query and mutation strings for the GigSmart engagements surface.

All engagement state transitions use the single ``transitionEngagement`` mutation.
There are NO separate hire/accept/end/cancel mutations.
"""

LIST_ENGAGEMENTS = """
query ListEngagements($gigId: ID!, $first: Int, $after: String, $filter: EngagementFilter) {
  node(id: $gigId) {
    ... on Gig {
      engagements(first: $first, after: $after, filter: $filter) {
        edges {
          node {
            id
            gigId
            workerDisplayName
            currentState {
              name
            }
            appliedAt
            hiredAt
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
}
"""

GET_ENGAGEMENT = """
query GetEngagement($id: ID!) {
  node(id: $id) {
    ... on Engagement {
      id
      gigId
      workerDisplayName
      currentState {
        name
      }
      appliedAt
      hiredAt
    }
  }
}
"""

ADD_ENGAGEMENT = """
mutation AddEngagement($input: AddEngagementInput!) {
  addEngagement(input: $input) {
    engagement {
      id
      gigId
      currentState {
        name
      }
    }
  }
}
"""

TRANSITION_ENGAGEMENT = """
mutation TransitionEngagement($input: TransitionEngagementInput!) {
  transitionEngagement(input: $input) {
    engagement {
      id
      currentState {
        name
      }
    }
  }
}
"""

LIST_ENGAGEMENT_STATES = """
query ListEngagementStates($id: ID!) {
  node(id: $id) {
    ... on Engagement {
      id
      engagementStates {
        edges {
          node {
            name
            transitionedAt
          }
          cursor
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""
