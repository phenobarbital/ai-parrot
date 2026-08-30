import { browser } from "$app/environment";
import {
  applyComputedColumns,
  colIndexToLetter,
  evaluateFormula,
  type AggregationType,
  type ComputedColumn,
  type FormulaMap,
  type RollUpRow,
} from "./formulas";

export interface GridStateOptions {
  persistKey: string;
  tenantPrefix?: string;
}

export class GridState {
  // Feature toggles
  editMode = $state(false);
  dragEnabled = $state(false);
  filterEnabled = $state(false);
  groupingEnabled = $state(false);
  formulaBarVisible = $state(false);

  // Grouping state
  groupDropdownOpen = $state(false);
  groupParentCol = $state<string | null>(null);
  groupChildCols = $state<Set<string>>(new Set());

  // Computed + rollups
  computedColumns = $state<ComputedColumn[]>([]);
  rollUpRows = $state<RollUpRow[]>([]);
  sigmaCounter = $state(0);

  // Sigma dropdown
  sigmaDropdownOpen = $state(false);
  sigmaStep = $state<"menu" | "column-select">("menu");
  sigmaAction = $state<"computed" | "rollup" | null>(null);
  sigmaAggType = $state<AggregationType | null>(null);
  sigmaSelectedCols = $state<Set<string>>(new Set());

  // Formula state
  formulas = $state<FormulaMap>(new Map());
  selectedRow = $state(-1);
  selectedCol = $state(-1);
  formulaInput = $state("");

  // Data
  localRows = $state<Record<string, unknown>[]>([]);

  // Private constructor options — declared before $derived fields that reference them
  #persistKey: string = "";
  #tenantPrefix: string | undefined = undefined;

  // Derived fields
  selectedCellRef = $derived(
    this.selectedRow >= 0 && this.selectedCol >= 0
      ? `${colIndexToLetter(this.selectedCol)}${this.selectedRow + 1}`
      : "",
  );
  columnKeys = $derived<string[]>(
    this.localRows.length > 0 ? Object.keys(this.localRows[0]) : [],
  );
  hasData = $derived(this.localRows.length > 0);
  displayRows = $derived(
    applyComputedColumns(this.localRows, this.computedColumns),
  );
  storageKey = $derived(
    this.#tenantPrefix
      ? `${this.#tenantPrefix}:${this.#persistKey}`
      : this.#persistKey,
  );

  constructor(options: GridStateOptions) {
    this.#persistKey = options.persistKey;
    this.#tenantPrefix = options.tenantPrefix;
    // Grid-level changes (computed columns, roll-ups, formulas) are intentionally
    // ephemeral — they must NOT survive navigation, reloads, or be persisted in any
    // store. Clear any state left behind by older builds that did persist it.
    this.purgeLegacyPersistedState();
  }

  resetRows(rows: Record<string, unknown>[]): void {
    this.localRows = rows;
  }

  toggleEdit(): void {
    this.editMode = !this.editMode;
  }

  toggleDrag(): void {
    this.dragEnabled = !this.dragEnabled;
  }

  toggleFilter(): void {
    this.filterEnabled = !this.filterEnabled;
  }

  toggleGrouping(): void {
    this.groupingEnabled = !this.groupingEnabled;
  }

  toggleFormulaBar(): void {
    this.formulaBarVisible = !this.formulaBarVisible;
  }

  clearGrouping(): void {
    this.groupParentCol = null;
    this.groupChildCols = new Set();
  }

  selectParentCol(key: string): void {
    if (this.groupParentCol === key) {
      this.groupParentCol = null;
      this.groupChildCols = new Set();
    } else {
      this.groupParentCol = key;
      this.groupChildCols = new Set(this.columnKeys.filter((k) => k !== key));
    }
  }

  toggleChildCol(key: string): void {
    const next = new Set(this.groupChildCols);
    if (next.has(key)) {
      next.delete(key);
    } else {
      next.add(key);
    }
    this.groupChildCols = next;
  }

  handleAfterFocus(rowIndex: number, prop: string, colIndex: number): void {
    this.selectedRow = rowIndex;
    this.selectedCol = colIndex;

    const key = `${this.selectedRow}:${this.selectedCol}`;
    const entry = this.formulas.get(key);
    if (entry) {
      this.formulaInput = entry.formula;
    } else if (
      this.selectedRow >= 0 &&
      this.selectedRow < this.localRows.length &&
      this.selectedCol >= 0 &&
      this.selectedCol < this.columnKeys.length
    ) {
      const val =
        this.localRows[this.selectedRow][this.columnKeys[this.selectedCol]];
      this.formulaInput = val != null ? String(val) : "";
    }
  }

