
function applyOp(rows: Row[], op: Op, frames: Record<string, Row[]>, key: string | null, i: number): Row[] {
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
      return limitOp(rows, op, i);
    case 'derive':
      return deriveOp(rows, op, i);
    case 'group_by':
      return groupByOp(rows, op, frames, i);
    case 'pivot':
      return pivotOp(rows, op, i);
    case 'join':
      return joinOp(rows, op, frames, i);
    case 'union':
      return unionOp(rows, op, frames, i);
    default:
      throw new TransformError(`unknown op '${op.op}'`, key, i);
  }
}
function requireColumns(rows: Row[], columns: string[], opIndex: number, opName: string): void {
  if (rows.length === 0) return;
  const row = rows[0];
  const missing = columns.filter(column => !(column in row));
  if (missing.length > 0) {
    throw new TransformError(`${opName}: unknown column(s) ${JSON.stringify(missing)}; have ${JSON.stringify(Object.keys(row))}`, null, opIndex);
  }
}

function selectOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const columns = op.columns as string[];
  requireColumns(rows, columns, opIndex, 'select');
  return rows.map(row => {
    const newRow: Row = {};
    for (const col of columns) {
      newRow[col] = row[col];
    }
    return newRow;
  });
}

function renameOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const mapping = op.mapping as Record<string, string>;
  const fromColumns = Object.keys(mapping);
  requireColumns(rows, fromColumns, opIndex, 'rename');
  return rows.map(row => {
    const newRow: Row = {};
    for (const [key, value] of Object.entries(row)) {
      const newKey = key in mapping ? mapping[key] : key;
      newRow[newKey] = value;
    }
    return newRow;
  });
}

function filterOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const column = op.column as string;
  const operator = op.operator as string;
  const value = op.value;
  
  if (rows.length === 0) return [];
  requireColumns(rows, [column], opIndex, 'filter');
  
  return rows.filter(row => {
    const cellValue = row[column];
    // null never matches
    if (cellValue === null || cellValue === undefined) return false;
    
    switch (operator) {
      case 'eq': return cellValue === value;
      case 'ne': return cellValue !== value;
      case 'gt': return cellValue > value;
      case 'ge': return cellValue >= value;
      case 'lt': return cellValue < value;
      case 'le': return cellValue <= value;
      case 'in': 
        if (!Array.isArray(value)) {
          throw new TransformError("filter: 'in' requires a list value", null, opIndex);
        }
        return value.includes(cellValue);
      case 'contains':
        if (typeof cellValue === 'string' && typeof value === 'string') {
          return cellValue.includes(value);
        }
        return false;
      default:
        throw new TransformError(`filter: unsupported operator ${operator}`, null, opIndex);
    }
  });
}

function sortOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const by = op.by as Array<{column: string, direction: string}>;
  const columns = by.map(key => key.column);
  
  if (rows.length === 0) return [];
  requireColumns(rows, columns, opIndex, 'sort');
  
  // Make a copy to avoid mutating the original
  let sortedRows = [...rows];
  
  // Process in reverse order for stable sort
  for (let i = by.length - 1; i >= 0; i--) {
    const { column, direction } = by[i];
    sortedRows = sortedRows.sort((a, b) => {
      const aVal = a[column];
      const bVal = b[column];
      
      // nulls last
      if (aVal === null || aVal === undefined) return 1;
      if (bVal === null || bVal === undefined) return -1;
      
      // Handle date strings
      let aComparable = aVal;
      let bComparable = bVal;
      if (typeof aVal === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(aVal)) {
        aComparable = Date.parse(aVal);
      }
      if (typeof bVal === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(bVal)) {
        bComparable = Date.parse(bVal);
      }
      
      if (direction === 'asc') {
        return aComparable < bComparable ? -1 : aComparable > bComparable ? 1 : 0;
      } else {
        return aComparable > bComparable ? -1 : aComparable < bComparable ? 1 : 0;
      }
    });
  }
  
  return sortedRows;
}

function limitOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const n = op.n as number;
  return rows.slice(0, n);
}

function deriveOperand(rows: Row[], expr: any, opIndex: number): any[] | number | string {
  if (typeof expr === 'string') {
    // Column reference
    requireColumns(rows, [expr], opIndex, 'derive');
    // Check if column is numeric
    if (rows.length > 0) {
      const sampleValue = rows[0][expr];
      if (typeof sampleValue !== 'number') {
        throw new TransformError(`derive: column ${JSON.stringify(expr)} is not numeric`, null, opIndex);
      }
    }
    return rows.map(row => row[expr]);
  }
  
  if (typeof expr === 'number') {
    return expr;
  }
  
  // Binary operation
  const left = deriveOperand(rows, expr.left, opIndex);
  const right = deriveOperand(rows, expr.right, opIndex);
  const operator = expr.operator;
  
  const leftArray = Array.isArray(left) ? left : rows.map(() => left);
  const rightArray = Array.isArray(right) ? right : rows.map(() => right);
  
  switch (operator) {
    case '+': return leftArray.map((l, i) => l + rightArray[i]);
    case '-': return leftArray.map((l, i) => l - rightArray[i]);
    case '*': return leftArray.map((l, i) => l * rightArray[i]);
    case '/': 
      return leftArray.map((l, i) => {
        const r = rightArray[i];
        if (r === 0) return null;
        return l / r;
      });
    default:
      throw new TransformError(`derive: unsupported operator ${operator}`, null, opIndex);
  }
}

function deriveOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const name = op.name as string;
  const expr = op.expr;
  
  const result = deriveOperand(rows, expr, opIndex);
  const resultArray = Array.isArray(result) ? result : rows.map(() => result);
  
  return rows.map((row, i) => ({
    ...row,
    [name]: resultArray[i]
  }));
}

function groupByOp(rows: Row[], op: Op, frames: Record<string, Row[]>, opIndex: number): Row[] {
  const by = op.by as string[];
  const aggregate = op.aggregate as Record<string, string>;
  
  requireColumns(rows, [...by, ...Object.keys(aggregate)], opIndex, 'group_by');
  
  if (rows.length === 0) return [];
  
  // Group rows by the 'by' columns
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    // Skip rows with null values in group columns
    if (by.some(col => row[col] === null || row[col] === undefined)) continue;
    
    const key = by.map(col => JSON.stringify(row[col])).join('|');
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(row);
  }
  
  // Aggregate each group
  const result: Row[] = [];
  for (const [groupKey, groupRows] of groups) {
    const firstRow = groupRows[0];
    const newRow: Row = {};
    
    // Copy group by columns
    for (const col of by) {
      newRow[col] = firstRow[col];
    }
    
    // Apply aggregations
    for (const [col, aggFn] of Object.entries(aggregate)) {
      const values = groupRows.map(row => row[col]).filter(v => v !== null && v !== undefined);
      switch (aggFn) {
        case 'sum':
          newRow[col] = values.reduce((a, b) => (a as number) + (b as number), 0);
          break;
        case 'avg':
          newRow[col] = values.length > 0 ? values.reduce((a, b) => (a as number) + (b as number), 0) / values.length : null;
          break;
        case 'count':
          newRow[col] = values.length;
          break;
        case 'min':
          newRow[col] = values.length > 0 ? Math.min(...values as number[]) : null;
          break;
        case 'max':
          newRow[col] = values.length > 0 ? Math.max(...values as number[]) : null;
          break;
        default:
          throw new TransformError(`group_by: unsupported aggregate function ${aggFn}`, null, opIndex);
      }
    }
    
    result.push(newRow);
  }
  
  // Preserve first-appearance order
  return result;
}

