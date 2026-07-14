---
type: Wiki Summary
title: parrot.auth.manifest
id: mod:parrot.auth.manifest
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: In-package YAML manifest loader for per-agent credential configuration.
relates_to:
- concept: func:parrot.auth.manifest.load_credentials_manifest
  rel: defines
- concept: func:parrot.auth.manifest.parse_credentials_block
  rel: defines
- concept: mod:parrot.auth.credentials
  rel: references
---

# `parrot.auth.manifest`

In-package YAML manifest loader for per-agent credential configuration.

Parses a ``credentials:`` block (inline or from a file) into a list of
:class:`~parrot.auth.credentials.ProviderCredentialConfig` entries, with
env-var substitution for option values.

Expected YAML shape
-------------------
.. code-block:: yaml

    credentials:
      - provider: workiq
        auth: obo
        options:
          scope: api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask

      - provider: jira
        auth: oauth2

      - provider: fireflies
        auth: static_key
        options:
          capture_url: ${FIREFLIES_CAPTURE_URL}
          vault_key: fireflies:api_key

      - provider: myservice
        auth: mcp
        options:
          vault_key: myservice:token
          auth_url: https://myservice.example.com/auth

Environment variable substitution
----------------------------------
Option values of the form ``${VAR_NAME}`` are substituted with the value of
the corresponding environment variable.  ``${VAR_NAME:-default}`` syntax is
also supported (the part after ``:-`` is used when the variable is unset or
empty).  Missing variables (without a default) are silently expanded to an
empty string.

## Functions

- `def load_credentials_manifest(source: Union[str, Path], *, key: str='credentials') -> List[ProviderCredentialConfig]` — Load credential provider configs from a YAML file.
- `def parse_credentials_block(block: Optional[List[Dict[str, Any]]], *, expand_env: bool=True) -> List[ProviderCredentialConfig]` — Parse a raw ``credentials:`` list (already parsed from YAML) into configs.
