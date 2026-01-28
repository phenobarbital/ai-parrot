<script lang="ts">
    import { Widget } from "./lib/dashboard/models/widget.svelte.js";
    import WidgetRenderer from "./lib/dashboard/components/Widget.svelte";

    // Create state (Runes)
    let widgets = $state<Widget[]>([]);

    function addWidget() {
        const w = new Widget({
            title: `Widget ${widgets.length + 1}`,
            x: 50 + widgets.length * 30,
            y: 50 + widgets.length * 30,
            w: 300,
            h: 200,
        });
        widgets.push(w);
    }

    // Simple drag logic test
    function randomize() {
        widgets.forEach((w) => {
            w.moveTo(Math.random() * 500, Math.random() * 500);
        });
    }
</script>

<main>
    <div class="toolbar">
        <button onclick={addWidget}>Add Widget</button>
        <button onclick={randomize}>Randomize Positions</button>
    </div>

    <div class="canvas">
        {#each widgets as widget (widget.id)}
            <WidgetRenderer {widget}>
                {#snippet content()}
                    <div class="demo-content">
                        <h3>Dynamic Content</h3>
                        <p>ID: {widget.id}</p>
                        <p>
                            Pos: {Math.round(widget.x)}, {Math.round(widget.y)}
                        </p>
                        <input
                            type="text"
                            bind:value={widget.title}
                            placeholder="Bind Title"
                        />
                    </div>
                {/snippet}
            </WidgetRenderer>
        {/each}
    </div>
</main>

<style>
    main {
        width: 100vw;
        height: 100vh;
        display: flex;
        flex-direction: column;
        background: #f0f2f5;
    }
    .toolbar {
        padding: 1rem;
        background: white;
        border-bottom: 1px solid #ccc;
        display: flex;
        gap: 1rem;
    }
    .canvas {
        flex: 1;
        position: relative;
        overflow: hidden;
    }
    .demo-content {
        height: 100%;
        display: flex;
        flex-direction: column;
        gap: 0.5rem;
    }
    input {
        padding: 4px;
        border: 1px solid #ddd;
        border-radius: 4px;
    }
</style>