function pivotOp(rows: Row[], op: Op, opIndex: number): Row[] {
  const indexCols = op.index as string[];
  const columnsCol = op.columns as string;
  const valuesCol = op.values as string;
  const aggregateFn = op.aggregate as string || 'sum';
  
  requireColumns(rows, [...indexCols, columnsCol, valuesCol], opIndex, 'pivot');
  
  if (rows.length === 0) return [];
  
  // Group by index columns
  const groups = new Map<string, Row[]>();
  for (const row of rows) {
    // Skip rows with null values in index or columns column
    if ([...indexCols, columnsCol].some(col => row[col] === null || row[col] === undefined)) continue;
    
    const key = indexCols.map(col => JSON.stringify(row[col])).join('|');
    if (!groups.has(key)) {
      groups.set(key, []);
    }
    groups.get(key)!.push(row);
  }
  
  // Get unique column values (preserving first appearance order)
  const columnValues: string[] = [];
  const seenColumnValues = new Set<string>();
  for (const row of rows) {
    const colValue = row[columnsCol];
    if (colValue !== null && colValue !== undefined) {
      const strValue = String(colValue);
      if (!seenColumnValues.has(strValue)) {
        seenColumnValues.add(strValue);
        columnValues.push(strValue);
      }
    }
  }
  
  // Build result rows
  const result: Row[] = [];
  for (const [groupKey, groupRows] of groups) {
    const firstRow = groupRows[0];
    const newRow: Row = {};
    
    // Copy index columns
    for (const col of indexCols) {
      newRow[col] = firstRow[col];
    }
    
    // Create pivot columns
    const valueMap = new Map<string, number[]>();
    for (const row of groupRows) {
      const colValue = row[columnsCol];
      const value = row[valuesCol];
      if (colValue !== null && colValue !== undefined && value !== null && value !== undefined) {
        const strColValue = String(colValue);
        if (!valueMap.has(strColValue)) {
          valueMap.set(strColValue, []);
        }
        valueMap.get(strColValue)!.push(Number(value));
      }
    }
    
    // Apply aggregation and populate pivot columns
    for (const colValue of columnValues) {
      const values = valueMap.get(colValue) || [];
      let aggregatedValue: number | null = null;
      
      switch (aggregateFn) {
        case 'sum':
          aggregatedValue = values.reduce((a, b) => a + b, 0);
          break;
        case 'avg':
          aggregatedValue = values.length > 0 ? values.reduce((a, b) => a + b, 0) / values.length : null;
          break;
        case 'count':
          aggregatedValue = values.length;
          break;
        case 'min':
          aggregatedValue = values.length > 0 ? Math.min(...values) : null;
          break;
        case 'max':
          aggregatedValue = values.length > 0 ? Math.max(...values) : null;
          break;
      }
      
      newRow[colValue] = aggregatedValue;
    }
    
    result.push(newRow);
  }
  
  return result;
}

