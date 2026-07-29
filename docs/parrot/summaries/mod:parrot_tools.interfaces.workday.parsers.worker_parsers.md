---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.worker_parsers
id: mod:parrot_tools.interfaces.workday.parsers.worker_parsers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot_tools.interfaces.workday.parsers.worker_parsers
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.format_phone_number
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_benefits_and_roles
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_business_site
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_compensation_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_contact_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_employment_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_identification_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_international_assignment_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_management_chain_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_payroll_and_tax_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_personal_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_position_management_chain_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_position_organizations
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_worker_organization_data
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_worker_reference
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_worker_status
  rel: defines
- concept: func:parrot_tools.interfaces.workday.parsers.worker_parsers.save_worker_document
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.worker_parsers`

## Functions

- `def save_worker_document(file_content_base64: str, filename: str, worker_id: str, storage_path: Optional[str]=None) -> Optional[str]` — Save worker document file from base64 content to disk.
- `def format_phone_number(phone_raw: Optional[str]) -> Dict[str, Optional[str]]` — Formats a phone number from various formats to the required standards.
- `def parse_worker_reference(worker_response: Dict[str, Any]) -> Dict[str, Any]` — Extracts the main Worker_Reference WID from a Worker SOAP response.
- `def parse_personal_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse the personal information of the worker.
- `def parse_contact_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse the contact information (email, address, phone) of the worker.
- `def parse_worker_organization_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse worker organization information from worker data
- `def parse_compensation_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse the compensation details of the worker.
- `def parse_identification_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse identification details (national ID, license, custom IDs).
- `def parse_benefits_and_roles(worker_data: Dict[str, Any], worker_id: Optional[str]=None, document_directory: Optional[str]=None) -> Dict[str, Any]` — Parse benefit enrollments, roles, and worker documents.
- `def parse_employment_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse employment-related details (position, hours, job profile).
- `def parse_worker_status(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse worker status details (active, hire/termination dates, eligibility),
- `def parse_business_site(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse business site summary data.
- `def parse_management_chain_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse management chain data from Worker_Management_Chain_Data.
- `def parse_position_management_chain_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse management chain data from Position_Management_Chains_Data.
- `def parse_payroll_and_tax_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse payroll and tax related data from Position_Data.
- `def parse_position_organizations(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse position organization data from Position_Organizations_Data.
- `def parse_international_assignment_data(worker_data: Dict[str, Any]) -> Dict[str, Any]` — Parse international assignment summary data.
