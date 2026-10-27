# Inline A2UI Component Routing (FEAT-755)

Inline A2UI component routing lets an agent choose a display-only A2UI component
from a user's phrasing while it is still preparing the answer. It extends the
existing output-mode phrase bank; it does not add an `OutputMode` for every
component.

## What it does

When an output-routing agent is in its normal `Default (Auto)` mode, phrases in
its route bank can select an inline `KPICard`, `InfoCard`, `Timeline`, or `Graph`.
The main model turn then authors the selected component's configuration, which is
validated against the catalog and returned as an A2UI surface in the chat reply.

An explicit caller output mode, an explicit `a2ui_component` hint, and a
`/trigger`-selected skill retain precedence over phrase-bank routing. Routing is
therefore an opt-in default, not a replacement for an explicit request.

## Route grammar

Phrase-bank keys are either a plain `OutputMode` value, such as
`structured_chart`, or an A2UI component label:

```text
a2ui:<ComponentName>
```

For example, `a2ui:KPICard` parses to `OutputMode.A2UI` with the `KPICard`
component hint. The pure helpers
`parrot.registry.routing.route_labels.make_route_label()` and
`parse_route_label()` create and parse that form. Empty component names and
unknown plain output modes are invalid.

A composite label is accepted only when its component is registered in the A2UI
catalog and is display-only (`requires_actions=False`). Invalid labels and
action-bearing or unregistered components are warned about and skipped when the
router is configured.

To choose a component explicitly, pass the existing hint kwarg on a data-agent
turn:

```python
await agent.ask("Show this month's worked hours", a2ui_component="KPICard")
```

## Configuring the phrase bank (`routes.yaml`)

The optional phrase bank is loaded from these paths under an agent's definition
root:

```text
<agent_root>/routes.yaml
<agent_root>/tenants/<tenant>/routes.yaml
```

The resolved banks merge in this order: built-in defaults, then the agent bank,
then the tenant bank. A tenant bank starts from the resolved agent bank. For each
route, `replace: false` (the default) extends its utterances and removes duplicate
strings; `replace: true` replaces that route's utterances. `threshold` and
`margin` are optional agent-level routing-policy overrides.

This complete agent-level file adds KPI phrases without replacing the built-in
ones:

```yaml
version: 1
replace: false
routes:
  a2ui:KPICard:
    - show this month's worked hours
    - resumen de horas trabajadas este mes
  a2ui:Timeline:
    - show the project milestones in order
threshold: 0.72
margin: 0.08
```

Files are validated as `version`, `routes`, `replace`, `threshold`, and `margin`.
An absent, unreadable, malformed, or unknown-key file is warned about and skipped;
it never prevents the agent from using the remaining bank. Invalid route labels
are likewise warned about and omitted while configuring the router.

## The `parrot_presentation` marker

The inline emitter writes this surface-level extension at
`createSurface.metadata.extensions.parrot_presentation`:

```json
{
  "kind": "widget",
  "inline": true,
  "origin": "chat_turn",
  "component": "KPICard"
}
```

Renderers should read the marker before applying a root-component heuristic. The
reference UI treats a well-formed marker as the authoritative surface kind and
renders a surface with `inline: true` inside the chat bubble when the response
mode is `a2ui`. Missing or malformed markers are ignored safely, so older
envelopes continue through the normal root-component heuristic.

## Adding a new inline component (FEAT-753 / FEAT-754)

To make a component available to inline routing:

1. Register the catalog component as display-only (`requires_actions=False`).
2. Add one or more utterances under its `a2ui:<ComponentName>` route label in the
   default bank or a `routes.yaml` overlay.
3. Add optional component-specific authoring notes when the catalog instructions
   need inline-chat constraints.
4. Add an optional `SOURCE_MODEL` when the component needs a hand-written
   Pydantic model whose validators must survive schema generation.
5. Add an optional feasibility rule when schema-valid output can still be
   unusable in a chat bubble.

The emitter derives its base authoring contract from the registered component
schema and instructions, validates the completed surface as LLM-origin output,
and keeps the emitted marker component equal to the requested catalog name.

## The precedence hook (FEAT-756)

The output-shape precedence is:

```text
explicit caller mode or hint > router (mode plus hint) > metric default shape > agent default
```

`IntentRouterMixin._resolve_output_mode()` calls `super()` when it has no router
or the router abstains. A cooperative FEAT-756 override calls `super()` first;
when that also abstains, it can return
`set_output_shape(ctx, OutputShape(OutputMode.A2UI, "<Component>"))`. This keeps
the component hint on the request context and leaves the existing agent default
as the final fallback.

## Degradation

Inline emission never raises into the chat turn. It degrades to the normal prose
answer when the requested component is not inline-eligible, no component JSON can
be extracted, a feasibility check fails, catalog validation fails, or an
unexpected emitter failure occurs. The reason is recorded in
`response.metadata["a2ui_inline"]` for emitted and degraded outcomes.

If A2UI was requested but no surface is produced, the response mode falls back to
`DEFAULT`. Text-only transports continue to receive the ordinary lowered text
fallback from A2UI finalization rather than an empty structured reply.
