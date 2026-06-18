<script lang="ts">
	import { untrack } from 'svelte';
	import { subscribe } from '$lib/api/data';
	import { fitCanvas, logicalSize } from './canvas';

	let { nodeId, stream, field = 'raw' }: { nodeId: string; stream: any; field?: string } = $props();
	const NODE = untrack(() => nodeId), SID = untrack(() => stream.id); // snapshot ids — see ArrayMonitor
	const CAP = 600;
	let ring: number[] = [];
	let canvas: HTMLCanvasElement | undefined = $state();
	let last = $state<number | null>(null);

	$effect(() => {
		const unsub = subscribe(NODE, SID, (_h, value) => {
			let v: number | undefined;
			if (typeof value === 'string') { try { v = JSON.parse(value)[field]; } catch {} }
			if (typeof v === 'number') {
				ring.push(v); last = v;
				if (ring.length > CAP) ring = ring.slice(-CAP);
				draw();
			}
		});
		return unsub;
	});

	function draw() {
		const cv = canvas; if (!cv) return;
		const ctx = cv.getContext('2d'); if (!ctx) return;
		const { w, h } = logicalSize(cv, ctx);
		ctx.clearRect(0, 0, w, h);
		if (ring.length < 2) return;
		let mn = Math.min(...ring), mx = Math.max(...ring); if (mx === mn) mx = mn + 1;
		ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--ch-ecg') || '#FF6E8A';
		ctx.lineWidth = 1.3; ctx.beginPath();
		ring.forEach((v, i) => {
			const x = (i / (CAP - 1)) * w, y = h - ((v - mn) / (mx - mn)) * (h - 8) - 4;
			i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
		});
		ctx.stroke();
	}
</script>

<div class="trace"><canvas bind:this={canvas} use:fitCanvas={draw}></canvas></div>
<span class="rd mono">{field}: {last ?? '—'}</span>

<style>
	.trace { flex: 1; min-height: 0; }
	canvas { width: 100%; height: 100%; display: block; background: var(--ink); border-radius: var(--r); }
	.rd { font-size: 11px; color: var(--muted); flex: none; }
</style>
