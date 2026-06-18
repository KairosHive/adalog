<script lang="ts">
	import { recorder, type DeviceType } from '$lib/app/session.svelte';

	// Auto-generated config editor for one device, driven by its config_schema. A string
	// field named source/device/port becomes a live discovery dropdown (LSL streams, audio
	// devices, serial ports, MIDI inputs) refreshed from the backend's device_discover.
	let { device, config }: { device: DeviceType; config: Record<string, Record<string, any>> } = $props();

	const DISCOVER_FIELDS = ['source', 'device', 'port'];
	type FieldSpec = { type: string; default: any; doc?: string; enum?: string[]; minimum?: number; maximum?: number };
	const groups = $derived<Record<string, Record<string, FieldSpec>>>(device.config_schema?.groups ?? {});

	// the (group, field) the discovery dropdown binds to — first string source/device/port
	const discoverTarget = $derived.by(() => {
		for (const [g, fields] of Object.entries(groups))
			for (const [f, spec] of Object.entries(fields))
				if (DISCOVER_FIELDS.includes(f) && spec.type === 'string') return { g, f };
		return null;
	});

	let sources = $state<{ id: string; label: string }[]>([]);
	let loading = $state(false);
	async function refresh() {
		loading = true;
		sources = await recorder.discover(device.id);
		loading = false;
	}
	$effect(() => { if (discoverTarget) refresh(); });

	function set(g: string, f: string, v: any) { config[g][f] = v; }
</script>

<div class="cfg">
	{#each Object.entries(groups) as [g, fields]}
		{#each Object.entries(fields) as [f, spec]}
			{@const isDisc = discoverTarget && discoverTarget.g === g && discoverTarget.f === f}
			<label class="row">
				<span class="key mono" title={spec.doc}>{f}</span>
				{#if isDisc}
					<span class="disc">
						<select value={config[g][f]} onchange={(e) => set(g, f, e.currentTarget.value)}>
							<option value="">{loading ? 'scanning…' : 'auto / first'}</option>
							{#each sources as s}<option value={s.id}>{s.label || s.id}</option>{/each}
						</select>
						<button class="refresh" title="rescan" onclick={refresh} disabled={loading}>⟳</button>
					</span>
				{:else if spec.enum}
					<select value={config[g][f]} onchange={(e) => set(g, f, e.currentTarget.value)}>
						{#each spec.enum as opt}<option value={opt}>{opt}</option>{/each}
					</select>
				{:else if spec.type === 'boolean'}
					<input type="checkbox" checked={config[g][f]} onchange={(e) => set(g, f, e.currentTarget.checked)} />
				{:else if spec.type === 'integer' || spec.type === 'number'}
					<input type="number" value={config[g][f]} min={spec.minimum} max={spec.maximum}
						step={spec.type === 'integer' ? 1 : 'any'}
						onchange={(e) => set(g, f, e.currentTarget.valueAsNumber)} />
				{:else}
					<input type="text" value={config[g][f]} placeholder={spec.doc}
						onchange={(e) => set(g, f, e.currentTarget.value)} />
				{/if}
			</label>
			{#if spec.doc}<div class="doc">{spec.doc}</div>{/if}
		{/each}
	{/each}
</div>

<style>
	.cfg { display: flex; flex-direction: column; gap: 6px; padding: 8px 4px 4px; }
	.row { display: flex; align-items: center; gap: 10px; }
	.key { font-size: 12px; color: var(--muted); min-width: 92px; }
	.row > select, .row > input[type='text'], .row > input[type='number'] { flex: 1; min-width: 0; }
	.disc { flex: 1; display: flex; gap: 6px; align-items: center; }
	.disc select { flex: 1; min-width: 0; }
	.refresh { flex: none; padding: 6px 9px; }
	.doc { font-size: 10px; color: var(--faint); margin: -2px 0 4px 102px; line-height: 1.3; }
</style>
