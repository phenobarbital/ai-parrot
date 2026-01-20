/**
 * Type guard to check if a widget implements IFetchable
 */
export function isFetchable(widget) {
    return (typeof widget.fetchData === "function" &&
        typeof widget.getData === "function" &&
        typeof widget.getError === "function" &&
        typeof widget.isFetching === "function");
}
//# sourceMappingURL=fetchable.js.map