// examples/a2ui/static/dsl.js
// Transform DSL v1 — vanilla port of the admin UI's `linked/dsl.ts` (itself the TS twin of the Python reference
// executor `parrot/outputs/a2ui/linked/dsl.py`). Op-for-op, so the shared golden fixtures under
// `contract/fixtures/dsl/` pass here too. Pure: no I/O; inputs are never mutated.
//
// Linked dashboards use it for two things: a source-level `transform.ops` applied to a fetched frame, and a
// `kind: "derived"` source computed from a sibling's frame (e.g. a category aggregation of the rows a grid shows).

/** A DSL op failed: missing column, derive type mismatch, absent join key, … */
export class TransformError extends Error {
  constructor(message, key, opIndex) {
    super(message);
    this.name = 'TransformError';
    this.key = key;
    this.opIndex = opIndex;
  }
}

/** Apply `spec.ops` in order over `rows` (`frames` holds the already-executed sibling frames for join/union). */
export function applyTransform(rows, spec, frames = {}) {
  if (!spec) return rows;
  let out = rows;
  const ops = spec.ops ?? [];
  for (let i = 0; i < ops.length; i++) out = applyOp(out, ops[i], frames, i);
  return out;
}

function applyOp(rows, op, frames, i) {
  switch (op.op) {
    case 'select':
      return selectOp(rows, op, i);
    case 'rename':
      return renameOp(rows, op, i);
    case 'filter':
      return filterOp(rows, op, i);
    case 'sort':
      return sortOp(rows, op, i);
    case 'limit':
      return rows.slice(0, op.n);
    case 'derive':
      return deriveOp(rows, op, i);
    case 'group_by':
      return groupByOp(rows, op, i);
    case 'pivot':
      return pivotOp(rows, op, i);
    case 'join':
      return joinOp(rows, op, frames, i);
    case 'union':
      return unionOp(rows, op, frames, i);
    default:
      throw new TransformError(`unknown op '${op.op}'`, null, i);
  }
}

function requireColumns(rows, columns, opIndex, opName) {
  if (rows.length === 0) return;
  const row = rows[0];
  const missing = columns.filter((column) => !(column in row));
  if (missing.length > 0) {
    throw new TransformError(
      `${opName}: unknown column(s) ${JSON.stringify(missing)}; have ${JSON.stringify(Object.keys(row))}`,
      null,
      opIndex,
    );
  }
}

const isMissing = (v) => v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v));

function selectOp(rows, op, opIndex) {
  requireColumns(rows, op.columns, opIndex, 'select');
  return rows.map((row) => Object.fromEntries(op.columns.map((col) => [col, row[col]])));
}

function renameOp(rows, op, opIndex) {
  requireColumns(rows, Object.keys(op.mapping), opIndex, 'rename');
  return rows.map((row) => {
    const out = {};
    for (const [key, value] of Object.entries(row)) out[key in op.mapping ? op.mapping[key] : key] = value;
    return out;
  });
}

function filterOp(rows, op, opIndex) {
  if (rows.length === 0) return [];
  requireColumns(rows, [op.column], opIndex, 'filter');
  const { operator, value } = op;
  return rows.filter((row) => {
    const cell = row[op.column];
    if (cell === null || cell === undefined) return false; // null never matches
    switch (operator) {
      case 'eq':
        return cell === value;
      case 'ne':
        return cell !== value;
      case 'gt':
        return cell > value;
      case 'ge':
        return cell >= value;
      case 'lt':
        return cell < value;
      case 'le':
        return cell <= value;
      case 'in':
        if (!Array.isArray(value)) throw new TransformError("filter: 'in' requires a list value", null, opIndex);
        return value.includes(cell);
      case 'contains':
        return typeof cell === 'string' && typeof value === 'string' && cell.includes(value);
      default:
        throw new TransformError(`filter: unsupported operator ${operator}`, null, opIndex);
    }
  });
}

const ISO_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/;

