<script lang="ts">
	import { untrack } from 'svelte';
	import { subscribe } from '$lib/api/data';

	let { nodeId, stream }: { nodeId: string; stream: any } = $props();
	const NODE = untrack(() => nodeId), SID = untrack(() => stream.id); // snapshot ids — see ArrayMonitor
	let lines = $state<string[]>([]);

	$effect(() => {
		const unsub = subscribe(NODE, SID, (_h, value) => {
			if (typeof value !== 'string') return;
			let obj: any; try { obj = JSON.parse(value); } catch { return; }
			const desc = obj.type ? `${obj.type} ${obj.note ?? ''} ${obj.velocity ?? ''}`.trim() : JSON.stringify(obj);
			lines = [...lines.slice(-40), desc];
		});
		return unsub;
	});
</script>

<div class="log mono">
	{#each lines as l}<div class="line">{l}</div>{/each}
	{#if lines.length === 0}<div class="empty">waiting for messages…</div>{/if}
</div>

<style>
	.log { display: flex; flex-direction: column-reverse; max-height: 200px; overflow: auto; font-size: 11px; }
	.line { padding: 2px 6px; color: var(--text); border-bottom: 1px solid var(--line); }
	.empty { color: var(--faint); padding: 8px; }
</style>
