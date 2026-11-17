# Toolbar API Documentation

The `Toolbar API` allows modules and pages to dynamically inject buttons and actions into the global Top Toolbar of the AgentUI application. This ensures that context-specific actions are readily available to the user without cluttering the main content area.

## Usage

### Importing the Store

To use the Toolbar API, import the `toolbarStore` from `$lib/stores/toolbar.svelte`.

```typescript
import { toolbarStore } from '$lib/stores/toolbar.svelte';
```

### Adding a Button

Use the `addButton` method to register a new button. It is recommended to do this within an `$effect` block (in Svelte 5) or `onMount` (in Svelte 4) to ensure the button is added when the component mounts.

```typescript
$effect(() => {
  const buttonId = 'my-unique-button-id';

  toolbarStore.addButton({
    id: buttonId,
    label: 'My Action', // Used for tooltip
    icon: 'mdi:rocket', // Icon name (mapped in icon utility) or SVG path
    variant: 'ghost', // 'ghost' (default/recommended), 'primary', 'secondary', 'accent'
    position: 'right', // Optional: 'left' (default) or 'right'
    onClick: () => {
      console.log('Button clicked!');
      // Perform your action here
    }
  });

  // Cleanup: Remove button when component unmounts
  return () => {
    toolbarStore.removeButton(buttonId);
  };
});
```

### Button Interface

```typescript
interface ToolbarButton {
  id: string;           // Unique identifier for the button
  label: string;        // Text label, used for the tooltip
  icon: string;         // Icon identifier (e.g., 'mdi:home') or SVG path
  onClick?: () => void; // Callback function when clicked
  variant?: 'ghost' | 'primary' | 'secondary' | 'accent'; // Button style variant. 'ghost' is circular icon-only.
  position?: 'left' | 'right'; // Position in the toolbar relative to the center spacer. Default is left (center-left).
}
```

## Best Practices

1.  **Unique IDs**: Always use a unique `id` for your buttons to prevent collisions with other modules.
2.  **Cleanup**: Always return a cleanup function that calls `removeButton` to ensure buttons are removed when the user navigates away from your module.
3.  **Icons**: Use clear, recognizable icons. The toolbar buttons are designed to be icon-only with tooltips.
4.  **Tooltips**: Provide meaningful `label`s as they appear as tooltips on hover.
5.  **Placement**: Use `position: 'right'` for secondary or system-like actions, and default (left) for primary module actions.