function sortOp(rows, op, opIndex) {
  if (rows.length === 0) return [];
  requireColumns(rows, op.by.map((key) => key.column), opIndex, 'sort');
  let sorted = [...rows];
  for (let i = op.by.length - 1; i >= 0; i--) {
    const { column, direction } = op.by[i];
    sorted = sorted.sort((a, b) => {
      const av = a[column];
      const bv = b[column];
      if (av === null || av === undefined) return 1; // nulls last
      if (bv === null || bv === undefined) return -1;
      const ac = typeof av === 'string' && ISO_DATETIME.test(av) ? Date.parse(av) : av;
      const bc = typeof bv === 'string' && ISO_DATETIME.test(bv) ? Date.parse(bv) : bv;
      if (direction === 'asc') return ac < bc ? -1 : ac > bc ? 1 : 0;
      return ac > bc ? -1 : ac < bc ? 1 : 0;
    });
  }
  return sorted;
}

function deriveOperand(rows, expr, opIndex) {
  if (typeof expr === 'string') {
    requireColumns(rows, [expr], opIndex, 'derive');
    if (rows.length > 0 && typeof rows[0][expr] !== 'number') {
      throw new TransformError(`derive: column ${JSON.stringify(expr)} is not numeric`, null, opIndex);
    }
    return rows.map((row) => row[expr]);
  }
  if (typeof expr === 'number') return expr;
  const left = deriveOperand(rows, expr.left, opIndex);
  const right = deriveOperand(rows, expr.right, opIndex);
  const leftArray = Array.isArray(left) ? left : rows.map(() => left);
  const rightArray = Array.isArray(right) ? right : rows.map(() => right);
  const binary = (fn) => leftArray.map((l, i) => (isMissing(l) || isMissing(rightArray[i]) ? null : fn(l, rightArray[i])));
  switch (expr.operator) {
    case '+':
      return binary((l, r) => l + r);
    case '-':
      return binary((l, r) => l - r);
    case '*':
      return binary((l, r) => l * r);
    case '/':
      return binary((l, r) => (r === 0 ? null : l / r));
    default:
      throw new TransformError(`derive: unsupported operator ${expr.operator}`, null, opIndex);
  }
}

function deriveOp(rows, op, opIndex) {
  const result = deriveOperand(rows, op.expr, opIndex);
  const values = Array.isArray(result) ? result : rows.map(() => result);
  return rows.map((row, i) => ({ ...row, [op.name]: values[i] }));
}

function aggregateValues(fn, values, opIndex, opName) {
  switch (fn) {
    case 'sum':
      return values.reduce((a, b) => a + b, 0);
    case 'avg':
      return values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : null;
    case 'count':
      return values.length;
    case 'min':
      return values.length > 0 ? Math.min(...values) : null;
    case 'max':
      return values.length > 0 ? Math.max(...values) : null;
    default:
      throw new TransformError(`${opName}: unsupported aggregate function ${fn}`, null, opIndex);
  }
}

