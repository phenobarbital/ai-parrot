# OdooHelpdeskToolkit — Softhealer helpdesk on Odoo 19

`OdooHelpdeskToolkit(OdooToolkit)` (`parrot_tools.odoo.helpdesk`) adds helpdesk tools for Softhealer's
`sh_all_in_one_helpdesk` on top of the generic Odoo toolkit. Tools are prefixed `odoo_` and every inherited
`OdooToolkit` tool is exposed too.

> **One Odoo toolkit per agent.** Both classes register `odoo_*` names; loading them together raises a
> tool-name collision in `ToolManager`. Load only `OdooHelpdeskToolkit` (it is a superset). To narrow the
> surface, subclass and set `exclude_tools`.

## Configuration
`ODOO_HELPDESK_URL`, `ODOO_HELPDESK_USER`, `ODOO_HELPDESK_APIKEY` (preferred) or `ODOO_HELPDESK_PASSWORD`,
`ODOO_HELPDESK_DATABASE` (optional; empty lets JSON-2 infer it), `ODOO_HELPDESK_TIMEOUT`, `ODOO_HELPDESK_VERIFY_SSL`.
These never fall back to the generic `ODOO_*` keys.

## Tools

### Reference data
| Tool | Input model | Result | Notes |
|---|---|---|---|
| list_helpdesk_stages | - | HelpdeskStageList | Lists all helpdesk stages |
| list_helpdesk_teams | - | HelpdeskTeamList | Lists all helpdesk teams |
| list_helpdesk_categories | - | HelpdeskCategoryList | Lists all helpdesk categories |
| list_helpdesk_priorities | - | HelpdeskPriorityList | Lists all helpdesk priorities |
| list_ticket_types | - | TicketTypeList | Lists all ticket types |
| list_helpdesk_tags | - | HelpdeskTagList | Lists all helpdesk tags |

### Tickets read
| Tool | Input model | Result | Notes |
|---|---|---|---|
| get_ticket | GetTicketInput | HelpdeskTicketDetail | Gets detailed ticket info |
| search_tickets | SearchTicketsInput | HelpdeskTicketList | Searches tickets by criteria |

### Tickets write
| Tool | Input model | Result | Notes |
|---|---|---|---|
| create_ticket | CreateTicketInput | CreatedTicket | Creates a new ticket |
| add_ticket_comment | AddCommentInput | CommentResult | Adds a comment to ticket |
| merge_tickets | MergeTicketsInput | MergeResult | Merges multiple tickets (requires confirmation) |

### Assignment
| Tool | Input model | Result | Notes |
|---|---|---|---|
| take_ticket | TakeTicketInput | AssignmentResult | Assigns ticket to current user |
| reassign_ticket | ReassignTicketInput | AssignmentResult | Reassigns ticket to another user |

### Transitions
| Tool | Input model | Result | Notes |
|---|---|---|---|
| close_ticket | CloseTicketInput | TransitionResult | Moves ticket to close stage |
| reopen_ticket | ReopenTicketInput | TransitionResult | Reopens a closed ticket |
| resolve_ticket | ResolveTicketInput | TransitionResult | Resolves a ticket |
| move_ticket_to_stage | MoveToStageInput | TransitionResult | Moves ticket to specific stage |

### SLA
| Tool | Input model | Result | Notes |
|---|---|---|---|
| create_sla_policy | CreateSLAPolicyInput | CreatedSLAPolicy | Creates a new SLA policy (requires confirmation) |
| get_ticket_sla_status | GetTicketSLAInput | TicketSLAStatus | Gets SLA status for ticket |

### Stats & wizards
| Tool | Input model | Result | Notes |
|---|---|---|---|
| ticket_stats | TicketStatsInput | TicketStatistics | Gets ticket statistics |
| mass_update_tickets | MassUpdateTicketsInput | MassUpdateResult | Updates multiple tickets (requires confirmation) |

### Timer
| Tool | Input model | Result | Notes |
|---|---|---|---|
| start_ticket_timer | StartTimerInput | TimerResult | Starts timer on ticket |
| stop_ticket_timer | StopTimerInput | TimerResult | Stops timer on ticket |

## Tenant caveats (verified on staging, 2026-10-01)
- `state` is the reply direction (`customer_replied` / `staff_replied`), exposed as `replied_status`; the lifecycle is `stage_id` (+ `lifecycle` block).
- Stage roles live on `res.company` (`new/reopen/done/cancel/close_stage_id`). When `done_stage_id` / `cancel_stage_id` are unset, `action_done` /
  `action_cancel` are no-ops: `resolve_ticket` / `cancel_ticket` return `applied=False` with a warning. `close_ticket` always works.
- A **public** comment (`internal=False`) reopens a closed ticket when the company's "stage change when staff replied" setting is on; internal notes never do.
- `reopen_ticket` writes the stage directly when `action_open` does nothing (reported as `method_used="stage_write"`).
- `start_ticket_timer` needs a default project configured on the tenant; otherwise it returns `running=False` and a warning.
- JSON-2 `create` is rejected by Odoo 19 for helpdesk models; the transport falls back to `web_save` transparently.