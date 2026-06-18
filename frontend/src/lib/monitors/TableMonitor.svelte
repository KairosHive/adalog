<script lang="ts">
	import { untrack } from 'svelte';
	import { subscribe } from '$lib/api/data';

	let { nodeId, stream, mode = 'osc' }: { nodeId: string; stream: any; mode?: 'osc' | 'meteo' } = $props();
	const NODE = untrack(() => nodeId), SID = untrack(() => stream.id); // snapshot ids — see ArrayMonitor
	let rows = $state<Record<string, any>>({});

	$effect(() => {
		const unsub = subscribe(NODE, SID, (_h, value) => {
			if (typeof value !== 'string') return;
			let obj: any; try { obj = JSON.parse(value); } catch { return; }
			if (mode === 'osc') {
				rows = { ...rows, [obj.address ?? '?']: obj.value };
			} else {
				const { time_tag, ...rest } = obj;
				rows = { ...rest };
			}
		});
		return unsub;
	});
	const entries = $derived(Object.entries(rows));

	// physical ranges for the NOAA space-weather fields → gauge bars
	const METEO: Record<string, { min: number; max: number; unit: string; signed?: boolean }> = {
		bx_gsm: { min: -20, max: 20, unit: 'nT', signed: true },
		by_gsm: { min: -20, max: 20, unit: 'nT', signed: true },
		bz_gsm: { min: -20, max: 20, unit: 'nT', signed: true },
		bt: { min: 0, max: 30, unit: 'nT' },
		density: { min: 0, max: 50, unit: 'p/cm³' },
		speed: { min: 250, max: 800, unit: 'km/s' },
		temperature: { min: 0, max: 600000, unit: 'K' }
	};
	function pct(k: string, v: number) {
		const r = METEO[k]; if (!r) return 0;
		return Math.max(0, Math.min(1, (v - r.min) / (r.max - r.min))) * 100;
	}
	function color(k: string, v: number) {
		if (k === 'bz_gsm') return v < 0 ? 'var(--bad)' : 'var(--ok)'; // southward Bz = geoeffective
		return 'var(--signal)';
	}
</script>

{#if mode === 'meteo'}
	<div class="gauges">
		{#each entries as [k, v]}
			<div class="gauge">
				<span class="lbl mono">{k}</span>
				<div class="track"><div class="fill" style="width:{pct(k, +v)}%; background:{color(k, +v)}"></div></div>
				<span class="val mono">{v ?? '—'}{METEO[k] ? ' ' + METEO[k].unit : ''}</span>
			</div>
		{/each}
		{#if entries.length === 0}<div class="empty">waiting for space-weather data…</div>{/if}
	</div>
{:else}
	<div class="tbl">
		{#each entries as [k, v]}
			<div class="row"><span class="k mono">{k}</span><span class="v mono">{typeof v === 'object' ? JSON.stringify(v) : v}</span></div>
		{/each}
		{#if entries.length === 0}<div class="empty">waiting for data…</div>{/if}
	</div>
{/if}

<style>
	.tbl { display: flex; flex-direction: column; gap: 2px; max-height: 220px; overflow: auto; }
	.row { display: flex; justify-content: space-between; gap: 12px; padding: 3px 6px; border-bottom: 1px solid var(--line); }
	.k { color: var(--muted); font-size: 11px; }
	.v { color: var(--text); font-size: 11px; }
	.empty { color: var(--faint); font-size: 12px; padding: 8px; }
	.gauges { display: flex; flex-direction: column; gap: 7px; }
	.gauge { display: grid; grid-template-columns: 76px 1fr 92px; align-items: center; gap: 8px; }
	.gauge .lbl { font-size: 11px; color: var(--muted); }
	.gauge .track { height: 8px; background: var(--ink); border: 1px solid var(--line); border-radius: 4px; overflow: hidden; }
	.gauge .fill { height: 100%; transition: width 0.3s ease; }
	.gauge .val { font-size: 11px; color: var(--text); text-align: right; }
</style>