function joinOp(rows: Row[], op: Op, frames: Record<string, Row[]>, opIndex: number): Row[] {
  const withKey = op.with as string;
  const how = op.how as string || 'inner';
  const on = op.on as Array<{left: string, right: string}>;
  
  // Check if sibling frame exists
  if (!(withKey in frames)) {
    throw new TransformError(`join: sibling source ${JSON.stringify(withKey)} was not executed`, null, opIndex);
  }
  
  const rightRows = frames[withKey];
  const leftKeys = on.map(pair => pair.left);
  const rightKeys = on.map(pair => pair.right);
  
  requireColumns(rows, leftKeys, opIndex, 'join');
  requireColumns(rightRows, rightKeys, opIndex, 'join');
  
  // Identify column name collisions for prefixing
  const sameNamedKeys = new Set(rightKeys.filter((rightKey, i) => rightKey === leftKeys[i]));
  const rightOutputColumns = rightRows.length > 0 ? Object.keys(rightRows[0]).filter(col => !sameNamedKeys.has(col)) : [];
  const renamedColumns = new Map<string, string>();
  for (const col of rightOutputColumns) {
    if (rows.length > 0 && col in rows[0]) {
      renamedColumns.set(col, `${withKey}_${col}`);
    }
  }
  
  // Prepare right frame with renamed columns
  const rightWork = rightRows.map(row => {
    const newRow: Row = {};
    for (const [key, value] of Object.entries(row)) {
      const newKey = renamedColumns.get(key) || key;
      newRow[newKey] = value;
    }
    return newRow;
  });
  
  const mergeRightKeys = rightKeys.map(key => renamedColumns.get(key) || key);
  const outputRightColumns = rightOutputColumns.map(col => renamedColumns.get(col) || col);
  
  // Filter out rows with null keys
  const validLeftRows = rows.filter(row => leftKeys.every(key => row[key] !== null && row[key] !== undefined));
  const validRightRows = rightWork.filter(row => mergeRightKeys.every(key => row[key] !== null && row[key] !== undefined));
  
  // Perform join
  let result: Row[] = [];
  
  if (how === 'inner') {
    // Inner join
    for (const leftRow of validLeftRows) {
      const leftValues = leftKeys.map(key => leftRow[key]);
      
      for (const rightRow of validRightRows) {
        const rightValues = mergeRightKeys.map(key => rightRow[key]);
        
        // Check if keys match
        if (leftValues.every((val, i) => val === rightValues[i])) {
          const newRow: Row = { ...leftRow };
          for (const col of outputRightColumns) {
            newRow[col] = rightRow[col];
          }
          result.push(newRow);
        }
      }
    }
  } else if (how === 'left') {
    // Left join
    for (const leftRow of validLeftRows) {
      const leftValues = leftKeys.map(key => leftRow[key]);
      let matched = false;
      
      for (const rightRow of validRightRows) {
        const rightValues = mergeRightKeys.map(key => rightRow[key]);
        
        // Check if keys match
        if (leftValues.every((val, i) => val === rightValues[i])) {
          const newRow: Row = { ...leftRow };
          for (const col of outputRightColumns) {
            newRow[col] = rightRow[col];
          }
          result.push(newRow);
          matched = true;
        }
      }
      
      // If no match found, add left row with nulls for right columns
      if (!matched) {
        const newRow: Row = { ...leftRow };
        for (const col of outputRightColumns) {
          newRow[col] = null;
        }
        result.push(newRow);
      }
    }
    
    // Add rows with null keys from left
    const nullLeftRows = rows.filter(row => !leftKeys.every(key => row[key] !== null && row[key] !== undefined));
    for (const nullRow of nullLeftRows) {
      const newRow: Row = { ...nullRow };
      for (const col of outputRightColumns) {
        newRow[col] = null;
      }
      result.push(newRow);
    }
  }
  
  return result;
}

function unionOp(rows: Row[], op: Op, frames: Record<string, Row[]>, opIndex: number): Row[] {
  const sources = op.sources as string[];
  
  // Get all source frames
  const allFrames: Row[][] = [rows];
  for (const sourceKey of sources) {
    if (!(sourceKey in frames)) {
      throw new TransformError(`union: sibling source ${JSON.stringify(sourceKey)} was not executed`, null, opIndex);
    }
    allFrames.push(frames[sourceKey]);
  }
  
  if (allFrames.length === 0) return [];
  
  // Find column intersection
  let commonColumns: string[] = [];
  if (allFrames[0].length > 0) {
    commonColumns = Object.keys(allFrames[0][0]);
    for (let i = 1; i < allFrames.length; i++) {
      if (allFrames[i].length > 0) {
        const frameColumns = new Set(Object.keys(allFrames[i][0]));
        commonColumns = commonColumns.filter(col => frameColumns.has(col));
      }
    }
  }
  
  // Concatenate frames with common columns
  const result: Row[] = [];
  for (const frame of allFrames) {
    for (const row of frame) {
      const newRow: Row = {};
      for (const col of commonColumns) {
        newRow[col] = row[col];
      }
      result.push(newRow);
    }
  }
  
  return result;
}