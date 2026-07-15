---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.organization_parsers
id: mod:parrot_tools.interfaces.workday.parsers.organization_parsers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot_tools.interfaces.workday.parsers.organization_parsers
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.organization_parsers.parse_organization_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.organization_parsers.parse_organizations_response
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.models.organizations
  rel: references
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.organization_parsers`

## Functions

- `def parse_organization_data(org_data: Union[Dict[str, Any], OrderedDict]) -> Organization` — Parse organization data from Workday SOAP response.
- `def parse_organizations_response(response_data: Dict[str, Any]) -> List[Organization]` — Parse the complete organizations response from Workday.
