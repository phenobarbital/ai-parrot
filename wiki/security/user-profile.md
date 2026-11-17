# User Profile Management

This document describes the user profile structure and how to configure profile attributes in AI Parrot.

## Profile Attributes

The user profile in AI Parrot contains standard identity information and customizable display attributes. These attributes are typically populated from the authentication provider (SSO, Active Directory, etc.) or the local user database.

### Standard Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `username` | string | Unique identifier for the user (often email). |
| `email` | string | User's email address. |
| `displayName` | string | Full name for display purposes. |
| `firstName` | string | User's first name. |
| `lastName` | string | User's last name. |

### Custom Attributes

#### `avatar`
The `avatar` attribute is used to display a custom profile picture in the sidebar and user menu.

- **Type**: `string` (URL)
- **Description**: An absolute or relative URL pointing to the user's profile image.
- **Behavior**:
    - If `avatar` is Set: The image at the URL is displayed.
    - If `avatar` is Not Set: A generic user icon (SVG) is displayed as a fallback.

## Setting the Avatar

The `avatar` attribute should be returned as part of the user session or profile data from the backend `login` or `me` endpoints.

### JSON Example (API Response)

```json
{
  "user": {
    "id": 123,
    "username": "jdoe@example.com",
    "firstName": "John",
    "lastName": "Doe",
    "avatar": "https://example.com/photos/jdoe.jpg" // Optional
  }
}
```

### Integration Tips
- Ensure the `avatar` URL is accessible from the client browser.
- If using an internal asset server, use relative paths (e.g., `/assets/avatars/123.png`).
- To force the generic icon, simply omit the `avatar` field or set it to `null`.
