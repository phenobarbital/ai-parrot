/**
 * Data transformation utilities for DataSource.
 * Inspired by lodash but lightweight.
 */

export type DataTransformer<T, R> = (
    data: T,
    context: TransformContext,
) => R;

export interface TransformContext {
    response: Response;
    config: unknown;
    fetchedAt: Date;
}

/**
 * Get nested property by dot-notation path.
 * Similar to lodash.get
 */
function getByPath(obj: unknown, path: string): unknown {
    const keys = path.split('.');
    let current: unknown = obj;

    for (const key of keys) {
        if (current == null) return undefined;
        current = (current as Record<string, unknown>)[key];
    }

    return current;
}

/**
 * Pre-built transformers for common operations.
 */
export const Transformers = {
    /**
     * Extract a nested property by path.
     * @example Transformers.pluck('data.users.items')
     */
    pluck: <T, R>(path: string): DataTransformer<T, R> => {
        return (data: T) => getByPath(data, path) as R;
    },

    /**
     * Filter array items.
     * @example Transformers.filter(user => user.active)
     */
    filter: <T extends unknown[]>(
        predicate: (item: T[number], index: number) => boolean,
    ): DataTransformer<T, T> => {
        return (data: T) => data.filter(predicate) as T;
    },

    /**
     * Sort array items.
     * @example Transformers.sort((a, b) => b.score - a.score)
     */
    sort: <T extends unknown[]>(
        compareFn: (a: T[number], b: T[number]) => number,
    ): DataTransformer<T, T> => {
        return (data: T) => [...data].sort(compareFn) as T;
    },

    /**
     * Map over array items.
     * @example Transformers.mapItems(user => ({ id: user.id, name: user.name }))
     */
    mapItems: <T extends unknown[], R>(
        mapFn: (item: T[number], index: number) => R,
    ): DataTransformer<T, R[]> => {
        return (data: T) => data.map(mapFn);
    },

    /**
     * Group array items by key.
     * @example Transformers.groupBy(item => item.category)
     */
    groupBy: <T extends unknown[], K extends string | number>(
        keyFn: (item: T[number]) => K,
    ): DataTransformer<T, Record<K, T[number][]>> => {
        return (data: T) => {
            const result = {} as Record<K, T[number][]>;
            for (const item of data) {
                const key = keyFn(item);
                if (!result[key]) {
                    result[key] = [];
                }
                result[key].push(item);
            }
            return result;
        };
    },

    /**
     * Compose multiple transformers.
     * Executes left-to-right.
     * @example Transformers.compose(
     *   Transformers.pluck('data.items'),
     *   Transformers.filter(item => item.active),
     *   items => items.slice(0, 10)
     * )
     */
    compose: <T, R>(
        ...fns: Array<DataTransformer<unknown, unknown> | ((data: unknown) => unknown)>
    ): DataTransformer<T, R> => {
        return (data: T, context: TransformContext) => {
            let result: unknown = data;
            for (const fn of fns) {
                result = fn.length === 2
                    ? (fn as DataTransformer<unknown, unknown>)(result, context)
                    : (fn as (data: unknown) => unknown)(result);
            }
            return result as R;
        };
    },

    /**
     * Identity transformer (no-op).
     */
    identity: <T>(): DataTransformer<T, T> => {
        return (data: T) => data;
    },
};
