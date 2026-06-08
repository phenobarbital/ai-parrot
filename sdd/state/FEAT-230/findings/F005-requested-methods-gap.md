# F005 — 11 requested agent methods: NET-NEW self-service layer
**Type:** grep  **Confidence:** high
## Summary
grep across repo for each requested name:
- find_employee_id_by_name → NONE (analog: wd_search_workers_by_name)
- get_current_user_info → NONE
- get_current_user_time_off_balance → NONE
- get_current_user_time_off_history → NONE
- get_time_off_balance → EXISTS as wd_get_time_off_balance (tool.py)
- get_direct_reports → NONE (analog: wd_get_workers_by_manager; also employees.py/hierarchy.py have unrelated get_direct_reports)
- get_more_employee_data → NONE
- get_my_time_off_eligibility → NONE
- get_personal_information → NONE (partial: wd_get_worker_contact)
- get_today_date_and_day_of_week → NONE (trivial, no SOAP)
- request_my_time_off → NONE (WRITE op, needs Absence Mgmt submit)
## Implication
~9 of 11 are net-new. "current_user / my_" methods require a CURRENT-USER IDENTITY source (session user_id→worker_id). request_my_time_off is a write operation.
