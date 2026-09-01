---
kind: inline
jira_key: null
fetched_at: 2026-09-01T00:00:00Z
summary_oneline: New A2UI PandasAgent for Flex program — KPI dashboards, /widget + /infographic skills, QuerySource-fed datasets, deterministic HTML refresh
---

# New A2UI PandasAgent for Flex

Crear un agente en `agents/flex_dashboard.py` basado en PandasAgent y con la infra de A2UI outputs and dashboards.

Using QuerySource slugs y DatasSourceManager para consumir los siguientes slugs:

* `flex_msl_brian_bi` — Master Store List: district/region/market, account, store, lat/lon, city, state.

```json
{
    "district_name": "IL - Chicago",
    "region_name": "Midwest Region",
    "market_name": "IL - Chicago - Oak Park",
    "account_name": "T-Mobile",
    "store_name": "T-Mobile 3SFD Norridge IL",
    "latitude": 41.95535,
    "longitude": -87.80886,
    "city": "Norridge",
    "state_code": "IL"
}
```

* `Finance_results_bi` — P&L by project/month: Revenue, PC Revenue, EBITDA, Payroll, Travel and Expenses, Program Overhead Allocation, Other Related Expenses, Total Hours, FTE, Visits. Currency fields arrive as formatted strings (`"$137,456.85"`).

```json
{
    "project": "Flex - General",
    "month": "2025-10-31",
    "Revenue": "$137,456.85",
    "PC Revenue": "$51,229.85",
    "EBITDA": "$10,222.16",
    "Payroll": "$20,682.27",
    "Travel and Expenses": "$13,746.44",
    "Program Overhead Allocation": "$0.00",
    "Other Related Expenses": "-$44,621.24",
    "Total Hours": 2250.866693,
    "FTE": 17.278409301948,
    "Visits": 241
}
```

* `flex_hours_query_pbi` — hours/wages by month, program, pay_code, cost_center.

```json
{
    "month_start": "2025-10-01",
    "month_end": "2025-10-31",
    "program": "Flex - General",
    "pay_code": "Admin Time",
    "cost_center": "Flex",
    "hours": 30.199996,
    "wages": 693.749909
}
```

* `flex_empolyees_brian_bi` — employee roster with geo (lat/lon), Flex Type, service tenure fields.

```json
{
    "display_name": "Abby Halladay",
    "start_date": "2025-12-31",
    "job_code_title": "Mobile Retail Display Technician",
    "referred_by": null,
    "legal_city": "MEDIA",
    "legal_state": "PA",
    "zipcode": "19063",
    "phone_mobile": "(267) 346-0701",
    "latitude": 39.9222285,
    "longitude": -75.414058,
    "Flex Employees": 1,
    "Flex Type": "Flex",
    "Years of Service": 1,
    "Months of Service": 8,
    "Days of Service": 244,
    "Days of Service Retention": 244
}
```

* `fm_regions_avg_employees_html` — region/state monthly employee utilization.

```json
{
    "BOP Date": "2026-03-01",
    "EOP Date": "2026-03-31",
    "FM Region": "CA",
    "State Code": "CA",
    "State": "California",
    "Category": "Flex",
    "Employees Worked": 11,
    "Average Active Employees": 75.5,
    "Flex Employees": 68,
    "Employee Utilization": 0.145695364238411
}
```

* `fm_rep_utilization` — rep utilization by region/state/category per month.

```json
{
    "bop_date": "2026-05-01",
    "eop_date": "2026-05-31",
    "region": "CA",
    "state": "CA",
    "catagory": "Flex",
    "hours_worked": 167.550001,
    "work_shifts": 76,
    "employees_worked": 12,
    "average_active": 63
}
```

## Analytical scope (agent Q&A)

El PandasAgent será usado para responder por los siguientes computos a partir de los datasets aportados:

- **Payroll Contribution**
  * Worked Hours by Month
  * Payroll by Month
  * P&L Revenue by Month
  * Payroll % to Revenue by Month
  * Pay Code Hours
  * Worked Hours by Pay Code Allocation
- **Proximity Staffing**
  * Compare the Master Store List with the Employee proximity
- **Rep (Representative) Utilization**
  * Utilization by Region / Type

## Dashboard scope (A2UI deterministic refresh)

Aprovechar la capacidad de generar Dashboards con refrescamiento determinista basado en el HTML aportado como ejemplos en:
- `artifacts/a2ui_live/flex_program_report%20(39).html`
- `artifacts/a2ui_live/page.html`

Usando dashboard A2UI el dashboard debe ser capaz de mostrar los KPI:

- **Payroll Contribution**
  * Hero Cards: Worked Hours (total), Payroll (total), P&L Revenue (total), Payroll % to revenue (percentage)
  * Worked Hours by Month
  * Payroll by Month
  * P&L Revenue by Month
  * Payroll % to Revenue by Month
  * Pay Code Hours
  * Worked Hours by Pay Code Allocation

Al incorporar la data descargada directamente en el HTML (tal como el ejemplo), los usuarios pueden filtrar por Month, Flex Type, Pay Code or Cost Center.

## Additional requirements

- Un botón de "refresh" que usa la lógica determinista de volver a generar el HTML con data nueva.
- Incorporar un skill `/widget` para que cada uno de los KPI lo "exporte" como un A2UI structured chart (or map, or hero card, etc) y se renderice en el frontend como es debido.
- Incorporar InfographicToolkit y un skill (`/infographic`) para que el usuario pueda solicitar una infografía descriptiva.
- El agente debe tener WorkingMemoryToolkit para poder realizar operaciones intermedias con los datos.
- Varios documentos de "kb" explicando cada uno de los KPIs y cómo se computan (para reducir la ambigüedad en la forma de computarlos).
