# State Machines & OOP Patterns

## Table of Contents
1. [Reactive Classes](#reactive-classes)
2. [State Machine Pattern](#state-machine-pattern)
3. [Manager Classes](#manager-classes)
4. [Context Integration](#context-integration)
5. [Stores Interop](#stores-interop)

---

## Reactive Classes

### Basic Reactive Class

```typescript
// counter.svelte.ts
export class Counter {
  count = $state(0);
  step = $state(1);
  
  // Derived value
  get doubled() {
    return this.count * 2;
  }
  
  increment() {
    this.count += this.step;
  }
  
  decrement() {
    this.count -= this.step;
  }
  
  reset() {
    this.count = 0;
  }
}
```

### Class with Private State

```typescript
// auth-state.svelte.ts
export class AuthState {
  user = $state<User | null>(null);
  
  // Private reactive state
  #token = $state<string | null>(null);
  #refreshTimeout: ReturnType<typeof setTimeout> | null = null;
  
  get isAuthenticated() {
    return this.user !== null;
  }
  
  get hasValidToken() {
    return this.#token !== null;
  }
  
  async login(credentials: Credentials) {
    const response = await fetch('/api/login', {
      method: 'POST',
      body: JSON.stringify(credentials)
    });
    
    const { user, token, expiresIn } = await response.json();
    this.user = user;
    this.#token = token;
    this.#scheduleRefresh(expiresIn);
  }
  
  logout() {
    this.user = null;
    this.#token = null;
    if (this.#refreshTimeout) {
      clearTimeout(this.#refreshTimeout);
    }
  }
  
  #scheduleRefresh(expiresIn: number) {
    this.#refreshTimeout = setTimeout(
      () => this.#refreshToken(),
      (expiresIn - 60) * 1000
    );
  }
  
  async #refreshToken() {
    // Refresh logic
  }
}

// Singleton export
export const auth = new AuthState();
```

### Generic Repository Class

```typescript
// repository.svelte.ts
export class Repository<T extends { id: string }> {
  items = $state<T[]>([]);
  loading = $state(false);
  error = $state<string | null>(null);
  
  constructor(private endpoint: string) {}
  
  get byId() {
    return new Map(this.items.map(item => [item.id, item]));
  }
  
  async fetchAll() {
    this.loading = true;
    this.error = null;
    
    try {
      const res = await fetch(this.endpoint);
      this.items = await res.json();
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'Unknown error';
    } finally {
      this.loading = false;
    }
  }
  
  async create(data: Omit<T, 'id'>) {
    const res = await fetch(this.endpoint, {
      method: 'POST',
      body: JSON.stringify(data)
    });
    const created = await res.json();
    this.items = [...this.items, created];
    return created;
  }
  
  async update(id: string, data: Partial<T>) {
    const res = await fetch(`${this.endpoint}/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data)
    });
    const updated = await res.json();
    this.items = this.items.map(item => 
      item.id === id ? updated : item
    );
    return updated;
  }
  
  async delete(id: string) {
    await fetch(`${this.endpoint}/${id}`, { method: 'DELETE' });
    this.items = this.items.filter(item => item.id !== id);
  }
}

// Usage
export const users = new Repository<User>('/api/users');
export const products = new Repository<Product>('/api/products');
```

---

## State Machine Pattern

### Finite State Machine

```typescript
// form-machine.svelte.ts
type FormState = 'idle' | 'editing' | 'validating' | 'submitting' | 'success' | 'error';

type FormEvent = 
  | { type: 'EDIT' }
  | { type: 'SUBMIT' }
  | { type: 'VALIDATE_SUCCESS' }
  | { type: 'VALIDATE_ERROR'; error: string }
  | { type: 'SUBMIT_SUCCESS' }
  | { type: 'SUBMIT_ERROR'; error: string }
  | { type: 'RESET' };

export class FormMachine<T> {
  state = $state<FormState>('idle');
  data = $state<T | null>(null);
  error = $state<string | null>(null);
  
  constructor(private validator: (data: T) => Promise<boolean>) {}
  
  get canSubmit() {
    return this.state === 'editing' && this.data !== null;
  }
  
  get isProcessing() {
    return this.state === 'validating' || this.state === 'submitting';
  }
  
