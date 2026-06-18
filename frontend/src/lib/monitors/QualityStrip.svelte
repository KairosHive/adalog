<script lang="ts">
	import { recorder } from '$lib/app/session.svelte';

	// Per-device quality readout driven by status().quality — EEG headset HSI (per-channel
	// 0/1/2 dots, reproducing the old /eeg_quality indicator) or ECG BPM + HRV readouts.
	let { nodeId }: { nodeId: string } = $props();
	const q = $derived(recorder.statuses[nodeId]?.quality);

	const HSI = ['disconnected', 'check signal', 'good'];
	const HSI_COLOR = ['var(--bad)', 'var(--signal)', 'var(--ok)'];

	const isEeg = $derived(q && Array.isArray(q.hsi));
	const isEcg = $derived(q && 'bpm' in q);
	const isCount = $derived(q && 'count' in q && !isEeg && !isEcg);
	function fmt(v: number | null | undefined, suffix = '') {
		return v === null || v === undefined ? '—' : `${v}${suffix}`;
	}
</script>

{#if isEeg}
	<div class="hsi" title="headset signal quality (per electrode)">
		{#each q.hsi as code, i}
			<span class="ch">
				<span class="dot" style="background:{HSI_COLOR[code] ?? 'var(--faint)'}"
					title={HSI[code] ?? 'unknown'}></span>
				<span class="lbl mono">{q.channels?.[i] ?? `ch${i}`}</span>
			</span>
		{/each}
	</div>
{:else if isEcg}
	<div class="hrv">
		<div class="bpm"><span class="num mono">{fmt(q.bpm)}</span><span class="unit">BPM</span></div>
		<dl class="metrics mono">
			<div><dt>SDNN</dt><dd>{fmt(q.sdnn, ' ms')}</dd></div>
			<div><dt>SDSD</dt><dd>{fmt(q.sdsd, ' ms')}</dd></div>
			<div><dt>RMSSD</dt><dd>{fmt(q.rmssd, ' ms')}</dd></div>
		</dl>
	</div>
{:else if isCount}
	<div class="counter mono"><span class="n">{q.count}</span> messages received</div>
{/if}

<style>
	.hsi { display: flex; flex-wrap: wrap; gap: 12px; padding: 4px 2px 8px; }
	.ch { display: flex; align-items: center; gap: 5px; }
	.dot { width: 9px; height: 9px; border-radius: 50%; box-shadow: 0 0 6px currentColor; flex: none; }
	.lbl { font-size: 11px; color: var(--muted); }
	.hrv { display: flex; align-items: center; gap: 16px; padding: 4px 2px 8px; }
	.bpm { display: flex; align-items: baseline; gap: 5px; }
	.bpm .num { font-size: 26px; font-weight: 600; color: var(--signal); line-height: 1; }
	.bpm .unit { font-size: 11px; color: var(--muted); }
	.metrics { display: flex; gap: 14px; margin: 0; }
	.metrics div { display: flex; flex-direction: column; }
	.metrics dt { font-size: 10px; color: var(--faint); text-transform: uppercase; letter-spacing: 0.04em; }
	.metrics dd { margin: 0; font-size: 12px; color: var(--text); }
	.counter { font-size: 12px; color: var(--muted); padding: 4px 2px 8px; }
	.counter .n { color: var(--signal); font-size: 14px; }
</style>
