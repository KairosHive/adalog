<script lang="ts">
	import { recorder } from '$lib/app/session.svelte';

	let { nodeId }: { nodeId: string } = $props();
	let canvas: HTMLCanvasElement | undefined = $state();
	let drawing = false;
	let strokeId = 0;
	let pending: any[] = [];
	let color = $state('#C792EA');   // brush colour — captured per pen point for faithful replay
	let size = $state(2);            // brush width
	const active = $derived(recorder.sessionState === 'recording');

	// clear the canvas at the start of each recording (matches the old panel's reset)
	let wasActive = false;
	$effect(() => {
		if (active && !wasActive) clear();
		wasActive = active;
	});

	function nowNs() { return Math.round(performance.now() * 1e6); }
	function pos(e: PointerEvent) {
		const r = canvas!.getBoundingClientRect();
		return { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
	}
	function down(e: PointerEvent) {
		if (!active) return;
		drawing = true; strokeId++;
		canvas!.setPointerCapture(e.pointerId);
		const ctx = canvas!.getContext('2d')!; const p = pos(e);
		ctx.beginPath(); ctx.moveTo(p.x * canvas!.width, p.y * canvas!.height);
		emit(e, p);
	}
	function move(e: PointerEvent) {
		if (!drawing) return;
		const ctx = canvas!.getContext('2d')!; const p = pos(e);
		ctx.lineTo(p.x * canvas!.width, p.y * canvas!.height);
		ctx.strokeStyle = color; ctx.lineWidth = size; ctx.lineCap = 'round'; ctx.stroke();
		emit(e, p);
	}
	function up() {
		if (!drawing) return;
		drawing = false; flush(); snapshot();
	}
	function emit(e: PointerEvent, p: { x: number; y: number }) {
		pending.push({ kind: 'pen', x: +p.x.toFixed(4), y: +p.y.toFixed(4),
			pressure: e.pressure || 0.5, stroke_id: strokeId, color, width: size, t_browser_ns: nowNs() });
		if (pending.length >= 8) flush();
	}
	function flush() {
		if (pending.length && active) { recorder.ingest(nodeId, pending); }
		pending = [];
	}
	function snapshot() {
		if (!active || !canvas) return;
		const b64 = canvas.toDataURL('image/png').split(',')[1];
		recorder.ingest(nodeId, [{ kind: 'snapshot', png_b64: b64, t_browser_ns: nowNs() }]);
	}
	function clear() {
		const ctx = canvas?.getContext('2d'); if (ctx && canvas) ctx.clearRect(0, 0, canvas.width, canvas.height);
	}
</script>

<canvas bind:this={canvas} width="520" height="320"
	onpointerdown={down} onpointermove={move} onpointerup={up} onpointerleave={up}
	data-testid={`drawing-${nodeId}`} class:active style="--brush:{color}"></canvas>
<div class="ctl">
	<label class="swatch" title="pen colour">
		<input type="color" bind:value={color} data-testid={`draw-color-${nodeId}`} />
	</label>
	<label class="size" title="pen size">
		<input type="range" min="1" max="30" bind:value={size} data-testid={`draw-size-${nodeId}`} />
		<span class="mono">{size}px</span>
	</label>
	<button onclick={clear} data-testid={`draw-clear-${nodeId}`}>Clear</button>
	<span class="rd mono">{active ? 'pen-traces + snapshots recording' : 'recording not started'}</span>
</div>

<style>
	canvas { width: 100%; background: var(--ink); border: 1px solid var(--line); border-radius: var(--r); touch-action: none; cursor: crosshair; }
	canvas.active { border-color: var(--brush); }
	.ctl { display: flex; align-items: center; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
	.swatch input { width: 34px; height: 28px; padding: 2px; border: 1px solid var(--line); border-radius: var(--r); background: var(--surface); cursor: pointer; }
	.size { display: flex; align-items: center; gap: 6px; }
	.size input { width: 90px; }
	.size .mono { font-size: 11px; color: var(--muted); min-width: 32px; }
	.rd { font-size: 11px; color: var(--muted); margin-left: auto; }
</style>
