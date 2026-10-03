"""Export rule pack — lint the exported markdown/OKF wiki (FEAT-625)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult, Severity
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.wiki.export import export_okf_bundle

logger = logging.getLogger(__name__)


class ExportFrontmatter(BaseModel):
    """Schema of the frontmatter written by ``wiki.export.page_frontmatter``."""

    type: str
    title: str
    id: str
    tags: list[str]
    timestamp: str
    summary: str | None = None
    relates_to: list[dict[str, str]] | None = None


def _read_export(export_dir: Path) -> dict[str, dict[str, Any]]:
    """Return ``{path: {"meta": dict|None, "error": str|None}}`` for every page file (sync; run in a thread)."""
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(export_dir.rglob("*.md")):
        if path.name == "index.md":
            continue
        rel = path.relative_to(export_dir).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result[rel] = {"meta": None, "error": f"unreadable: {exc}"}
            continue
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            result[rel] = {"meta": None, "error": "missing frontmatter"}
            continue
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            result[rel] = {"meta": None, "error": "unterminated frontmatter"}
            continue
        try:
            meta = yaml.safe_load("\n".join(lines[1:end]))
        except yaml.YAMLError as exc:
            result[rel] = {"meta": None, "error": f"invalid YAML: {exc}"}
            continue
        if not isinstance(meta, dict):
            result[rel] = {"meta": None, "error": "frontmatter is not a mapping"}
            continue
        result[rel] = {"meta": meta, "error": None}
    return result


def _read_export_if_dir(export_dir: Path) -> dict[str, dict[str, Any]] | None:
    """Return the parsed export, or None when the directory is missing (sync; run in a thread)."""
    return _read_export(export_dir) if export_dir.is_dir() else None


async def _export(ctx: LintContext) -> dict[str, dict[str, Any]] | None:
    export_dir = ctx.options.export_dir
    if export_dir is None:
        return None
    if "export" not in ctx.extras:
        ctx.extras["export"] = await asyncio.to_thread(_read_export_if_dir, Path(export_dir))
    return ctx.extras["export"]


def _finding(rule_id: str, severity: Severity, subjects: list[str], message: str, **kw: Any) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        subjects=subjects,
        message=message,
        fingerprint=make_fingerprint(rule_id, subjects),
        **kw,
    )


class FrontmatterSchemaRule:
    """Validate each exported page's frontmatter against :class:`ExportFrontmatter`."""

    rule_id, pack, default_severity = "frontmatter-schema", "export", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        export = await _export(ctx)
        if export is None:
            return [
                _finding(
                    "export-missing",
                    "info",
                    ["export"],
                    "No export directory configured or found; export rules skipped.",
                )
            ]
        findings: list[Finding] = []
        for rel, entry in export.items():
            if entry["error"] is not None:
                findings.append(_finding(self.rule_id, "error", [rel], f"{rel}: {entry['error']}"))
                continue
            try:
                ExportFrontmatter.model_validate(entry["meta"])
            except ValidationError as exc:
                detail = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
                findings.append(_finding(self.rule_id, "error", [rel], f"{rel}: invalid frontmatter ({detail})"))
        return findings

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """This rule never fixes."""
        return None


class ExportDriftRule:
    """Detect export files that drifted from the plane (missing, extra, or stale timestamp)."""

    rule_id, pack, default_severity = "export-drift", "export", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        export = await _export(ctx)
        if export is None:
            return []
        exported: dict[str, str] = {}
        for entry in export.values():
            meta = entry["meta"]
            if meta and meta.get("id") is not None:
                exported[str(meta["id"])] = str(meta.get("timestamp") or "")
        pages = {str(p["concept_id"]): str(p.get("updated_at") or "") for p in await ctx.pages()}
        findings: list[Finding] = []
        for cid in sorted(pages.keys() - exported.keys()):
            findings.append(
                _finding(
                    self.rule_id,
                    "warning",
                    [cid],
                    f"Page '{cid}' is not in the export.",
                    fixable=True,
                    data={"kind": "missing"},
                )
            )
        for cid in sorted(exported.keys() - pages.keys()):
            findings.append(
                _finding(
                    self.rule_id,
                    "warning",
                    [cid],
                    f"Exported page '{cid}' no longer exists in the plane.",
                    fixable=True,
                    data={"kind": "extra"},
                )
            )
        for cid in sorted(pages.keys() & exported.keys()):
            if pages[cid] != exported[cid]:
                findings.append(
                    _finding(
                        self.rule_id,
                        "warning",
                        [cid],
                        f"Export timestamp for '{cid}' differs from the plane updated_at.",
                        fixable=True,
                        data={"kind": "timestamp"},
                    )
                )
        return findings

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        """Re-export the bundle through the real exporter (once per run)."""
        if ctx.extras.get("export_refreshed"):
            return FixResult(fingerprint=finding.fingerprint, applied=True, detail="already re-exported")
        export_dir = ctx.options.export_dir
        if export_dir is None:
            return FixResult(fingerprint=finding.fingerprint, applied=False, detail="no export dir")
        wiki_name = getattr(ctx.store, "wiki_name", "")
        await export_okf_bundle(ctx.store, Path(export_dir), wiki_name if isinstance(wiki_name, str) else "")
        ctx.extras.pop("export", None)
        ctx.extras["export_refreshed"] = True
        return FixResult(fingerprint=finding.fingerprint, applied=True, detail="re-exported bundle")


class ExportDanglingRelatesToRule:
    """Flag ``relates_to`` entries whose target is not a plane page."""

    rule_id, pack, default_severity = "export-dangling-relates-to", "export", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        export = await _export(ctx)
        if export is None:
            return []
        ids = await ctx.page_ids()
        findings: list[Finding] = []
        for rel, entry in export.items():
            meta = entry["meta"]
            if not meta:
                continue
            relates = meta.get("relates_to")
            if not isinstance(relates, list):
                continue
            for item in relates:
                target = item.get("concept") if isinstance(item, dict) else None
                if target is not None and str(target) not in ids:
                    subjects = [rel, str(target)]
                    findings.append(
                        _finding(
                            self.rule_id,
                            "error",
                            subjects,
                            f"{rel}: relates_to target '{target}' is not a page.",
                            data={"target": str(target)},
                        )
                    )
        return findings

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        """This rule never fixes."""
        return None


EXPORT_RULES = [FrontmatterSchemaRule, ExportDriftRule, ExportDanglingRelatesToRule]
