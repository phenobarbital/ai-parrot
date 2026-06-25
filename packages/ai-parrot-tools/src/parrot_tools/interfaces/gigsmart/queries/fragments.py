"""Shared GraphQL fragments reused across GigSmart query modules."""

PAGE_INFO_FRAGMENT = """
fragment PageInfoFields on PageInfo {
  hasNextPage
  hasPreviousPage
  startCursor
  endCursor
}
"""
