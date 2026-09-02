"""Probe: can declarative ast-grep rules reproduce the scanners' outlines, and
does the rewrite path (replace + commit_edits) work as the design assumes?"""
from ast_grep_py import SgRoot, SgNode
import yaml, json

SAMPLES = {
"python": '''"""Module doc."""
import os
from parrot.tools import AbstractTool

class UserService(BaseService):
    """Main service class."""
    async def get_user(self, user_id: int) -> dict:
        """Fetch a user."""
        return {}

def helper(a, b=1):
    """Utility helper."""
    return a
''',
"typescript": '''/** Main service class. */
export class UserService {
  /** Create a user. */
  async createUser(name: string, email: string): Promise<User> { return null; }
}
/** Create a new user. */
export function createUser(name, email) {}
function internalHelper(x) {}
/** Shape of a user row. */
export interface UserRecord { id: number }
/** Request timeout in ms. */
export const DEFAULT_TIMEOUT = 30;
export type Id = string;
import { foo } from "./foo";
''',
"php": '''<?php
namespace App\\Models;
use App\\Contracts\\Serializable;
/** Represents an application user. */
class User extends Model implements Serializable {
    /** Get the full name. */
    public function getFullName($prefix = '') { return $prefix; }
}
interface Serializable {}
trait HasTimestamps {}
enum Status: string { case Active = 'a'; }
/** Utility helper. */
function helper_function($a, $b) {}
''',
"rust": '''use std::collections::HashMap;
/// A document parser.
#[derive(Debug)]
pub struct Parser { cfg: Config }
impl Parser {
    /// Create a parser.
    pub fn new(config: Config) -> Self { todo!() }
    fn private_helper(&self) {}
}
/// Visits every node.
pub trait Visitor { fn visit(&self); }
pub mod utils;
pub enum Kind { A, B }
fn not_pub() {}
''',
}

# ---- Rule files: one per language, kind-based, with metavariables for name
RULES = {
"python": """
symbols:
  - id: class
    rule: { kind: class_definition }
    name_field: name
    doc: first_docstring
  - id: function
    rule:
      kind: function_definition
      not: { inside: { kind: class_definition, stopBy: end } }
    name_field: name
    doc: first_docstring
  - id: method
    rule:
      kind: function_definition
      inside: { kind: class_definition, stopBy: end }
    name_field: name
    parent_kind: class_definition
    doc: first_docstring
imports:
  - rule: { kind: import_statement }
  - rule: { kind: import_from_statement }
""",
"typescript": """
symbols:
  - id: class
    rule: { kind: class_declaration }
    name_field: name
    doc: leading_comment
    exported_if_inside: export_statement
  - id: function
    rule: { kind: function_declaration }
    name_field: name
    doc: leading_comment
    exported_if_inside: export_statement
  - id: method
    rule: { kind: method_definition, inside: { kind: class_body } }
    name_field: name
    parent_kind: class_declaration
    doc: leading_comment
  - id: interface
    rule: { kind: interface_declaration }
    name_field: name
    doc: leading_comment
    exported_if_inside: export_statement
  - id: type
    rule: { kind: type_alias_declaration }
    name_field: name
    exported_if_inside: export_statement
  - id: const
    rule: { kind: lexical_declaration, inside: { kind: export_statement } }
    name_path: [variable_declarator, name]
    doc: leading_comment
    exported_if_inside: export_statement
imports:
  - rule: { kind: import_statement }
""",
"php": """
symbols:
  - id: class
    rule: { kind: class_declaration }
    name_field: name
    doc: leading_comment
  - id: interface
    rule: { kind: interface_declaration }
    name_field: name
  - id: trait
    rule: { kind: trait_declaration }
    name_field: name
  - id: enum
    rule: { kind: enum_declaration }
    name_field: name
  - id: method
    rule: { kind: method_declaration }
    name_field: name
    parent_kind: class_declaration
    doc: leading_comment
  - id: function
    rule: { kind: function_definition }
    name_field: name
    doc: leading_comment
imports:
  - rule: { kind: namespace_use_declaration }
""",
"rust": """
symbols:
  - id: struct
    rule: { kind: struct_item, has: { kind: visibility_modifier } }
    name_field: name
    doc: leading_doc_comment
  - id: enum
    rule: { kind: enum_item, has: { kind: visibility_modifier } }
    name_field: name
    doc: leading_doc_comment
  - id: trait
    rule: { kind: trait_item, has: { kind: visibility_modifier } }
    name_field: name
    doc: leading_doc_comment
  - id: mod
    rule: { kind: mod_item, has: { kind: visibility_modifier } }
    name_field: name
  - id: impl
    rule: { kind: impl_item }
    name_field: type
  - id: fn
    rule:
      kind: function_item
      any:
        - has: { kind: visibility_modifier }
        - inside: { kind: impl_item, stopBy: end }
    name_field: name
    parent_kind: impl_item
    doc: leading_doc_comment
imports:
  - rule: { kind: use_declaration }
""",
}

