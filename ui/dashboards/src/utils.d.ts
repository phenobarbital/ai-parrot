export type Dispose = () => void;
export declare const clamp: (n: number, min: number, max: number) => number;
export declare const cssPx: (n: number) => string;
export declare const uid: (prefix?: string) => string;
export declare const stop: (ev: Event) => void;
type Attrs = Record<string, string | boolean | number>;
export declare function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs?: Attrs, ...children: (string | Node)[]): HTMLElementTagNameMap[K];
export declare function on<K extends keyof HTMLElementEventMap>(target: EventTarget, type: K, handler: (ev: HTMLElementEventMap[K]) => void, options?: AddEventListenerOptions): Dispose;
export declare function debounce<T extends (...args: unknown[]) => void>(fn: T, ms: number): T;
export declare const storage: {
    get<T>(key: string): T | null;
    set<T>(key: string, value: T): void;
    remove(key: string): void;
};
export {};
//# sourceMappingURL=utils.d.ts.map