  send(event: FormEvent) {
    switch (this.state) {
      case 'idle':
        if (event.type === 'EDIT') {
          this.state = 'editing';
        }
        break;
        
      case 'editing':
        if (event.type === 'SUBMIT' && this.data) {
          this.state = 'validating';
          this.#validate();
        }
        break;
        
      case 'validating':
        if (event.type === 'VALIDATE_SUCCESS') {
          this.state = 'submitting';
        } else if (event.type === 'VALIDATE_ERROR') {
          this.state = 'editing';
          this.error = event.error;
        }
        break;
        
      case 'submitting':
        if (event.type === 'SUBMIT_SUCCESS') {
          this.state = 'success';
        } else if (event.type === 'SUBMIT_ERROR') {
          this.state = 'error';
          this.error = event.error;
        }
        break;
        
      case 'success':
      case 'error':
        if (event.type === 'RESET') {
          this.state = 'idle';
          this.data = null;
          this.error = null;
        }
        break;
    }
  }
  
  async #validate() {
    try {
      const valid = await this.validator(this.data!);
      this.send(valid 
        ? { type: 'VALIDATE_SUCCESS' }
        : { type: 'VALIDATE_ERROR', error: 'Validation failed' }
      );
    } catch (e) {
      this.send({ type: 'VALIDATE_ERROR', error: String(e) });
    }
  }
  
  setData(data: T) {
    this.data = data;
    this.error = null;
  }
}
```

### Async Operation Machine

```typescript
// async-machine.svelte.ts
type AsyncState = 'idle' | 'loading' | 'success' | 'error';

export class AsyncMachine<T, E = Error> {
  state = $state<AsyncState>('idle');
  data = $state<T | null>(null);
  error = $state<E | null>(null);
  
  get isIdle() { return this.state === 'idle'; }
  get isLoading() { return this.state === 'loading'; }
  get isSuccess() { return this.state === 'success'; }
  get isError() { return this.state === 'error'; }
  
  async execute(operation: () => Promise<T>): Promise<T | null> {
    this.state = 'loading';
    this.error = null;
    
    try {
      this.data = await operation();
      this.state = 'success';
      return this.data;
    } catch (e) {
      this.error = e as E;
      this.state = 'error';
      return null;
    }
  }
  
  reset() {
    this.state = 'idle';
    this.data = null;
    this.error = null;
  }
}

// Usage
const fetchUsers = new AsyncMachine<User[]>();
await fetchUsers.execute(() => fetch('/api/users').then(r => r.json()));
```

---

## Manager Classes

### Widget Manager (Dashboard Pattern)

```typescript
// widget-manager.svelte.ts
interface WidgetConfig {
  id: string;
  type: string;
  title: string;
  position: { x: number; y: number };
  size: { w: number; h: number };
  settings: Record<string, any>;
  visible: boolean;
}

interface LayoutPreset {
  name: string;
  widgets: WidgetConfig[];
}

export class WidgetManager {
  widgets = $state<WidgetConfig[]>([]);
  selectedId = $state<string | null>(null);
  
