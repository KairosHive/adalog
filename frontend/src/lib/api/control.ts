/** Control-plane client: JSON-RPC over /ws/control + server-pushed events. */
export type Op = string;
export interface ControlEvent { event: string; payload: any; }

export class ControlClient {
	private ws: WebSocket | null = null;
	private nextId = 1;
	private pending = new Map<string, { resolve: (v: any) => void; reject: (e: any) => void }>();
	private listeners = new Set<(e: ControlEvent) => void>();
	connected = false;

	constructor(private url: string = `ws://${location.host}/ws/control`) {}

	connect(): Promise<void> {
		return new Promise((resolve) => {
			const ws = new WebSocket(this.url);
			this.ws = ws;
			ws.onopen = () => { this.connected = true; resolve(); };
			ws.onclose = () => { this.connected = false; setTimeout(() => this.connect(), 1000); };
			ws.onmessage = (ev) => this.onMessage(ev.data);
		});
	}

	private onMessage(data: string) {
		const msg = JSON.parse(data);
		if (msg.event) { this.listeners.forEach((l) => l(msg)); return; }
		const p = this.pending.get(String(msg.id));
		if (!p) return;
		this.pending.delete(String(msg.id));
		if (msg.ok) p.resolve(msg.result);
		else p.reject(msg.error);
	}

	call(op: Op, args: Record<string, any> = {}): Promise<any> {
		const id = String(this.nextId++);
		return new Promise((resolve, reject) => {
			if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
				reject(new Error('Not connected to the recorder backend.'));
				return;
			}
			this.pending.set(id, { resolve, reject });
			try {
				this.ws.send(JSON.stringify({ id, op, args }));
			} catch (e) {
				this.pending.delete(id);
				reject(e instanceof Error ? e : new Error(String(e)));
			}
		});
	}

	onEvent(cb: (e: ControlEvent) => void): () => void {
		this.listeners.add(cb);
		return () => this.listeners.delete(cb);
	}
}

export const control = new ControlClient();
