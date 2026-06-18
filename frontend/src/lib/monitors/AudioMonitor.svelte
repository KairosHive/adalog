<script lang="ts">
	import { recorder } from '$lib/app/session.svelte';
	let { nodeId }: { nodeId: string } = $props();
	const rms = $derived(recorder.statuses[nodeId]?.quality?.rms ?? 0);
	const pct = $derived(Math.min(100, Math.sqrt(rms) * 140));
</script>

<div class="meter"><div class="bar" style:width={`${pct}%`}></div></div>
<span class="rd mono">RMS {rms.toFixed(4)}</span>

<style>
	.meter { height: 22px; background: var(--ink); border: 1px solid var(--line); border-radius: var(--r); overflow: hidden; }
	.bar { height: 100%; background: linear-gradient(90deg, var(--ok), var(--signal) 70%, var(--rec)); transition: width .1s linear; }
	.rd { font-size: 11px; color: var(--muted); }
</style>
