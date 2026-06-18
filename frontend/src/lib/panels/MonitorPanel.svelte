<script lang="ts">
	import { recorder } from '$lib/app/session.svelte';
	import { monitorFor } from '$lib/monitors/registry';
	import QualityStrip from '$lib/monitors/QualityStrip.svelte';

	// One monitor per armed device instance — hyperscanning shows N stacked cards that share
	// the panel height (each with a floor) so signals get a real size budget, not a sliver.
	function streamFor(dev: any, localId?: string) {
		if (!dev.streams?.length) return null;
		if (localId) return dev.streams.find((s: any) => s.local_id === localId) ?? dev.streams[0];
		return dev.streams[0];
	}
	const armed = $derived(recorder.armed);
</script>

<div class="monitors">
	{#if armed.length === 0}
		<div class="empty-fill">
			<span class="eyebrow">device monitors</span>
			<p>Arm a device to watch its signal here.</p>
		</div>
	{/if}
	{#each armed as dev (dev.node_id)}
		{@const spec = monitorFor(dev.adapter_id)}
		{@const st = recorder.statuses[dev.node_id]}
		<section class="card">
			<header>
				<span class="dot" class:on={st?.state === 'streaming'}></span>
				<span class="node mono">{dev.node_id}</span>
				{#if st?.rate_est}<span class="rate mono">{st.rate_est.toFixed(0)} Hz</span>{/if}
			</header>
			<QualityStrip nodeId={dev.node_id} />
			<div class="body">
				{#if spec}
					{@const Comp = spec.component}
					{@const stream = streamFor(dev, spec.streamLocalId)}
					{#if spec.input}
						<Comp nodeId={dev.node_id} {...(spec.props?.(stream) ?? {})} />
					{:else if stream}
						<Comp nodeId={dev.node_id} {stream} {...(spec.props?.(stream) ?? {})} />
					{:else}
						<div class="empty">no stream</div>
					{/if}
				{:else}
					<div class="empty">no monitor for {dev.adapter_id}</div>
				{/if}
			</div>
		</section>
	{/each}
</div>

<style>
	.monitors { display: flex; flex-direction: column; gap: 12px; padding: 14px; height: 100%; overflow: auto; }
	.card { display: flex; flex-direction: column; flex: 1 1 240px; min-height: 220px;
		border: 1px solid var(--line); border-radius: var(--r); padding: 10px; background: var(--surface); }
	header { display: flex; align-items: center; gap: 8px; flex: none; }
	.dot { width: 7px; height: 7px; border-radius: 50%; background: var(--faint); flex: none; }
	.dot.on { background: var(--signal); box-shadow: 0 0 6px var(--signal); }
	.node { font-size: 12px; color: var(--text); }
	.rate { margin-left: auto; font-size: 10px; color: var(--muted); }
	/* the monitor component fills the remaining card height (trace canvases are container-driven) */
	.body { flex: 1; min-height: 0; display: flex; flex-direction: column; }
	.empty { flex: 1; display: grid; place-items: center; color: var(--faint); font-size: 12px;
		border: 1px dashed var(--line); border-radius: var(--r); }
	.empty-fill { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
		gap: 8px; color: var(--faint); }
	.empty-fill p { margin: 0; font-size: 13px; }
</style>
