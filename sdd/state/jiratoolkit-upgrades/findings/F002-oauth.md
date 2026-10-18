# F002 — existing 3LO machinery
packages/ai-parrot/src/parrot/auth/jira_oauth.py: JiraOAuthManager(redirect_uri, redis required: __init__ L98-125),
ACCESSIBLE_RESOURCES_URL L34, create_authorization_url L258, handle_callback L304, get_valid_token L409.
Tokens live in Redis keyed (channel,user_id); designed for the aiohttp callback server + chat integrations.
Toolkit oauth2_3lo mode needs a credential_resolver (jiratoolkit.py:982-984), resolved in _pre_execute (L1243).
jira_config.py: JiraToolkitConfig auth_type Literal excludes oauth2_3lo.
