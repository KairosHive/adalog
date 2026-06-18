<script lang="ts">
	import { recorder, type DeviceType } from '$lib/app/session.svelte';
	import DeviceConfig from './DeviceConfig.svelte';

	const canArm = $derived(recorder.sessionState === 'created');
	const byCategory = $derived.by(() => {
		const m: Record<string, DeviceType[]> = {};
		for (const d of recorder.catalog) (m[d.category || 'other'] ??= []).push(d);
		return m;
	});

	function armedCount(id: string) { return recorder.armed.filter((d) => d.adapter_id === id).length; }

	// per-device config (lazily seeded from schema defaults) + which cards are expanded
	let configs = $state<Record<string, Record<string, Record<string, any>>>>({});
	let open = $state<Record<string, boolean>>({});

	function defaultsFor(schema: any): Record<string, Record<string, any>> {
		const out: Record<string, Record<string, any>> = {};
		for (const [g, fields] of Object.entries(schema?.groups ?? {}) as [string, any][]) {
			out[g] = {};
			for (const [f, spec] of Object.entries(fields) as [string, any][]) out[g][f] = spec.default;
		}
		return out;
	}
	function ensure(d: DeviceType) { configs[d.id] ??= defaultsFor(d.config_schema); return configs[d.id]; }
	function hasConfig(d: DeviceType) { return Object.keys(d.config_schema?.groups ?? {}).length > 0; }
	function toggle(d: DeviceType) { ensure(d); open[d.id] = !open[d.id]; }

	async function arm(d: DeviceType) {
		if (!canArm || !d.available) return;
		await recorder.armDevice(d.id, configs[d.id] ? $state.snapshot(configs[d.id]) : {});
	}
</script>

<div class="devices">
	<span class="eyebrow">devices {canArm ? '· tap to arm' : '· create a session to arm'}</span>
	{#each Object.entries(byCategory) as [cat, list]}
		<div class="group">
			<div class="cat mono">{cat}</div>
			{#each list as d}
				{@const n = armedCount(d.id)}
				{@const err = recorder.armErrors[d.id]}
				<div class="card" class:armed={n > 0} class:unavailable={!d.available}>
					<button class="arm" data-testid={`arm-${d.id}`}
						disabled={!canArm || !d.available || (!d.multi && n > 0)}
						title={d.available ? '' : `backend not installed${d.backend ? ` (${d.backend})` : ''}`}
						onclick={() => arm(d)}>
						<span class="card-main">
							<span class="title">{d.title}</span>
							{#if !d.available}<span class="req mono">backend not installed{d.backend ? ` · ${d.backend}` : ''}</span>
							{:else if d.requires}<span class="req mono">needs {d.requires}</span>{/if}
						</span>
						{#if n > 0}<span class="badge mono">×{n}</span>{/if}
					</button>
					{#if hasConfig(d) && d.available}
						<button class="gear" class:on={open[d.id]} title="configure"
							data-testid={`cfg-${d.id}`} onclick={() => toggle(d)}>⚙</button>
					{/if}
				</div>
				{#if open[d.id] && configs[d.id]}<DeviceConfig device={d} config={configs[d.id]} />{/if}
				{#if err}<div class="arm-err">{err}</div>{/if}
			{/each}
		</div>
	{/each}
	{#if recorder.catalog.length === 0}<div class="empty">connecting to recorder…</div>{/if}
</div>

<style>
	.devices { display: flex; flex-direction: column; gap: 14px; padding: 16px; height: 100%; overflow: auto; }
	.group { display: flex; flex-direction: column; gap: 6px; }
	.cat { font-size: 10px; letter-spacing: 0.15em; text-transform: uppercase; color: var(--faint); margin-bottom: 2px; }
	.card { display: flex; align-items: stretch; gap: 0; border: 1px solid var(--line); border-radius: var(--r);
		background: var(--surface); overflow: hidden; }
	.card.armed { border-color: var(--signal); }
	.card.unavailable { opacity: 0.5; }
	.card .arm { flex: 1; display: flex; align-items: center; justify-content: space-between; text-align: left;
		border: none; border-radius: 0; background: transparent; }
	.gear { flex: none; border: none; border-left: 1px solid var(--line); border-radius: 0; background: transparent;
		color: var(--muted); font-size: 15px; padding: 0 12px; }
	.gear.on { color: var(--signal); }
	.card-main { display: flex; flex-direction: column; gap: 2px; }
	.title { font-size: 14px; }
	.req { font-size: 11px; color: var(--faint); }
	.badge { color: var(--signal); font-size: 13px; }
	.arm-err { color: var(--bad); font-size: 11px; padding: 2px 4px 6px; line-height: 1.3; }
	.empty { color: var(--faint); font-size: 12px; }
</style>
