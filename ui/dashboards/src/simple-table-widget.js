// simple-table-widget.ts - Basic Table with Zebra, Totals, and Masks
import { ApiWidget } from "./api-widget.js";
export class SimpleTableWidget extends ApiWidget {
    _zebra;
    _totals;
    _columns;
    _tableContainer = null;
    constructor(opts) {
        super({
            icon: "▦",
            ...opts,
            title: opts.title || "Simple Table",
        });
        this._zebra = opts.zebra ?? true;
        this._totals = opts.totals ?? "none";
        this._columns = opts.columns ?? [];
        // Initialize container
        this.initializeTableContainer();
    }
    initializeTableContainer() {
        this._tableContainer = document.createElement("div");
        this._tableContainer.className = "simple-table-container";
        // Styles will be largely handled by dashboard.css, but we add some base layout here
        Object.assign(this._tableContainer.style, {
            width: "100%",
            height: "100%",
            overflow: "auto",
        });
        this.setContent(this._tableContainer);
    }
    renderData() {
        if (!this._tableContainer)
            return;
        this._tableContainer.innerHTML = "";
        const data = this.getData();
        if (!data || !Array.isArray(data) || data.length === 0) {
            this.renderPlaceholder("No data available");
            return;
        }
        // Auto-detect columns if not configured
        let columns = this._columns;
        if (columns.length === 0) {
            const keys = Object.keys(data[0]);
            columns = keys.map(key => ({ key, label: this.humanize(key) }));
        }
        const table = document.createElement("table");
        table.className = "simple-table";
        if (this._zebra)
            table.classList.add("simple-table-zebra");
        // Header
        const thead = document.createElement("thead");
        const headerRow = document.createElement("tr");
        columns.forEach(col => {
            if (col.hidden)
                return;
            const th = document.createElement("th");
            th.textContent = col.label ?? this.humanize(col.key);
            headerRow.appendChild(th);
        });
        thead.appendChild(headerRow);
        table.appendChild(thead);
        // Body
        const tbody = document.createElement("tbody");
        data.forEach(row => {
            const tr = document.createElement("tr");
            columns.forEach(col => {
                if (col.hidden)
                    return;
                const td = document.createElement("td");
                const val = row[col.key];
                td.textContent = this.formatValue(val, col.mask);
                // Numeric alignment hint
                if (typeof val === "number" || (col.mask && col.mask !== "string")) {
                    td.classList.add("text-right");
                }
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        // Footer (Totals)
        if (this._totals !== "none") {
            const tfoot = document.createElement("tfoot");
            const footerRow = document.createElement("tr");
            footerRow.className = "simple-table-total";
            // Add a label in the first visible column
            let labelAdded = false;
            columns.forEach((col, index) => {
                if (col.hidden)
                    return;
                const td = document.createElement("td");
                // If it's a numeric column, calculate total
                // Just a simple heuristic: check the first row's value type or if mask is numeric
                const isNumeric = typeof data[0][col.key] === "number";
                if (isNumeric) {
                    const values = data.map(r => Number(r[col.key]));
                    const total = this.calculateTotal(values, this._totals);
                    td.textContent = this.formatValue(total, col.mask);
                    td.classList.add("text-right");
                }
                else if (!labelAdded) {
                    td.textContent = `Total (${this._totals})`;
                    td.style.fontWeight = "bold";
                    labelAdded = true;
                }
                footerRow.appendChild(td);
            });
            tfoot.appendChild(footerRow);
            table.appendChild(tfoot);
        }
        this._tableContainer.appendChild(table);
    }
    calculateTotal(values, type) {
        if (values.length === 0)
            return 0;
        const sum = values.reduce((a, b) => a + b, 0);
        switch (type) {
            case "sum": return sum;
            case "avg": return sum / values.length;
            case "median":
                const sorted = [...values].sort((a, b) => a - b);
                const mid = Math.floor(sorted.length / 2);
                return sorted.length % 2 !== 0 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
            default: return 0;
        }
    }
    formatValue(value, mask) {
        if (value === null || value === undefined)
            return "";
        if (typeof value !== "number")
            return String(value);
        switch (mask) {
            case "money":
                return value.toLocaleString(undefined, { style: "currency", currency: "USD" }); // Default USD for now
            case "percent":
                return value.toLocaleString(undefined, { style: "percent", minimumFractionDigits: 1 });
            case "number":
                return value.toLocaleString();
            default:
                return String(value);
        }
    }
    humanize(key) {
        return key.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase());
    }
    // === Configuration ===
    getConfigTabs() {
        return [...super.getConfigTabs(), this.createTableConfigTab()];
    }
    onConfigSave(config) {
        super.onConfigSave(config);
        if (typeof config.zebra === "boolean")
            this._zebra = config.zebra;
        if (typeof config.totals === "string")
            this._totals = config.totals;
        if (typeof config.columns === "string") {
            try {
                this._columns = JSON.parse(config.columns);
            }
            catch (e) {
                console.warn("Invalid columns config", e);
            }
        }
        this.renderData();
    }
    createTableConfigTab() {
        let zebraInput;
        let totalsSelect;
        let columnsInput;
        return {
            id: "table-settings",
            label: "Table",
            icon: "▦",
            render: (container) => {
                container.innerHTML = "";
                // Zebra Striping
                const zebraGroup = this.createFormGroup("Zebra Striping");
                zebraInput = document.createElement("input");
                zebraInput.type = "checkbox";
                zebraInput.checked = this._zebra;
                zebraGroup.appendChild(zebraInput);
                container.appendChild(zebraGroup);
                // Totals
                const totalsGroup = this.createFormGroup("Totals Row");
                totalsSelect = document.createElement("select");
                const opts = ["none", "sum", "avg", "median"];
                opts.forEach(o => {
                    const opt = document.createElement("option");
                    opt.value = o;
                    opt.textContent = o.charAt(0).toUpperCase() + o.slice(1);
                    if (o === this._totals)
                        opt.selected = true;
                    totalsSelect.appendChild(opt);
                });
                this.styleInput(totalsSelect);
                totalsGroup.appendChild(totalsSelect);
                container.appendChild(totalsGroup);
                // Columns Config (JSON)
                const colsGroup = this.createFormGroup("Columns Config (JSON)");
                columnsInput = document.createElement("textarea");
                columnsInput.value = JSON.stringify(this._columns, null, 2);
                columnsInput.placeholder = `[
  { "key": "postpaid_sales", "label": "Sales", "mask": "money" }
]`;
                this.styleInput(columnsInput);
                columnsInput.style.height = "150px";
                columnsInput.style.fontFamily = "monospace";
                colsGroup.appendChild(columnsInput);
                container.appendChild(colsGroup);
            },
            save: () => ({
                zebra: zebraInput.checked,
                totals: totalsSelect.value,
                columns: columnsInput.value
            })
        };
    }
    createFormGroup(label) {
        const div = document.createElement("div");
        div.style.marginBottom = "10px";
        const l = document.createElement("label");
        l.textContent = label;
        l.style.display = "block";
        l.style.fontWeight = "bold";
        l.style.marginBottom = "5px";
        div.appendChild(l);
        return div;
    }
    styleInput(el) {
        Object.assign(el.style, {
            width: "100%",
            padding: "5px",
            boxSizing: "border-box",
            borderRadius: "4px",
            border: "1px solid #ccc"
        });
    }
}
//# sourceMappingURL=simple-table-widget.js.map