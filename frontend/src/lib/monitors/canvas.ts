/** Svelte action: size a canvas's backing store to its CSS box × devicePixelRatio and
 * redraw on resize — so traces fill their card crisply instead of a fixed letterboxed size.
 * draw() should map to logical (CSS) coordinates via ctx.setTransform(dpr,0,0,dpr,0,0). */
export function fitCanvas(canvas: HTMLCanvasElement, redraw: () => void) {
	let cb = redraw;
	function apply() {
		const dpr = window.devicePixelRatio || 1;
		const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
		const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
		if (canvas.width !== w || canvas.height !== h) {
			canvas.width = w;
			canvas.height = h;
		}
		cb();
	}
	const ro = new ResizeObserver(apply);
	ro.observe(canvas);
	apply();
	return {
		update(fn: () => void) { cb = fn; },
		destroy() { ro.disconnect(); }
	};
}

/** Logical (CSS-pixel) size of a DPR-scaled canvas, and prime the context transform so
 * subsequent drawing is in CSS pixels. Returns {w, h} in CSS px. */
export function logicalSize(canvas: HTMLCanvasElement, ctx: CanvasRenderingContext2D): { w: number; h: number } {
	const dpr = window.devicePixelRatio || 1;
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	return { w: canvas.width / dpr, h: canvas.height / dpr };
}
