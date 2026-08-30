<script lang="ts">
    /**
     * SimpleTable — Reusable data table with Tailwind styling.
     * Replaces Flowbite Table sub-components with plain HTML.
     */

    interface Column {
        key: string;
        label: string;
    }

    interface Props {
        columns: Column[];
        data: Record<string, unknown>[];
        striped?: boolean;
        hoverable?: boolean;
        class?: string;
    }

    let {
        columns,
        data,
        striped = true,
        hoverable = true,
        class: className = "",
    }: Props = $props();

    function formatValue(value: unknown): string {
        if (value === null || value === undefined) return "";
        if (typeof value === "object") return JSON.stringify(value);
        return String(value);
    }
</script>

<div class="w-full overflow-x-auto {className}">
    <table class="w-full text-sm text-left text-base-content">
        <thead
            class="text-xs uppercase bg-base-200 text-base-content/70 dark:bg-base-300 dark:text-base-content/80"
        >
            <tr>
                {#each columns as col (col.key)}
                    <th
                        scope="col"
                        class="px-4 py-3 font-semibold whitespace-nowrap"
                    >
                        {col.label}
                    </th>
                {/each}
            </tr>
        </thead>
        <tbody>
            {#each data as row, idx (idx)}
                <tr
                    class="border-b border-base-200 dark:border-base-300
                        {striped && idx % 2 === 1
                        ? 'bg-base-200/50 dark:bg-base-300/30'
                        : ''}
                        {hoverable
                        ? 'hover:bg-primary-50 dark:hover:bg-primary-900/20 transition-colors'
                        : ''}"
                >
                    {#each columns as col (col.key)}
                        <td class="px-4 py-3">
                            {formatValue(row[col.key])}
                        </td>
                    {/each}
                </tr>
            {/each}
        </tbody>
    </table>
</div>
