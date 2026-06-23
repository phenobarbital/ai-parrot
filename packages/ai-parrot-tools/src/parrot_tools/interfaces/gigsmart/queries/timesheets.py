"""GraphQL query and mutation strings for the GigSmart timesheets and disputes surfaces.

Key facts from schema introspection:
- Only two timesheet mutations: ``approveEngagementTimesheet`` (approve) and
  ``removeEngagementTimesheet`` (reject/send back — worker can resubmit).
- No ``editTimesheet`` mutation exists.
- Disputes are separate: ``addEngagementDispute`` and ``setEngagementDisputeApproval``.
"""

LIST_TIMESHEETS = """
query ListTimesheets($engagementId: ID!) {
  node(id: $engagementId) {
    ... on Engagement {
      timesheets {
        edges {
          node {
            id
            engagementId
            isApproved
            variant
            paymentStyle
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

GET_TIMESHEET = """
query GetTimesheet($id: ID!) {
  node(id: $id) {
    ... on EngagementTimesheet {
      id
      engagementId
      isApproved
      variant
      paymentStyle
    }
  }
}
"""

APPROVE_ENGAGEMENT_TIMESHEET = """
mutation ApproveEngagementTimesheet($input: ApproveEngagementTimesheetInput!) {
  approveEngagementTimesheet(input: $input) {
    engagementTimesheet {
      id
      isApproved
      variant
    }
  }
}
"""

REMOVE_ENGAGEMENT_TIMESHEET = """
mutation RemoveEngagementTimesheet($input: RemoveEngagementTimesheetInput!) {
  removeEngagementTimesheet(input: $input) {
    engagementTimesheet {
      id
      isApproved
    }
  }
}
"""

ADD_ENGAGEMENT_DISPUTE = """
mutation AddEngagementDispute($input: AddEngagementDisputeInput!) {
  addEngagementDispute(input: $input) {
    engagementDispute {
      id
      engagementId
    }
  }
}
"""

SET_ENGAGEMENT_DISPUTE_APPROVAL = """
mutation SetEngagementDisputeApproval($input: SetEngagementDisputeApprovalInput!) {
  setEngagementDisputeApproval(input: $input) {
    engagementDispute {
      id
    }
  }
}
"""
