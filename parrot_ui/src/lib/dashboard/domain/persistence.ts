/**
 * Persistence module - Storage abstraction with IndexedDB + LocalStorage fallback
 */

const DB_NAME = 'dashboard-storage';
const DB_VERSION = 1;
const STORE_NAME = 'keyvalue';

// === Storage Interface ===

export interface StorageAdapter {
    get<T>(key: string): Promise<T | null>;
    set(key: string, value: unknown): Promise<void>;
    remove(key: string): Promise<void>;
    clear(): Promise<void>;
}

// === IndexedDB Storage ===

class IndexedDBStorage implements StorageAdapter {
    private dbPromise: Promise<IDBDatabase> | null = null;

    private openDB(): Promise<IDBDatabase> {
        if (this.dbPromise) return this.dbPromise;

        this.dbPromise = new Promise((resolve, reject) => {
            const request = indexedDB.open(DB_NAME, DB_VERSION);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result);

            request.onupgradeneeded = (event) => {
                const db = (event.target as IDBOpenDBRequest).result;
                if (!db.objectStoreNames.contains(STORE_NAME)) {
                    db.createObjectStore(STORE_NAME);
                }
            };
        });

        return this.dbPromise;
    }

    async get<T>(key: string): Promise<T | null> {
        const db = await this.openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, 'readonly');
            const store = tx.objectStore(STORE_NAME);
            const request = store.get(key);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve(request.result ?? null);
        });
    }

    async set(key: string, value: unknown): Promise<void> {
        const db = await this.openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, 'readwrite');
            const store = tx.objectStore(STORE_NAME);
            const request = store.put(value, key);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve();
        });
    }

    async remove(key: string): Promise<void> {
        const db = await this.openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, 'readwrite');
            const store = tx.objectStore(STORE_NAME);
            const request = store.delete(key);

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve();
        });
    }

    async clear(): Promise<void> {
        const db = await this.openDB();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE_NAME, 'readwrite');
            const store = tx.objectStore(STORE_NAME);
            const request = store.clear();

            request.onerror = () => reject(request.error);
            request.onsuccess = () => resolve();
        });
    }
}

// === LocalStorage Fallback ===

class LocalStorageAdapter implements StorageAdapter {
    private prefix = 'dashboard:';

    async get<T>(key: string): Promise<T | null> {
        try {
            const item = localStorage.getItem(this.prefix + key);
            return item ? JSON.parse(item) : null;
        } catch {
            return null;
        }
    }

    async set(key: string, value: unknown): Promise<void> {
        try {
            localStorage.setItem(this.prefix + key, JSON.stringify(value));
        } catch {
            // Quota exceeded or other error
            console.warn('[Persistence] LocalStorage write failed for key:', key);
        }
    }

    async remove(key: string): Promise<void> {
        try {
            localStorage.removeItem(this.prefix + key);
        } catch {
            // Ignore
        }
    }

    async clear(): Promise<void> {
        try {
            const keys = Object.keys(localStorage).filter(k => k.startsWith(this.prefix));
            keys.forEach(k => localStorage.removeItem(k));
        } catch {
            // Ignore
        }
    }
}

// === Sync Helper for legacy code ===

export const storageSync = {
    set: (key: string, val: unknown): void => {
        try {
            localStorage.setItem(key, JSON.stringify(val));
        } catch {
            // Ignore
        }
    },
    get: <T>(key: string): T | null => {
        try {
            return JSON.parse(localStorage.getItem(key) || 'null');
        } catch {
            return null;
        }
    },
    remove: (key: string): void => {
        try {
            localStorage.removeItem(key);
        } catch {
            // Ignore
        }
    }
};

// === Factory ===

function createStorage(): StorageAdapter {
    // Check if IndexedDB is available
    if (typeof indexedDB !== 'undefined') {
        try {
            return new IndexedDBStorage();
        } catch {
            console.warn('[Persistence] IndexedDB not available, falling back to LocalStorage');
        }
    }

    // Fallback to LocalStorage
    return new LocalStorageAdapter();
}

// === Singleton Export ===

export const storage = createStorage();

// Re-export sync storage for layouts that need sync operations
export { storageSync as storageLegacy };
