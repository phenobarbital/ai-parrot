"""Web Worker boot block + patch allowlist (FEAT-459 / M13, OQ-7).

Generates the additive JS block injected into html5.py's
_LIFECYCLE_SCRIPT_TEMPLATE. The Worker itself has NO DOM (G6) and
communicates via postMessage; the HOST page applies patches through a
fixed six-operation allowlist. The existing fetch-based remote bridge in
_LIFECYCLE_SCRIPT_TEMPLATE is untouched — this module is purely additive.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# The ONLY six patch operations a Worker may request the host apply
# (spec §2 "Client patch allowlist", OQ-7). Exact names/arities fixed.
ALLOWED_PATCH_OPERATIONS: frozenset[str] = frozenset(
    {"set_visibility", "set_required", "set_enabled", "set_value", "set_hint", "narrow_options"}
)


def validate_patch(patch: dict) -> bool:
    """True if `patch` names an allowlisted operation with a field_uid.

    This is the Python-side mirror of the host-page's JS allowlist check
    — used wherever a patch is inspected/logged server-side (e.g.
    security auditing), NOT the actual client-side enforcement (which
    runs as generated JS in the browser, see render_worker_boot_block()).
    """
    op = patch.get("op")
    if op not in ALLOWED_PATCH_OPERATIONS:
        logger.warning("worker patch discarded: unrecognised operation %r", op)
        return False
    if "field_uid" not in patch:
        logger.warning("worker patch discarded: missing field_uid for op %r", op)
        return False
    return True


def render_worker_boot_block() -> str:
    """Generate the additive Worker boot block for _LIFECYCLE_SCRIPT_TEMPLATE.

    Returns:
        A raw JS string (no Python f-string interpolation — matching the
        existing template's __SENTINEL__ convention) implementing:
        1. Worker instantiation from a Blob (so no separate static file
           is needed per form — the compiled snippet client_source(s)
           are embedded via the __SNIPPET_CLIENT_SOURCES__ sentinel).
        2. A postMessage listener applying ONLY the six allowlisted ops.
        3. No DOM access inside the Worker's own script body.

    The returned string uses the sentinel __SNIPPET_CLIENT_SOURCES__
    (a JSON array of compiled JS strings, one per bundle with a
    client_source) — html5.py's _inject_lifecycle() must .replace() it
    the same way it already replaces __FORM_ID__ etc.
    """
    allowed_ops_js = json.dumps(sorted(ALLOWED_PATCH_OPERATIONS))
    return (
        "\n<script>\n"
        "(function() {\n"
        "  var ALLOWED_PATCH_OPS = " + allowed_ops_js + ";\n"
        "  var SNIPPET_CLIENT_SOURCES = __SNIPPET_CLIENT_SOURCES__;\n"
        "  if (!SNIPPET_CLIENT_SOURCES.length) { return; }\n"
        "  var workerSrc = SNIPPET_CLIENT_SOURCES.join('\\n');\n"
        "  var blob = new Blob([workerSrc], {type: 'application/javascript'});\n"
        "  var worker = new Worker(URL.createObjectURL(blob));\n"
        "  worker.onmessage = function(evt) {\n"
        "    var patches = evt.data && evt.data.patches ? evt.data.patches : [];\n"
        "    patches.forEach(function(patch) {\n"
        "      if (ALLOWED_PATCH_OPS.indexOf(patch.op) === -1 || !patch.field_uid) {\n"
        "        console.warn('discarded disallowed worker patch', patch);\n"
        "        return;\n"
        "      }\n"
        "      applyFieldPatch(patch);\n"
        "    });\n"
        "  };\n"
        "  function applyFieldPatch(patch) {\n"
        "    var el = document.querySelector('[data-field-uid=\"' + patch.field_uid + '\"]');\n"
        "    if (!el) { return; }\n"
        "    switch (patch.op) {\n"
        "      case 'set_visibility':\n"
        "        el.hidden = patch.value;\n"
        "        break;\n"
        "      case 'set_required':\n"
        "        el.required = patch.value;\n"
        "        break;\n"
        "      case 'set_enabled':\n"
        "        el.disabled = !patch.value;\n"
        "        break;\n"
        "      case 'set_value':\n"
        "        if (el.dataset && el.dataset.computable === 'true') {\n"
        "          el.value = patch.value;\n"
        "        }\n"
        "        break;\n"
        "      case 'set_hint':\n"
        "        var hintEl = el.parentNode.querySelector('.form-field__help');\n"
        "        if (hintEl) {\n"
        "          hintEl.textContent = patch.value;\n"
        "        }\n"
        "        break;\n"
        "      case 'narrow_options':\n"
        "        if (el.tagName === 'SELECT') {\n"
        "          var subset = patch.subset || [];\n"
        "          var i = el.options.length - 1;\n"
        "          while (i >= 0) {\n"
        "            if (subset.indexOf(el.options[i].value) === -1) {\n"
        "              el.remove(i);\n"
        "            }\n"
        "            i--;\n"
        "          }\n"
        "        }\n"
        "        break;\n"
        "      default:\n"
        "        console.warn('unhandled patch op', patch.op);\n"
        "    }\n"
        "  }\n"
        "})();\n"
        "</script>\n"
    )
