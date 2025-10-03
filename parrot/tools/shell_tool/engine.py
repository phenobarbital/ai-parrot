from typing import Optional, Union, Any
import time
import subprocess
import re
import json
from .models import BaseAction, ActionResult


class EvaluationEngine:
    """
    Supports:
        - regex: {"eval_type": "regex", "expr": "pattern", "group": 1}
        - jsonpath (lite): {"eval_type": "jsonpath", "expr": "$.a.b[0]"}
        - jq (requires 'jq' in PATH): {"eval_type": "jq", "expr": ".items[] | .name"}
    """
    @staticmethod
    def eval_regex(text: str, expr: str, group: Optional[Union[int, str]] = None) -> str:
        m = re.search(expr, text, re.MULTILINE | re.DOTALL)
        if not m:
            return ""
        if group is None:
            return m.group(0)
        try:
            return m.group(group)
        except IndexError:
            return ""

    @staticmethod
    def _jsonpath_lite(obj: Any, path: str) -> Any:
        # Very small subset: $.a.b[0].c
        if not path or not path.startswith("$."):
            return None
        cur = obj
        # Split by '.' but keep indices [n]
        tokens = re.findall(r'\.([A-Za-z0-9_]+)|\[(\d+)\]', path[1:])  # skip leading $
        for key, idx in tokens:
            if key:
                if isinstance(cur, dict) and key in cur:
                    cur = cur[key]
                else:
                    return None
            elif idx:
                if isinstance(cur, list):
                    i = int(idx)
                    if 0 <= i < len(cur):
                        cur = cur[i]
                    else:
                        return None
                else:
                    return None
        return cur

    @staticmethod
    def eval_jsonpath(src: Union[str, Any], expr: str, as_json: bool = False) -> str:
        data: Any = src
        if as_json and isinstance(src, str):
            try:
                data = json.loads(src)
            except Exception:
                return ""
        val = EvaluationEngine._jsonpath_lite(data, expr)
        if val is None:
            return ""
        if isinstance(val, (dict, list)):
            return json.dumps(val, ensure_ascii=False)
        return str(val)

    @staticmethod
    def eval_jq(src: Union[str, Any], expr: str, as_json: bool = False) -> str:
        # Requires 'jq' installed
        if isinstance(src, (dict, list)):
            input_str = json.dumps(src)
        elif isinstance(src, str):
            if as_json:
                try:
                    json.loads(src)  # validate
                    input_str = src
                except Exception:
                    input_str = json.dumps(src)
            else:
                input_str = src
        else:
            input_str = json.dumps(src)

        try:
            p = subprocess.run(
                ["jq", "-c", "-M", expr],
                input=input_str.encode(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if p.returncode != 0:
                return ""
            return p.stdout.decode(errors="replace").strip()
        except Exception:
            return ""


class EvalAction(BaseAction):
    """Evaluate an expression using regex, jsonpath, or jq."""
    def __init__(
        self,
        *,
        eval_type: str,
        expr: str,
        group: Optional[Union[int, str]],
        src_text_or_obj: Any,
        as_json: bool,
        work_dir: Optional[str] = None,
        ignore_errors: Optional[bool] = None
    ):
        super().__init__(
            type_name="eval",
            work_dir=work_dir,
            ignore_errors=ignore_errors
        )
        self.eval_type = eval_type
        self.expr = expr
        self.group = group
        self.src = src_text_or_obj
        self.as_json = as_json

    async def _run_impl(self) -> ActionResult:
        started = time.time()
        out = ""
        err = ""
        ok = True
        try:
            if self.eval_type == "regex":
                out = EvaluationEngine.eval_regex(str(self.src), self.expr or "", self.group)
            elif self.eval_type == "jsonpath":
                out = EvaluationEngine.eval_jsonpath(self.src, self.expr or "", as_json=self.as_json)
            elif self.eval_type == "jq":
                out = EvaluationEngine.eval_jq(self.src, self.expr or "", as_json=self.as_json)
            else:
                ok = False
                err = f"Unsupported eval_type: {self.eval_type}"
        except Exception as e:
            ok = False
            err = f"{type(e).__name__}: {e}"
        ended = time.time()
        return ActionResult(
            ok=ok or self.ignore_errors,
            exit_code=0 if ok else 1,
            stdout=(out + ("\n" if out else "")),
            stderr=(err + ("\n" if err else "")),
            started_at=started,
            ended_at=ended,
            duration=ended-started,
            cmd=f"eval({self.eval_type}) {self.expr}",
            work_dir=self.work_dir,
            metadata={"eval_type": self.eval_type},
            type="eval"
        )