DOC_KINDS = {"comment", "line_comment", "block_comment"}

def leading_comment(n: SgNode):
    p = n.parent()
    # exported decl: the comment precedes the export_statement wrapper
    probe = p if p is not None and p.kind() == "export_statement" else n
    prev = probe.prev()
    while prev is not None and prev.kind() in {"attribute_item"}:
        prev = prev.prev()
    if prev is not None and prev.kind() in DOC_KINDS:
        return prev.text().strip("/* \n").splitlines()[0].strip("* /")
    return ""

def first_docstring(n: SgNode):
    body = n.field("body")
    if body is None:
        return ""
    first = body.child(0)
    if first is not None and first.kind() == "expression_statement":
        s = first.child(0)
        if s is not None and s.kind() == "string":
            return s.text().strip('"\' \n').splitlines()[0]
    return ""

DOC = {"leading_comment": leading_comment, "leading_doc_comment": leading_comment,
       "first_docstring": first_docstring}

def name_of(n: SgNode, spec):
    if "name_field" in spec:
        f = n.field(spec["name_field"])
        return f.text() if f else "?"
    node = n
    for k in spec["name_path"]:
        node = node.find(kind=k) if not node.field(k) else node.field(k)
    return node.text()

def extract(lang, src):
    root = SgRoot(src, lang).root()
    rules = yaml.safe_load(RULES[lang])
    out = []
    for spec in rules["symbols"]:
        for m in root.find_all({"rule": spec["rule"]}):
            r = m.range()
            exported = False
            if "exported_if_inside" in spec:
                p = m.parent()
                exported = p is not None and p.kind() == spec["exported_if_inside"]
            parent = None
            if "parent_kind" in spec:
                anc = [a for a in m.ancestors() if a.kind() == spec["parent_kind"]]
                if anc:
                    pn = anc[0].field("name") or anc[0].field("type")
                    parent = pn.text() if pn else None
            doc = DOC[spec["doc"]](m) if "doc" in spec else ""
            out.append(dict(kind=spec["id"], name=name_of(m, spec), parent=parent,
                            exported=exported, doc=doc,
                            start=(r.start.line + 1, r.start.column), end=(r.end.line + 1, r.end.column),
                            byte_range=(r.start.index, r.end.index)))
    imports = [m.text() for spec in rules["imports"] for m in root.find_all({"rule": spec["rule"]})]
    return out, imports

for lang, src in SAMPLES.items():
    print(f"\n=== {lang}")
    syms, imps = extract(lang, src)
    for s in sorted(syms, key=lambda s: s["byte_range"]):
        print(f"  {s['kind']:9} {s['name']:16} parent={s['parent']!s:12} exp={s['exported']!s:5} L{s['start'][0]}-{s['end'][0]}  doc={s['doc']!r}")
    print("  imports:", imps)

# ---- Rewrite path: pattern with metavariables, preview, then commit
print("\n=== rewrite (python): rename helper() call sites + def, preview then commit")
src = SAMPLES["python"] + "\nx = helper(1, b=2)\ny = obj.helper(3)\n"
root = SgRoot(src, "python").root()
edits = []
for m in root.find_all(pattern="helper($$$ARGS)"):
    edits.append(m.replace(f"utility_helper({m.get_multiple_matches('ARGS') and ', '.join(a.text() for a in m.get_multiple_matches('ARGS'))})"))
for m in root.find_all({"rule": {"kind": "function_definition", "has": {"field": "name", "regex": "^helper$"}}}):
    nm = m.field("name")
    edits.append(nm.replace("utility_helper"))
print("  edits:", [(e.start_pos, e.end_pos, e.inserted_text) for e in edits])
new_src = root.commit_edits(edits)
print("  preview diff lines:")
import difflib
for line in difflib.unified_diff(src.splitlines(), new_src.splitlines(), lineterm="", n=0):
    print("   ", line)
# ---- YAML rule with fix + transform through Config (rewrite via get_transformed)
print("\n=== rule with fix via Config (typescript): console.log -> logger.info")
ts = 'console.log("a", x);\nconsole.log(y);\n'
root = SgRoot(ts, "typescript").root()
cfg = {"rule": {"pattern": "console.log($$$A)"}}
ms = root.find_all(cfg)
print("  matches:", [m.text() for m in ms])