  submitFormula(): void {
    if (this.selectedRow < 0 || this.selectedCol < 0) return;
    const key = `${this.selectedRow}:${this.selectedCol}`;

    if (this.formulaInput.startsWith("=")) {
      const result = evaluateFormula(
        this.formulaInput,
        this.localRows,
        this.columnKeys,
        this.formulas,
      );
      const updated = new Map(this.formulas);
      updated.set(key, { formula: this.formulaInput, result });
      this.formulas = updated;

      if (this.selectedCol < this.columnKeys.length) {
        this.localRows[this.selectedRow] = {
          ...this.localRows[this.selectedRow],
          [this.columnKeys[this.selectedCol]]: result,
        };
      }
    } else {
      const updated = new Map(this.formulas);
      updated.delete(key);
      this.formulas = updated;

      if (this.selectedCol < this.columnKeys.length) {
        this.localRows[this.selectedRow] = {
          ...this.localRows[this.selectedRow],
          [this.columnKeys[this.selectedCol]]: this.formulaInput,
        };
      }
    }
  }

  openSigmaColumnSelect(
    action: "computed" | "rollup",
    agg: AggregationType,
  ): void {
    this.sigmaAction = action;
    this.sigmaAggType = agg;
    this.sigmaSelectedCols = new Set();
    this.sigmaStep = "column-select";
  }

  toggleSigmaColumn(key: string): void {
    const next = new Set(this.sigmaSelectedCols);
    if (next.has(key)) {
      next.delete(key);
    } else {
      if (this.sigmaAction === "rollup") next.clear();
      next.add(key);
    }
    this.sigmaSelectedCols = next;
  }

  applySigma(): void {
    if (!this.sigmaAction || !this.sigmaAggType) return;
    this.sigmaCounter++;

    const AGG_LABELS: Record<AggregationType, string> = {
      sum: "Sum",
      average: "Average",
      min: "Min",
      max: "Max",
      count: "Count",
      distinct_count: "Distinct Count",
    };

    if (this.sigmaAction === "computed") {
      const cols = Array.from(this.sigmaSelectedCols);
      if (cols.length === 0) return;
      const label = `${AGG_LABELS[this.sigmaAggType]} (${cols.join(", ")})`;
      const prop = `_computed_${this.sigmaAggType}_${this.sigmaCounter}`;
      this.computedColumns = [
        ...this.computedColumns,
        { id: prop, type: this.sigmaAggType, sourceColumns: cols, label, prop },
      ];
    } else {
      const col = Array.from(this.sigmaSelectedCols)[0];
      if (!col) return;
      const label = `${AGG_LABELS[this.sigmaAggType]} of ${col}`;
      this.rollUpRows = [
        ...this.rollUpRows,
        {
          id: `_rollup_${this.sigmaAggType}_${this.sigmaCounter}`,
          type: this.sigmaAggType,
          sourceColumn: col,
          label,
        },
      ];
    }

    this.sigmaStep = "menu";
    this.sigmaAction = null;
    this.sigmaAggType = null;
    this.sigmaSelectedCols = new Set();
    this.sigmaDropdownOpen = false;
  }

  cancelSigma(): void {
    this.sigmaStep = "menu";
    this.sigmaAction = null;
    this.sigmaAggType = null;
    this.sigmaSelectedCols = new Set();
  }

  clearAllComputed(): void {
    this.computedColumns = [];
    this.rollUpRows = [];
    this.sigmaDropdownOpen = false;
  }

  removeComputedColumn(id: string): void {
    this.computedColumns = this.computedColumns.filter((cc) => cc.id !== id);
  }

  removeRollUpRow(id: string): void {
    this.rollUpRows = this.rollUpRows.filter((ru) => ru.id !== id);
  }

  /** Remove any grid state persisted by older builds. The grid is now ephemeral. */
  purgeLegacyPersistedState(): void {
    if (!browser) return;
    try {
      localStorage.removeItem(this.storageKey);
    } catch {
      /* ignore — storage unavailable */
    }
  }
}
