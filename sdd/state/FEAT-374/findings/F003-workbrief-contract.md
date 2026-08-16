# F003 — WorkBrief: the exact Pydantic structured input the CLI must collect

- **Query**: Q009 (wiki file page `models.py` + live introspection via
  `WorkBrief.model_fields`)
- **Citations**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py::WorkBrief`
  - `kind: Literal['bug','enhancement','new_feature']` (default `'bug'`)
  - `summary: str` (required, ≤255 — becomes Jira summary)
  - `description: str` (default `''`) — long-form details
  - `affected_component: str` (required)
  - `log_sources: List[LogSource]`
  - `acceptance_criteria: List[FlowtaskCriterion | ShellCriterion | ManualCriterion]`
  - `escalation_assignee: str` (required, Jira accountId/email)
  - `reporter: str` (required)
  - `existing_issue_key: Optional[str]` — **the "Jira ticket (if any)"** the
    source asks about; when set, ResearchNode skips issue creation
  - `dev_agents: Optional[List[DevAgentSpec]]`, `dev_isolation` (FEAT-323)
  - Also: `RevisionBrief` (repo_path, branch, pr_number, repository,
    jira_issue_key, feedback, head_sha) for revision-mode runs.
- Field descriptions exist on the model — a pydantic-driven prompt wizard can
  render them directly (`model_fields[*].description`, `is_required()`,
  defaults, Literal choices).
- `models.py` has zero internal deps beyond pydantic (safe cheap import).
