/** Central recorder state: wraps the control client, mirrors session + device status. */
import { control } from '$lib/api/control';

export interface DeviceType { id: string; title: string; category: string; multi: boolean; requires: string | null; available: boolean; backend: string | null; config_schema: any; }
export interface ArmedDevice { node_id: string; adapter_id: string; instance_id: string; streams: any[]; }
export interface StreamStatus { node_id: string; state: string; rate_est: number | null; quality: any; last_error: string | null; }

const USER_KEY = 'adalog.user';
const TAGS_KEY = 'adalog.recentTags';

class RecorderState {
	connected = $state(false);
	catalog = $state<DeviceType[]>([]);
	armed = $state<ArmedDevice[]>([]);
	sessionState = $state<'idle' | 'created' | 'armed' | 'recording' | 'paused' | 'complete'>('idle');
	sessionId = $state<string | null>(null);
	t0 = $state<number>(0);          // performance.now() at start, for the live clock
	statuses = $state<Record<string, StreamStatus>>({});
	events = $state<{ t: number; kind: string; detail: any }[]>([]);
	user = $state('');               // required identity — names the personal dataset
	label = $state('');
	tags = $state<string[]>([]);
	recentTags = $state<string[]>([]);  // autocomplete suggestions from prior sessions
	armErrors = $state<Record<string, string>>({});  // per-adapter arm failure messages
	userValid = $derived(this.user.trim().length > 0);

	async init() {
		// pre-fill the username + tag suggestions persisted from previous sessions
		try {
			this.user = localStorage.getItem(USER_KEY) ?? '';
			this.recentTags = JSON.parse(localStorage.getItem(TAGS_KEY) ?? '[]');
		} catch { /* no storage */ }
		await control.connect();
		this.connected = true;
		control.onEvent((e) => this.onEvent(e));
		const r = await control.call('list_devices');
		this.catalog = r.devices;
		setInterval(() => this.pollStatus(), 1000);
	}

	private onEvent(e: { event: string; payload: any }) {
		if (e.event === 'stream_status' || e.event === 'adapter_error') {
			this.events = [...this.events.slice(-50), { t: Date.now(), kind: e.event, detail: e.payload }];
		}
	}

	private async pollStatus() {
		if (this.sessionState === 'idle' || this.sessionState === 'complete') return;
		try {
			const s = await control.call('status');
			const map: Record<string, StreamStatus> = {};
			for (const st of s.streams) map[st.node_id] = st;
			this.statuses = map;
		} catch { /* between sessions */ }
	}

	async createSession() {
		const user = this.user.trim();
		if (!user) throw new Error('Enter a username before recording — it names your personal dataset.');
		// persist identity + tag history for next launch
		try {
			localStorage.setItem(USER_KEY, user);
			const merged = Array.from(new Set([...this.tags, ...this.recentTags])).slice(0, 50);
			this.recentTags = merged;
			localStorage.setItem(TAGS_KEY, JSON.stringify(merged));
		} catch { /* no storage */ }
		const r = await control.call('session_create', { user, label: this.label, tags: this.tags });
		this.sessionId = r.session_id;
		this.sessionState = 'created';
		this.armed = [];
		this.armErrors = {};
	}

	async discover(adapter_id: string): Promise<{ id: string; label: string; detail: any }[]> {
		try {
			const r = await control.call('device_discover', { adapter_id });
			return r.sources?.[adapter_id] ?? [];
		} catch {
			return [];
		}
	}

	async armDevice(adapter_id: string, config: Record<string, any> = {}) {
		const existing = this.armed.filter((d) => d.adapter_id === adapter_id).length;
		const instance_id = String(existing);
		try {
			const r = await control.call('device_arm', { adapter_id, instance_id, config });
			this.armed = [...this.armed, { node_id: r.node_id, adapter_id, instance_id, streams: r.streams }];
			const { [adapter_id]: _drop, ...rest } = this.armErrors;
			this.armErrors = rest;
		} catch (e: any) {
			// surface a clean message on the device card instead of an uncaught rejection
			this.armErrors = { ...this.armErrors, [adapter_id]: e?.message ?? String(e) };
		}
	}

	async start() {
		await control.call('session_arm');
		this.sessionState = 'armed';
		const r = await control.call('session_start');
		this.sessionState = 'recording';
		this.t0 = performance.now();
	}

	async pause() { await control.call('session_pause'); this.sessionState = 'paused'; }
	async resume() { await control.call('session_resume'); this.sessionState = 'recording'; }
	async stop() {
		const r = await control.call('session_stop', { publish: false });
		this.sessionState = 'complete';
		return r;
	}

	async ingest(node_id: string, batch: any[]) {
		return control.call('device_ingest', { node_id, batch });
	}

	reset() {
		this.sessionState = 'idle'; this.sessionId = null; this.armed = []; this.statuses = {}; this.events = [];
	}
}

export const recorder = new RecorderState();