  #dragState = $state({
    isDragging: false,
    widgetId: null as string | null,
    startPos: { x: 0, y: 0 }
  });
  
  #history = $state<WidgetConfig[][]>([]);
  #historyIndex = $state(-1);
  
  get selected() {
    return this.selectedId 
      ? this.widgets.find(w => w.id === this.selectedId) 
      : null;
  }
  
  get visibleWidgets() {
    return this.widgets.filter(w => w.visible);
  }
  
  get canUndo() {
    return this.#historyIndex > 0;
  }
  
  get canRedo() {
    return this.#historyIndex < this.#history.length - 1;
  }
  
  // CRUD Operations
  add(config: Omit<WidgetConfig, 'id'>) {
    const widget = { ...config, id: crypto.randomUUID() };
    this.#saveHistory();
    this.widgets = [...this.widgets, widget];
    return widget;
  }
  
  remove(id: string) {
    this.#saveHistory();
    this.widgets = this.widgets.filter(w => w.id !== id);
    if (this.selectedId === id) {
      this.selectedId = null;
    }
  }
  
  update(id: string, changes: Partial<WidgetConfig>) {
    this.#saveHistory();
    this.widgets = this.widgets.map(w =>
      w.id === id ? { ...w, ...changes } : w
    );
  }
  
  // Selection
  select(id: string | null) {
    this.selectedId = id;
  }
  
  // Drag & Drop
  startDrag(id: string, x: number, y: number) {
    this.#dragState = { isDragging: true, widgetId: id, startPos: { x, y } };
  }
  
  moveDrag(x: number, y: number) {
    if (!this.#dragState.isDragging || !this.#dragState.widgetId) return;
    
    const dx = x - this.#dragState.startPos.x;
    const dy = y - this.#dragState.startPos.y;
    
    this.widgets = this.widgets.map(w =>
      w.id === this.#dragState.widgetId
        ? { ...w, position: { x: w.position.x + dx, y: w.position.y + dy } }
        : w
    );
    
    this.#dragState.startPos = { x, y };
  }
  
  endDrag() {
    if (this.#dragState.isDragging) {
      this.#saveHistory();
    }
    this.#dragState = { isDragging: false, widgetId: null, startPos: { x: 0, y: 0 } };
  }
  
  // History
  #saveHistory() {
    this.#history = [
      ...this.#history.slice(0, this.#historyIndex + 1),
      structuredClone(this.widgets)
    ];
    this.#historyIndex = this.#history.length - 1;
  }
  
  undo() {
    if (this.canUndo) {
      this.#historyIndex--;
      this.widgets = structuredClone(this.#history[this.#historyIndex]);
    }
  }
  
  redo() {
    if (this.canRedo) {
      this.#historyIndex++;
      this.widgets = structuredClone(this.#history[this.#historyIndex]);
    }
  }
  
  // Presets
  savePreset(name: string): LayoutPreset {
    return { name, widgets: structuredClone(this.widgets) };
  }
  
  loadPreset(preset: LayoutPreset) {
    this.#saveHistory();
    this.widgets = structuredClone(preset.widgets);
  }
  
  // Serialization
  toJSON() {
    return JSON.stringify(this.widgets);
  }
  
  fromJSON(json: string) {
    this.#saveHistory();
    this.widgets = JSON.parse(json);
  }
}

export const widgetManager = new WidgetManager();
```

---

## Context Integration

### Using Classes with Context

```svelte
<!-- +layout.svelte -->
<script lang="ts">
  import { setContext } from 'svelte';
  import { WidgetManager } from '$lib/state/widget-manager.svelte';
  
  // Create instance for this layout tree
  const manager = new WidgetManager();
  setContext('widgetManager', manager);
</script>

<slot />
```

```svelte
<!-- child-component.svelte -->
<script lang="ts">
  import { getContext } from 'svelte';
  import type { WidgetManager } from '$lib/state/widget-manager.svelte';
  
  const manager = getContext<WidgetManager>('widgetManager');
</script>

<button onclick={() => manager.add({ ... })}>
  Add Widget
</button>
```

### Type-Safe Context Pattern

```typescript
// context-keys.ts
import type { WidgetManager } from '$lib/state/widget-manager.svelte';
import type { AuthState } from '$lib/state/auth-state.svelte';

export const CONTEXT_KEYS = {
  widgetManager: Symbol('widgetManager'),
  auth: Symbol('auth')
} as const;

// Type-safe getters
export function getWidgetManager() {
  return getContext<WidgetManager>(CONTEXT_KEYS.widgetManager);
}

export function getAuth() {
  return getContext<AuthState>(CONTEXT_KEYS.auth);
}
```

---

## Stores Interop

### Wrapping Stores in Classes

```typescript
// store-wrapper.svelte.ts
import { writable, type Writable } from 'svelte/store';

export class StoreBackedState<T> {
  #store: Writable<T>;
  current = $state<T>(undefined as T);
  
  constructor(initial: T) {
    this.#store = writable(initial);
    this.current = initial;
    
    // Sync store to state
    this.#store.subscribe(value => {
      this.current = value;
    });
  }
  
  set(value: T) {
    this.#store.set(value);
  }
  
  update(fn: (value: T) => T) {
    this.#store.update(fn);
  }
  
  // For components that need store syntax
  get store() {
    return this.#store;
  }
}
```

### Using External Stores

```svelte
<script lang="ts">
  import { page } from '$app/state';
  import { someExternalStore } from 'external-lib';
  
  // $app/state works directly
  let currentPath = $derived(page.url.pathname);
  
  // External stores need $store syntax
  let externalValue = $derived($someExternalStore);
</script>
```