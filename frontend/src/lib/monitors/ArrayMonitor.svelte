<script lang="ts">
	import { untrack } from 'svelte';
	import { subscribe } from '$lib/api/data';
	import { fitCanvas, logicalSize } from './canvas';

	let { nodeId, stream }: { nodeId: string; stream: any } = $props();
	// Snapshot the identity once — the parent reassigns `armed` (and thus the `stream`
	// object reference) on every arm, so reading stream.id INSIDE the effect would churn
	// the socket on each rapid arm→record click. node id + stream id never change here.
	const NODE = untrack(() => nodeId);
	const SID = untrack(() => stream.id);
	const channels: string[] = untrack(() => (stream.channels?.length ? stream.channels : ['v']));
	const nch = channels.length;
	const CAP = 500;
	let rings: number[][] = channels.map(() => []);
	let canvas: HTMLCanvasElement | undefined = $state();

	$effect(() => {
		// subscribe once on mount (device armed) and keep it across preview → record →
		// pause — do NOT depend on sessionState, or the WS churns and the canvas blanks.
		const unsub = subscribe(NODE, SID, (_h, value) => {
			if (!value || !value.length) return;
			const arr = value as Float32Array;
			for (let i = 0; i + nch <= arr.length; i += nch) {
				for (let c = 0; c < nch; c++) rings[c].push(arr[i + c]);
			}
			for (let c = 0; c < nch; c++) if (rings[c].length > CAP) rings[c] = rings[c].slice(-CAP);
			draw();
		});
		return unsub;
	});

	function draw() {
		const cv = canvas; if (!cv) return;
		const ctx = cv.getContext('2d'); if (!ctx) return;
		const { w, h } = logicalSize(cv, ctx);   // CSS-pixel space; canvas fills its card
		const lane = h / nch;
		ctx.clearRect(0, 0, w, h);
		const accent = getComputedStyle(document.documentElement).getPropertyValue('--signal') || '#FFB454';
		for (let c = 0; c < nch; c++) {
			const r = rings[c]; if (r.length < 2) continue;
			let mn = Math.min(...r), mx = Math.max(...r); if (mx === mn) mx = mn + 1;
			const y0 = c * lane;
			ctx.strokeStyle = accent; ctx.globalAlpha = 0.9; ctx.lineWidth = 1; ctx.beginPath();
			r.forEach((v, i) => {
				const x = (i / (CAP - 1)) * w;
				const y = y0 + lane - ((v - mn) / (mx - mn)) * (lane - 8) - 4;
				i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
			});
			ctx.stroke();
			ctx.globalAlpha = 1; ctx.fillStyle = 'var(--muted)'; ctx.fillStyle = '#8A95A5';
			ctx.font = '10px monospace';
			ctx.fillText(channels[c], 5, y0 + 12);
			ctx.strokeStyle = '#2A323D'; ctx.globalAlpha = 1; ctx.lineWidth = 1;
			ctx.beginPath(); ctx.moveTo(0, y0 + lane); ctx.lineTo(w, y0 + lane); ctx.stroke();  // lane divider
		}
	}
</script>

<canvas bind:this={canvas} use:fitCanvas={draw}></canvas>

<style>
	canvas { flex: 1; min-height: 0; width: 100%; height: 100%; display: block;
		background: var(--ink); border-radius: var(--r); }
</style>
