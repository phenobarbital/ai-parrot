// card-widget.ts - KPI Card display widget
import { ApiWidget } from "./api-widget.js";
/**
 * Default gradient colors for colored cards.
 */
const DEFAULT_COLORS = [
    "linear-gradient(135deg, #e831a3 0%, #a855f7 100%)", // Pink-Purple
    "linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)", // Blue
    "linear-gradient(135deg, #22c55e 0%, #16a34a 100%)", // Green
    "linear-gradient(135deg, #f97316 0%, #ea580c 100%)", // Orange
    "linear-gradient(135deg, #06b6d4 0%, #0891b2 100%)", // Cyan
    "linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%)", // Purple
    "linear-gradient(135deg, #ec4899 0%, #db2777 100%)", // Pink
    "linear-gradient(135deg, #eab308 0%, #ca8a04 100%)", // Yellow
];
/**
 * CardWidget - Displays KPIs as Bootstrap-like cards.
 *
 * Features:
 * - Colored mode: Gradient backgrounds with optional background images
 * - Transparent mode: Plain background with foreground icons
 * - Comparison mode: Shows trend arrows (+X.X% / -X.X%)
 * - Progress bar footer for goal tracking
 * - Responsive layout: Cards stack vertically on mobile
 */
export class CardWidget extends ApiWidget {
    _displayMode;
    _cardsConfig;
    _comparisonEnabled;
    _comparisonData;
    _showProgressBar;
    _defaultColors;
    _cardGap;
    _cardContainer = null;
    constructor(opts) {
        super({
            icon: "📊",
            ...opts,
            title: opts.title || "KPI Cards",
        });
        this._displayMode = opts.displayMode ?? "colored";
        this._cardsConfig = opts.cards ?? [];
        this._comparisonEnabled = opts.comparisonEnabled ?? false;
        this._comparisonData = opts.comparisonData ?? [];
        this._showProgressBar = opts.showProgressBar ?? false;
        this._defaultColors = opts.defaultColors ?? DEFAULT_COLORS;
        this._cardGap = opts.cardGap ?? 16;
        // Initialize card container
        this.initializeCardContainer();
    }
    /**
     * Initialize the card container element.
     */
    initializeCardContainer() {
        this._cardContainer = document.createElement("div");
        this._cardContainer.className = "card-widget-container";
        Object.assign(this._cardContainer.style, {
            display: "flex",
            flexWrap: "wrap",
            gap: `${this._cardGap}px`,
            padding: "16px",
            boxSizing: "border-box",
            width: "100%",
            height: "100%",
            overflow: "auto",
            alignContent: "flex-start",
        });
        this.setContent(this._cardContainer);
    }
    /**
     * Format a value based on the format configuration.
     */
    formatValue(value, config) {
        if (value === null || value === undefined)
            return "N/A";
        const num = typeof value === "number" ? value : parseFloat(String(value));
        if (isNaN(num))
            return String(value);
        const decimals = config.decimals ?? 2;
        const format = config.format ?? "number";
        switch (format) {
            case "currency":
                const symbol = config.currencySymbol ?? "$";
                if (num >= 1000000) {
                    return `${symbol}${(num / 1000000).toFixed(decimals)}M`;
                }
                else if (num >= 1000) {
                    return `${symbol}${(num / 1000).toFixed(decimals)}k`;
                }
                return `${symbol}${num.toFixed(decimals)}`;
            case "percent":
                return `${(num * 100).toFixed(decimals)}%`;
            case "number":
            default:
                if (num >= 1000000) {
                    return `${(num / 1000000).toFixed(decimals)}M`;
                }
                else if (num >= 1000) {
                    return `${(num / 1000).toFixed(decimals)}k`;
                }
                return num.toLocaleString(undefined, {
                    minimumFractionDigits: decimals,
                    maximumFractionDigits: decimals,
                });
        }
    }
    /**
     * Calculate comparison percentage between current and previous values.
     */
    calculateComparison(currentValue, previousValue) {
        const current = typeof currentValue === "number" ? currentValue : parseFloat(String(currentValue));
        const previous = typeof previousValue === "number" ? previousValue : parseFloat(String(previousValue));
        if (isNaN(current) || isNaN(previous) || previous === 0)
            return null;
        const percentChange = ((current - previous) / Math.abs(previous)) * 100;
        return {
            percentage: Math.abs(percentChange),
            isPositive: percentChange >= 0,
        };
    }
    /**
     * Create a single card element.
     */
    createCard(config, value, index, comparisonValue) {
        const card = document.createElement("div");
        card.className = `card-widget-card ${this._displayMode}`;
        const color = config.color ?? this._defaultColors[index % this._defaultColors.length];
        const isGradient = color?.includes("gradient") ?? false;
        // Base card styles
        Object.assign(card.style, {
            flex: "1 1 200px",
            minWidth: "180px",
            maxWidth: "300px",
            borderRadius: "12px",
            padding: "16px",
            position: "relative",
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.1)",
            transition: "transform 0.2s, box-shadow 0.2s",
        });
        if (this._displayMode === "colored") {
            Object.assign(card.style, {
                background: color ?? this._defaultColors[0],
                color: "#fff",
            });
            // Background image (decorative)
            if (config.image) {
                const bgImg = document.createElement("div");
                Object.assign(bgImg.style, {
                    position: "absolute",
                    right: "-10px",
                    bottom: "-10px",
                    width: "80px",
                    height: "80px",
                    backgroundImage: `url(${config.image})`,
                    backgroundSize: "contain",
                    backgroundRepeat: "no-repeat",
                    backgroundPosition: "center",
                    opacity: "0.3",
                });
                card.appendChild(bgImg);
            }
        }
        else {
            // Transparent mode
            Object.assign(card.style, {
                background: "#fff",
                color: "#333",
                border: "1px solid #eee",
            });
            // Foreground icon/image
            if (config.image) {
                const iconContainer = document.createElement("div");
                Object.assign(iconContainer.style, {
                    width: "48px",
                    height: "48px",
                    borderRadius: "50%",
                    background: isGradient ? color : color,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    marginBottom: "8px",
                    flexShrink: "0",
                });
                const icon = document.createElement("img");
                icon.src = config.image;
                Object.assign(icon.style, {
                    width: "24px",
                    height: "24px",
                    filter: "brightness(0) invert(1)",
                });
                icon.onerror = () => {
                    // Fallback to emoji if image fails
                    iconContainer.textContent = "📊";
                    iconContainer.style.fontSize = "20px";
                    iconContainer.style.color = "#fff";
                };
                iconContainer.appendChild(icon);
                card.appendChild(iconContainer);
            }
        }
        // Title
        const titleEl = document.createElement("div");
        titleEl.className = "card-widget-title";
        titleEl.textContent = config.title;
        Object.assign(titleEl.style, {
            fontSize: "13px",
            fontWeight: "500",
            opacity: this._displayMode === "colored" ? "0.9" : "0.7",
            textTransform: "uppercase",
            letterSpacing: "0.5px",
        });
        card.appendChild(titleEl);
        // Value row (value + comparison)
        const valueRow = document.createElement("div");
        Object.assign(valueRow.style, {
            display: "flex",
            alignItems: "baseline",
            gap: "12px",
            flexWrap: "wrap",
        });
        const valueEl = document.createElement("div");
        valueEl.className = "card-widget-value";
        valueEl.textContent = this.formatValue(value, config);
        Object.assign(valueEl.style, {
            fontSize: "28px",
            fontWeight: "700",
            lineHeight: "1.2",
        });
        valueRow.appendChild(valueEl);
        // Comparison indicator
        if (this._comparisonEnabled && comparisonValue !== undefined) {
            const comparison = this.calculateComparison(value, comparisonValue);
            if (comparison) {
                const compEl = document.createElement("div");
                compEl.className = `card-widget-comparison ${comparison.isPositive ? "positive" : "negative"}`;
                compEl.innerHTML = `${comparison.isPositive ? "↑" : "↓"} ${comparison.percentage.toFixed(1)}%`;
                Object.assign(compEl.style, {
                    fontSize: "13px",
                    fontWeight: "600",
                    padding: "2px 8px",
                    borderRadius: "12px",
                    background: comparison.isPositive
                        ? "rgba(34, 197, 94, 0.2)"
                        : "rgba(239, 68, 68, 0.2)",
                    color: this._displayMode === "colored"
                        ? "#fff"
                        : comparison.isPositive
                            ? "#16a34a"
                            : "#dc2626",
                });
                valueRow.appendChild(compEl);
            }
        }
        card.appendChild(valueRow);
        // Progress bar footer
        if (this._showProgressBar && config.goal !== undefined) {
            const numValue = typeof value === "number" ? value : parseFloat(String(value));
            if (!isNaN(numValue)) {
                const progress = Math.min((numValue / config.goal) * 100, 100);
                const progressContainer = document.createElement("div");
                Object.assign(progressContainer.style, {
                    marginTop: "auto",
                    paddingTop: "8px",
                });
                const progressBar = document.createElement("div");
                Object.assign(progressBar.style, {
                    width: "100%",
                    height: "6px",
                    borderRadius: "3px",
                    background: this._displayMode === "colored"
                        ? "rgba(255, 255, 255, 0.3)"
                        : "#e5e7eb",
                    overflow: "hidden",
                });
                const progressFill = document.createElement("div");
                Object.assign(progressFill.style, {
                    width: `${progress}%`,
                    height: "100%",
                    borderRadius: "3px",
                    background: this._displayMode === "colored"
                        ? "#fff"
                        : isGradient ? color : "#3b82f6",
                    transition: "width 0.5s ease",
                });
                progressBar.appendChild(progressFill);
                progressContainer.appendChild(progressBar);
                card.appendChild(progressContainer);
            }
        }
        // Hover effect
        card.addEventListener("mouseenter", () => {
            card.style.transform = "translateY(-2px)";
            card.style.boxShadow = "0 8px 24px rgba(0, 0, 0, 0.15)";
        });
        card.addEventListener("mouseleave", () => {
            card.style.transform = "";
            card.style.boxShadow = "0 4px 12px rgba(0, 0, 0, 0.1)";
        });
        return card;
    }
    /**
     * Render cards from data.
     */
    renderData() {
        if (!this._cardContainer)
            return;
        this._cardContainer.innerHTML = "";
        const data = this.getData();
        if (!data || !Array.isArray(data) || data.length === 0) {
            this.renderPlaceholder("No data available");
            return;
        }
        // Use first row for card values (typical for aggregated KPI data)
        const row = data[0];
        if (!row) {
            this.renderPlaceholder("No data available");
            return;
        }
        const comparisonRow = this._comparisonData?.[0];
        // If no cards configured, try to auto-detect numeric columns
        let cardsToRender = this._cardsConfig;
        if (cardsToRender.length === 0) {
            cardsToRender = Object.entries(row)
                .filter(([, value]) => typeof value === "number")
                .slice(0, 5) // Limit to 5 cards max
                .map(([key]) => ({
                valueKey: key,
                title: this.humanizeKey(key),
            }));
        }
        // Render each card
        cardsToRender.forEach((config, index) => {
            const value = row[config.valueKey];
            const compValue = comparisonRow?.[config.valueKey];
            const card = this.createCard(config, value, index, compValue);
            this._cardContainer.appendChild(card);
        });
    }
    /**
     * Convert a snake_case or camelCase key to human-readable title.
     */
    humanizeKey(key) {
        return key
            .replace(/_/g, " ")
            .replace(/([a-z])([A-Z])/g, "$1 $2")
            .replace(/\b\w/g, (c) => c.toUpperCase());
    }
    // === Configuration ===
    getConfigTabs() {
        return [...super.getConfigTabs(), this.createCardsConfigTab()];
    }
    onConfigSave(config) {
        super.onConfigSave(config);
        if (typeof config.displayMode === "string") {
            this._displayMode = config.displayMode;
        }
        if (typeof config.comparisonEnabled === "boolean") {
            this._comparisonEnabled = config.comparisonEnabled;
        }
        if (typeof config.showProgressBar === "boolean") {
            this._showProgressBar = config.showProgressBar;
        }
        if (typeof config.cardGap === "number") {
            this._cardGap = config.cardGap;
            if (this._cardContainer) {
                this._cardContainer.style.gap = `${this._cardGap}px`;
            }
        }
        if (typeof config.cardsConfig === "string") {
            try {
                this._cardsConfig = JSON.parse(config.cardsConfig);
            }
            catch {
                console.warn("[CardWidget] Invalid cards config JSON");
            }
        }
        // Re-render with new config
        this.renderData();
    }
    /**
     * Create the Cards configuration tab.
     */
    createCardsConfigTab() {
        let displayModeSelect;
        let comparisonCheckbox;
        let progressBarCheckbox;
        let cardGapInput;
        let cardsConfigTextarea;
        return {
            id: "cards",
            label: "Cards",
            icon: "🎴",
            render: (container) => {
                container.innerHTML = "";
                // Display Mode
                const modeGroup = this.createFormGroup("Display Mode");
                displayModeSelect = document.createElement("select");
                for (const mode of ["colored", "transparent"]) {
                    const option = document.createElement("option");
                    option.value = mode;
                    option.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
                    option.selected = this._displayMode === mode;
                    displayModeSelect.appendChild(option);
                }
                this.styleInput(displayModeSelect);
                modeGroup.appendChild(displayModeSelect);
                container.appendChild(modeGroup);
                // Comparison Toggle
                const compGroup = this.createFormGroup("Enable Comparison");
                comparisonCheckbox = document.createElement("input");
                comparisonCheckbox.type = "checkbox";
                comparisonCheckbox.checked = this._comparisonEnabled;
                compGroup.appendChild(comparisonCheckbox);
                container.appendChild(compGroup);
                // Progress Bar Toggle
                const progressGroup = this.createFormGroup("Show Progress Bar");
                progressBarCheckbox = document.createElement("input");
                progressBarCheckbox.type = "checkbox";
                progressBarCheckbox.checked = this._showProgressBar;
                progressGroup.appendChild(progressBarCheckbox);
                container.appendChild(progressGroup);
                // Card Gap
                const gapGroup = this.createFormGroup("Card Gap (px)");
                cardGapInput = document.createElement("input");
                cardGapInput.type = "number";
                cardGapInput.min = "0";
                cardGapInput.value = String(this._cardGap);
                this.styleInput(cardGapInput);
                cardGapInput.style.width = "80px";
                gapGroup.appendChild(cardGapInput);
                container.appendChild(gapGroup);
                // Cards Configuration (JSON)
                const cardsGroup = this.createFormGroup("Cards Configuration (JSON)");
                cardsConfigTextarea = document.createElement("textarea");
                cardsConfigTextarea.value = JSON.stringify(this._cardsConfig, null, 2);
                cardsConfigTextarea.placeholder = `[
  {
    "valueKey": "num_stores",
    "title": "Number of Stores",
    "format": "number",
    "color": "linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)"
  }
]`;
                Object.assign(cardsConfigTextarea.style, {
                    width: "100%",
                    height: "200px",
                    padding: "8px 12px",
                    borderRadius: "6px",
                    border: "1px solid var(--border, #ddd)",
                    fontSize: "12px",
                    fontFamily: "monospace",
                    resize: "vertical",
                    boxSizing: "border-box",
                });
                cardsGroup.appendChild(cardsConfigTextarea);
                container.appendChild(cardsGroup);
            },
            save: () => ({
                displayMode: displayModeSelect?.value ?? this._displayMode,
                comparisonEnabled: comparisonCheckbox?.checked ?? this._comparisonEnabled,
                showProgressBar: progressBarCheckbox?.checked ?? this._showProgressBar,
                cardGap: parseInt(cardGapInput?.value, 10) || this._cardGap,
                cardsConfig: cardsConfigTextarea?.value ?? JSON.stringify(this._cardsConfig),
            }),
        };
    }
    /**
     * Create a form group element with label.
     */
    createFormGroup(label) {
        const group = document.createElement("div");
        Object.assign(group.style, { marginBottom: "16px" });
        const labelEl = document.createElement("label");
        labelEl.textContent = label;
        Object.assign(labelEl.style, {
            display: "block",
            marginBottom: "6px",
            fontSize: "13px",
            fontWeight: "500",
            color: "var(--text, #333)",
        });
        group.appendChild(labelEl);
        return group;
    }
    /**
     * Apply standard input styles.
     */
    styleInput(input) {
        Object.assign(input.style, {
            padding: "8px 12px",
            borderRadius: "6px",
            border: "1px solid var(--border, #ddd)",
            fontSize: "14px",
        });
    }
    // === Public API ===
    /**
     * Set the display mode.
     */
    setDisplayMode(mode) {
        this._displayMode = mode;
        this.renderData();
    }
    /**
     * Get current display mode.
     */
    getDisplayMode() {
        return this._displayMode;
    }
    /**
     * Set cards configuration.
     */
    setCardsConfig(cards) {
        this._cardsConfig = cards;
        this.renderData();
    }
    /**
     * Get current cards configuration.
     */
    getCardsConfig() {
        return this._cardsConfig;
    }
    /**
     * Set comparison data for trend calculation.
     */
    setComparisonData(data) {
        this._comparisonData = data;
        this.renderData();
    }
    /**
     * Enable or disable comparison mode.
     */
    setComparisonEnabled(enabled) {
        this._comparisonEnabled = enabled;
        this.renderData();
    }
    /**
     * Enable or disable progress bar.
     */
    setShowProgressBar(show) {
        this._showProgressBar = show;
        this.renderData();
    }
}
//# sourceMappingURL=card-widget.js.map