function groupByOp(rows, op, opIndex) {
  requireColumns(rows, [...op.by, ...Object.keys(op.aggregate)], opIndex, 'group_by');
  if (rows.length === 0) return [];
  const groups = new Map(); // first-appearance order; rows with a null group key are dropped (pandas dropna)
  for (const row of rows) {
    if (op.by.some((col) => row[col] === null || row[col] === undefined)) continue;
    const key = op.by.map((col) => JSON.stringify(row[col])).join('|');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const out = [];
  for (const groupRows of groups.values()) {
    const row = {};
    for (const col of op.by) row[col] = groupRows[0][col];
    for (const [col, fn] of Object.entries(op.aggregate)) {
      const values = groupRows.map((r) => r[col]).filter((v) => v !== null && v !== undefined);
      row[col] = aggregateValues(fn, values, opIndex, 'group_by');
    }
    out.push(row);
  }
  return out;
}

function pivotOp(rows, op, opIndex) {
  const aggregate = op.aggregate || 'sum';
  requireColumns(rows, [...op.index, op.columns, op.values], opIndex, 'pivot');
  if (rows.length === 0) return [];
  const groups = new Map();
  for (const row of rows) {
    if ([...op.index, op.columns].some((col) => row[col] === null || row[col] === undefined)) continue;
    const key = op.index.map((col) => JSON.stringify(row[col])).join('|');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const columnValues = [];
  for (const row of rows) {
    const v = row[op.columns];
    if (v !== null && v !== undefined && !columnValues.includes(String(v))) columnValues.push(String(v));
  }
  const out = [];
  for (const groupRows of groups.values()) {
    const row = {};
    for (const col of op.index) row[col] = groupRows[0][col];
    const cells = new Map();
    for (const r of groupRows) {
      const c = r[op.columns];
      const v = r[op.values];
      if (c === null || c === undefined || v === null || v === undefined) continue;
      if (!cells.has(String(c))) cells.set(String(c), []);
      cells.get(String(c)).push(Number(v));
    }
    for (const c of columnValues) {
      const values = cells.get(c) || [];
      row[c] = values.length === 0 ? null : aggregateValues(aggregate, values, opIndex, 'pivot'); // missing cell → null
    }
    out.push(row);
  }
  return out;
}

function joinOp(rows, op, frames, opIndex) {
  const withKey = op.with;
  const how = op.how || 'inner';
  if (!(withKey in frames)) {
    throw new TransformError(`join: sibling source ${JSON.stringify(withKey)} was not executed`, null, opIndex);
  }
  const rightRows = frames[withKey];
  const leftKeys = op.on.map((pair) => pair.left);
  const rightKeys = op.on.map((pair) => pair.right);
  requireColumns(rows, leftKeys, opIndex, 'join');
  requireColumns(rightRows, rightKeys, opIndex, 'join');
  const sameNamed = new Set(rightKeys.filter((k, i) => k === leftKeys[i]));
  const rightOutput = rightRows.length > 0 ? Object.keys(rightRows[0]).filter((c) => !sameNamed.has(c)) : [];
  const renamed = new Map();
  for (const col of rightOutput) if (rows.length > 0 && col in rows[0]) renamed.set(col, `${withKey}_${col}`);
  const rightWork = rightRows.map((row) => Object.fromEntries(Object.entries(row).map(([k, v]) => [renamed.get(k) || k, v])));
  const mergeRightKeys = rightKeys.map((k) => renamed.get(k) || k);
  const outputRight = rightOutput.map((c) => renamed.get(c) || c);
  const validKeys = (row, keys) => keys.every((k) => row[k] !== null && row[k] !== undefined);
  const validLeft = rows.filter((row) => validKeys(row, leftKeys));
  const validRight = rightWork.filter((row) => validKeys(row, mergeRightKeys));
  const out = [];
  for (const leftRow of validLeft) {
    const leftValues = leftKeys.map((k) => leftRow[k]);
    let matched = false;
    for (const rightRow of validRight) {
      if (leftValues.every((v, i) => v === rightRow[mergeRightKeys[i]])) {
        const row = { ...leftRow };
        for (const col of outputRight) row[col] = rightRow[col];
        out.push(row);
        matched = true;
      }
    }
    if (how === 'left' && !matched) {
      const row = { ...leftRow };
      for (const col of outputRight) row[col] = null;
      out.push(row);
    }
  }
  if (how === 'left') {
    for (const nullRow of rows.filter((row) => !validKeys(row, leftKeys))) {
      const row = { ...nullRow };
      for (const col of outputRight) row[col] = null;
      out.push(row);
    }
  }
  return out;
}

function unionOp(rows, op, frames, opIndex) {
  const all = [rows];
  for (const key of op.sources) {
    if (!(key in frames)) throw new TransformError(`union: sibling source ${JSON.stringify(key)} was not executed`, null, opIndex);
    all.push(frames[key]);
  }
  let common = all[0].length > 0 ? Object.keys(all[0][0]) : [];
  for (const frame of all.slice(1)) {
    if (frame.length > 0) {
      const cols = new Set(Object.keys(frame[0]));
      common = common.filter((c) => cols.has(c));
    }
  }
  const out = [];
  for (const frame of all) for (const row of frame) out.push(Object.fromEntries(common.map((c) => [c, row[c]])));
  return out;
}
