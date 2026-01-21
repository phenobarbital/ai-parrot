import { ApiWidget, type ApiWidgetOptions } from "./api-widget.js";
import type { ConfigTab } from "./widget-config-modal.js";
/**
 * Card display mode configuration.
 */
export type CardDisplayMode = "colored" | "transparent";
/**
 * Individual card configuration.
 */
export interface CardConfig {
    /** Column key to extract value from */
    valueKey: string;
    /** Display title for this card */
    title: string;
    /** Card background color (for colored mode) or icon background */
    color?: string;
    /** Background image URL (colored mode) or icon URL (transparent mode) */
    image?: string;
    /** Goal value for progress bar calculation */
    goal?: number;
    /** Format: 'number', 'currency', 'percent', or custom format string */
    format?: "number" | "currency" | "percent" | string;
    /** Number of decimal places */
    decimals?: number;
    /** Currency symbol for currency format */
    currencySymbol?: string;
}
/**
 * Configuration options for CardWidget.
 */
export interface CardWidgetOptions extends ApiWidgetOptions {
    /** Display mode: 'colored' (gradient bg) or 'transparent' (plain bg, icon foreground) */
    displayMode?: CardDisplayMode;
    /** Card configurations array - defines which columns to show as cards */
    cards?: CardConfig[];
    /** Enable comparison mode (shows trend indicators) */
    comparisonEnabled?: boolean;
    /** Comparison data (previous period) for trend calculation */
    comparisonData?: Record<string, unknown>[];
    /** Show progress bar in footer */
    showProgressBar?: boolean;
    /** Global default color palette for cards */
    defaultColors?: string[];
    /** Card gap in pixels */
    cardGap?: number;
}
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
export declare class CardWidget extends ApiWidget {
    private _displayMode;
    private _cardsConfig;
    private _comparisonEnabled;
    private _comparisonData;
    private _showProgressBar;
    private _defaultColors;
    private _cardGap;
    private _cardContainer;
    constructor(opts: CardWidgetOptions);
    /**
     * Initialize the card container element.
     */
    private initializeCardContainer;
    /**
     * Format a value based on the format configuration.
     */
    private formatValue;
    /**
     * Calculate comparison percentage between current and previous values.
     */
    private calculateComparison;
    /**
     * Create a single card element.
     */
    private createCard;
    /**
     * Render cards from data.
     */
    protected renderData(): void;
    /**
     * Convert a snake_case or camelCase key to human-readable title.
     */
    private humanizeKey;
    getConfigTabs(): ConfigTab[];
    protected onConfigSave(config: Record<string, unknown>): void;
    /**
     * Create the Cards configuration tab.
     */
    private createCardsConfigTab;
    /**
     * Create a form group element with label.
     */
    private createFormGroup;
    /**
     * Apply standard input styles.
     */
    private styleInput;
    /**
     * Set the display mode.
     */
    setDisplayMode(mode: CardDisplayMode): void;
    /**
     * Get current display mode.
     */
    getDisplayMode(): CardDisplayMode;
    /**
     * Set cards configuration.
     */
    setCardsConfig(cards: CardConfig[]): void;
    /**
     * Get current cards configuration.
     */
    getCardsConfig(): CardConfig[];
    /**
     * Set comparison data for trend calculation.
     */
    setComparisonData(data: Record<string, unknown>[]): void;
    /**
     * Enable or disable comparison mode.
     */
    setComparisonEnabled(enabled: boolean): void;
    /**
     * Enable or disable progress bar.
     */
    setShowProgressBar(show: boolean): void;
}
//# sourceMappingURL=card-widget.d.ts.map