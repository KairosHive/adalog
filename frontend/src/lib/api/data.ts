/** Data-plane client: one binary WS per (node, slot); latest-wins; decodes GOOF frames.
 * Reconnects on unexpected close — a monitor armed during preview survives the rapid
 * arm→record churn (a socket killed mid-handshake, "closed before established", must
 * recover or the canvas stays blank). */
import { decodeFrame } from './codec';

export function subscribe(node: string, slot: string, cb: (header: any, value: any) => void): () => void {
	// node ids contain '#' (e.g. eeg_muse#0) — encode each segment so it isn't parsed
	// as a URL fragment, which would silently break the data subscription.
	const path = `${encodeURIComponent(node)}/${encodeURIComponent(slot)}`;
	const url = `ws://${location.host}/ws/data/${path}`;
	let ws: WebSocket | null = null;
	let closed = false;
	let retry: ReturnType<typeof setTimeout> | undefined;

	function open() {
		if (closed) return;
		ws = new WebSocket(url);
		ws.binaryType = 'arraybuffer';
		ws.onmessage = (ev) => {
			try {
				const { header, value } = decodeFrame(new Uint8Array(ev.data));
				cb(header, value);
			} catch (e) { /* ignore malformed monitor frame */ }
		};
		ws.onclose = () => {
			if (closed) return;
			retry = setTimeout(open, 400); // reconnect after an unexpected drop
		};
		ws.onerror = () => { try { ws?.close(); } catch { /* noop */ } };
	}
	open();

	return () => {
		closed = true;
		clearTimeout(retry);
		try { ws?.close(); } catch { /* noop */ }
	};
}
