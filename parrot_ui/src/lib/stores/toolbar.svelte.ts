import { getContext, setContext } from 'svelte';

export interface ToolbarButton {
    id: string;
    label: string; // Used for tooltip
    icon: string; // HTML SVG path or icon name (required)
    onClick?: () => void;
    variant?: 'ghost' | 'primary' | 'secondary' | 'accent';
    position?: 'left' | 'right'; // Relative to default center
}

class ToolbarState {
    buttons = $state<ToolbarButton[]>([]);

    addButton(button: ToolbarButton) {
        // Avoid duplicates
        if (!this.buttons.find(b => b.id === button.id)) {
            this.buttons.push(button);
        }
    }

    removeButton(id: string) {
        this.buttons = this.buttons.filter(b => b.id !== id);
    }

    clearButtons() {
        this.buttons = [];
    }
}

// Global instance for now, or could be contextual
export const toolbarStore = new ToolbarState();
