"""GraphQL mutation strings for the GigSmart messages surface."""

ADD_USER_MESSAGE = """
mutation AddUserMessage($input: AddUserMessageInput!) {
  addUserMessage(input: $input) {
    userMessage {
      id
      body
      insertedAt
    }
  }
}
"""
