---
kind: inline
jira_key: null
fetched_at: 2026-10-06T00:00:00+00:00
summary_oneline: Linked A2UI surfaces should optionally route through a server endpoint that executes the query slug and applies recipe transformers, like static/recipe surfaces do
---

# Source (inline, verbatim — Spanish)

**Slug solicitado**: `linked-a2ui-recipes-transforms`

> las surfaces a2ui estáticas pueden hacer agregación con transformadores en
> python, pero las linked surfaces no (dependen de la invocación del query
> slug) llaman a la URL de querysource, pero y si al definir la surface se
> puede invocar o la URL del querysource o llaman a una URL dónde se decide
> ejecutar el slug y luego pasar la data por un transformer, con lo cual los
> linked surfaces ganan la flexibilidad de ganar data de manera dinámica y a
> su vez de invocar transformaciones de las recipes (tal y como las static y
> recipe definitions)

# Paraphrase (English)

Static A2UI surfaces can aggregate data through Python transformers
(recipes), but **linked surfaces** cannot — they depend on invoking the
query slug directly against the querysource URL. The idea: when a surface
is defined, allow it to point either at (a) the querysource URL directly
(current behavior), or (b) a new URL/endpoint where the server executes the
slug and then pipes the resulting data through a transformer. Linked
surfaces would thus keep dynamic data acquisition AND gain recipe
transformations, achieving parity with static and recipe definitions.
