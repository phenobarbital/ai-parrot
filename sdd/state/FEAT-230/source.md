---
kind: inline
jira_key: null
fetched_at: 2026-06-08
summary_oneline: Vendor flowtask's composable Workday interface into ai-parrot-tools and rebase WorkdayToolkit onto it; homologate 11 agent methods
---

En `/home/jesuslara/proyectos/parallel/flowtask/flowtask/interfaces/workday/` hemos
generado una interfaz composable para trabajar con Workday, permite abstraer métodos de
interacción con la API WSDL de Workday en una única interfaz composable (a partir de la
documentación: https://community.workday.com/sites/default/files/file-hosting/productionapi/index.html).

Esta propuesta consta de 3 niveles:
1. Copiar enteramente la interfaz al codebase de ai-parrot-tools dentro de un nuevo
   sub-folder de interfaces (`parrot_tools/interfaces/workday`).
2. Hacer que el toolkit de Workday (`parrot_tools/workday/tool.py` `WorkdayToolkit`) use
   este composable en vez de tener el código in-line per-method.
3. Cuando el `WorkdayToolkit` esté homologado, verificar/garantizar que todos estos
   métodos son ejecutables por el Toolkit de Workday:

```
find_employee_id_by_name          Look up an employee's worker ID by name
get_current_user_info             Get the current user's profile
get_current_user_time_off_balance Get the current user's leave balances
get_current_user_time_off_history Get the current user's leave request history
get_time_off_balance              Get leave balances for any worker by ID
get_direct_reports                List direct reports for a manager
get_more_employee_data            Get extended employee data
get_my_time_off_eligibility       Check which leave types the current user can request
get_personal_information          Get personal info (address, emergency contact)
get_today_date_and_day_of_week    Get the current date and time
request_my_time_off               Submit a time-off request for the current user
```
