---
id: F008
slug: gigsmart-oauth-scopes
query: "GigSmart OAuth scopes"
type: web
---

## Finding: 12 OAuth scopes, write scopes require auth_code grant

### Scopes:
| Scope | Description | Grant Types |
|-------|-------------|-------------|
| `read:gigs` | View gig postings, shifts, scheduling | auth_code, client_credentials |
| `read:engagements` | View engagement details and state transitions | auth_code, client_credentials |
| `read:organizations` | View organization profiles and structure | auth_code, client_credentials |
| `read:positions` | View organization positions and gig categories | auth_code, client_credentials |
| `read:locations` | View organization locations and addresses | auth_code, client_credentials |
| `write:gigs` | Create and modify gig postings | auth_code only |
| `write:engagements` | Modify engagement states | auth_code only |
| `write:organizations` | Manage organizations | auth_code only |
| `write:positions` | Create and manage positions | auth_code only |
| `write:locations` | Create and manage locations | auth_code only |
| `read:messages` | Read messages and conversations | auth_code only |
| `write:messages` | Send messages | auth_code only |

### Important constraint:
- Write scopes ONLY available via auth_code grant (not client_credentials)
- This means server-to-server (client_credentials) is READ-ONLY
- Write mutations require user-facing OAuth flow with PKCE

### No timesheet-specific scopes visible
- Timesheet operations may be under `read:engagements` / `write:engagements`
