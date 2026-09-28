<script lang="ts">
	import Child from './Child.svelte'
	let { rows }: { rows: string[] } = $props()
	const onSave = async () => { persist(rows) }
</script>
<Child items={rows} />
