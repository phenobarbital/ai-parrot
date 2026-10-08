#!/bin/bash
REPO_ROOT="$(pwd)"
MODEL="${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}"
DR="$1"
SKIP_REASON=""
timeout 120 codex exec --ephemeral --sandbox read-only -m "$MODEL" \
  -c model_reasoning_effort=high --ignore-user-config \
  -o "$DR/probe.txt" "Reply with exactly the single word OK." < /dev/null >/dev/null 2>&1 \
  || SKIP_REASON="model probe failed for $MODEL (rc=$?)"
if [ -z "$SKIP_REASON" ]; then
  PROBE_TEXT="$(cat "$DR/probe.txt" 2>/dev/null | tr -d '[:space:]')"
  [ "$PROBE_TEXT" = "OK" ] || SKIP_REASON="model probe returned unexpected output for $MODEL"
fi
CODEX_VERSION="$(codex --version 2>/dev/null | awk '{print $2}')"
python -c "
import json, sys
json.dump({'model': sys.argv[1], 'codex_cli_version': sys.argv[2], 'reasoning_effort': 'high',
           'timeout_s': 600, 'probe_output': open(sys.argv[3]).read() if __import__('os').path.exists(sys.argv[3]) else ''},
          open(sys.argv[4], 'w'), indent=2)
" "$MODEL" "$CODEX_VERSION" "$DR/probe.txt" "$DR/run.json"
if [ -z "$SKIP_REASON" ]; then
  python - "$DR" <<'PY' || SKIP_REASON="brief rendering failed"
import sys
from pathlib import Path
dr = Path(sys.argv[1])
template = Path("sdd/templates/design_research.prompt.md").read_text(encoding="utf-8")
names = ["problem_statement", "constraints_and_goals", "recommended_option_or_scope",
         "code_context_paths", "open_questions", "question"]
for name in names:
    value = (dr / f"{name}.txt").read_text(encoding="utf-8").strip()
    template = template.replace("{{" + name + "}}", value)
assert "{{" not in template, "unfilled placeholder remains"
(dr / "brief.md").write_text(template, encoding="utf-8")
PY
fi
if [ -z "$SKIP_REASON" ]; then
  STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
  timeout 600 codex exec --ephemeral --sandbox read-only --cd "$REPO_ROOT" \
    -m "$MODEL" -c model_reasoning_effort=high --ignore-user-config \
    --output-schema sdd/templates/design_research.schema.json \
    -o "$DR/suggestions.json" - < "$DR/brief.md" > "$DR/codex.log" 2>&1
  rc=$?
  [ "$rc" -eq 124 ] && SKIP_REASON="codex timed out after 600s"
  [ "$rc" -ne 0 ] && [ -z "$SKIP_REASON" ] && SKIP_REASON="codex exited $rc (see $DR/codex.log)"
  ENDED_AT="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
  python -c "
import json, sys
d = json.load(open(sys.argv[1])); d['started_at']=sys.argv[2]; d['ended_at']=sys.argv[3]; d['exit_code']=int(sys.argv[4])
json.dump(d, open(sys.argv[1], 'w'), indent=2)" "$DR/run.json" "$STARTED_AT" "$ENDED_AT" "$rc"
fi
if [ -z "$SKIP_REASON" ]; then
  python -c "
import json, jsonschema
s = json.load(open('sdd/templates/design_research.schema.json'))
d = json.load(open('$DR/suggestions.json'))
jsonschema.Draft202012Validator(s).validate(d)
print(len(d['suggestions']), 'suggestions')" || SKIP_REASON="suggestions.json failed schema validation"
fi
echo "${SKIP_REASON:-OK}" > "$DR/STATUS"
