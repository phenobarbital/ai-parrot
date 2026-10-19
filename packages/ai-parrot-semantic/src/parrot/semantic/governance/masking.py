"""Rewrite projected masked columns per MaskRule.strategy (null / md5-hash / partial)."""

from __future__ import annotations

from sqlglot import exp

from ..policy import MaskRule, ModelPolicy
from .lineage import ColumnUse


def _masked_expression(column: exp.Column, rule: MaskRule, dialect: str) -> exp.Expression:
    """Build one dialect-renderable masking expression."""
    source = column.copy()
    if rule.strategy == "null":
        data_type = column.type if isinstance(column.type, exp.DataType) else "TEXT"
        expression: exp.Expression = exp.cast(exp.Null(), data_type)
    elif rule.strategy == "hash":
        expression = exp.MD5(this=exp.cast(source, "TEXT"))
    else:
        length = exp.Length(this=source.copy())
        masked_prefix = exp.Repeat(
            this=exp.Literal.string("*"),
            times=exp.Sub(this=length, expression=exp.Literal.number(4)),
        )
        expression = exp.DPipe(
            this=masked_prefix,
            expression=exp.Right(this=source, expression=exp.Literal.number(4)),
            safe=True,
        )
    expression.sql(dialect=dialect)
    return expression


def apply_masks(
    tree: exp.Expression,
    uses: list[ColumnUse],
    policy: ModelPolicy,
    roles: frozenset[str],
    dialect: str,
) -> tuple[exp.Expression, tuple[str, ...], set[int]]:
    """Rewrite projected masked columns and return their names and trusted node identities."""
    physical_aliases: dict[str, str] = {}
    cte_names = {cte.alias_or_name.casefold() for cte in tree.find_all(exp.CTE)}
    for table in tree.find_all(exp.Table):
        if table.name.casefold() in cte_names and not table.db and not table.catalog:
            continue
        physical_name = ".".join(part for part in (table.catalog, table.db, table.name) if part)
        physical_aliases[table.alias_or_name.casefold()] = physical_name.casefold()
    # RLS push-down wraps a table as `(SELECT * FROM <table> WHERE ...) AS <alias>`: the user's alias now names
    # the subquery, so map it back to the wrapped physical table or masks would silently not apply.
    for subquery in tree.find_all(exp.Subquery):
        inner = subquery.this
        if not (subquery.alias and isinstance(inner, exp.Select) and not inner.args.get("joins")):
            continue
        if len(inner.expressions) != 1 or not isinstance(inner.expressions[0], exp.Star):
            continue
        source = inner.args.get("from_") or inner.args.get("from")
        wrapped = source.this if source is not None else None
        if isinstance(wrapped, exp.Table):
            physical_name = ".".join(part for part in (wrapped.catalog, wrapped.db, wrapped.name) if part)
            physical_aliases[subquery.alias.casefold()] = physical_name.casefold()

    masked_columns: list[str] = []
    trusted_nodes: set[int] = set()
    masked_selections: set[int] = set()
    for use in uses:
        if use.context != "projection":
            continue
        physical_column = f"{use.table}.{use.column}"
        rule = policy.mask_for(roles, physical_column)
        if rule is None:
            continue

        replacements: list[tuple[exp.Expression, exp.Column]] = []
        for select in tree.find_all(exp.Select):
            for selection in select.expressions:
                if id(selection) in masked_selections:
                    continue
                selected = selection.this if isinstance(selection, exp.Alias) else selection
                if not isinstance(selected, exp.Column) or selected.name.casefold() != use.column.casefold():
                    continue
                table_name = physical_aliases.get(selected.table.casefold()) if selected.table else None
                if table_name == use.table.casefold():
                    replacements.append((selection, selected))
        if not replacements:
            continue

        for selection, column in replacements:
            output_name = selection.alias_or_name or column.name
            quoted = isinstance(selection.args.get("alias"), exp.Identifier) and selection.args["alias"].quoted
            masked = exp.alias_(_masked_expression(column, rule, dialect), output_name, quoted=quoted)
            selection.replace(masked)
            masked_selections.add(id(masked))
            trusted_nodes.update(id(node) for node in masked.walk())
        masked_columns.append(physical_column)

    return tree, tuple(masked_columns), trusted_nodes
