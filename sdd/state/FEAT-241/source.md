---
kind: inline
jira_key: null
fetched_at: 2026-06-16
summary_oneline: Allow parrot-formdesigner public forms (is_public=True) to dynamically register/unregister their auth-exempt paths in navigator-auth's frozen exclude list at runtime.
---

# Source — FEAT-241 (inline)

Hay que permitir crear forms en parrot-formdesigner que si una propiedad
"is_public" es TRUE, las URLs para acceder al form en sus distintas versiones
(JSON schema, etc) y la URL para publicar resultados, debe ser registradas en
el exclude list de navigator-auth, el problema radica en que las tablas de
rutas son "frozen" (de hecho, son un frozenset) cuando termina de iniciar el
servidor, hay que permitir que el middleware de navigator-auth (../navigator-auth)
invoque una función que evalua de una lista de paths registrados para ser
excluidos del middleware de auth, entonces FormDesigner puede simplemente
agregar los paths relativos al Form a esa lista con un método de edición, y
retirar de dicha lista si el usuario edita el formulario y apaga la propiedad
(is_public=False).

## Translation / interpretation (not authoritative)

Allow creating forms in parrot-formdesigner such that when a form property
`is_public` is TRUE, the URLs to access the form in its different
representations (JSON schema, etc.) and the URL to submit/publish results must
be registered in navigator-auth's exclude list (auth-exempt paths). The problem
is that navigator-auth's route tables are "frozen" (literally a `frozenset`)
once the server finishes booting. We need to let the navigator-auth middleware
invoke a function that evaluates a list of dynamically-registered paths to
exclude from the auth middleware. Then FormDesigner can simply add the
form-relative paths to that list via an edit method, and remove them from the
list if the user edits the form and turns `is_public` off (is_public=False).
