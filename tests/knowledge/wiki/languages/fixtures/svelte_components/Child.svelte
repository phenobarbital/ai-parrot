<script lang="ts">
	let { items }: { items: string[] } = $props()
	const onPick = (i: string) => pick(i)
</script>
<ul>{#each items as i}<li on:click={() => onPick(i)}>{i}</li>{/each}</ul>
