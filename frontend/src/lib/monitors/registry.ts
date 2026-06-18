/** Map a device adapter to its monitor/input component + per-stream config. */
import type { Component } from 'svelte';
import ArrayMonitor from './ArrayMonitor.svelte';
import ScalarTraceMonitor from './ScalarTraceMonitor.svelte';
import AudioMonitor from './AudioMonitor.svelte';
import TableMonitor from './TableMonitor.svelte';
import LogMonitor from './LogMonitor.svelte';
import TextInput from './TextInput.svelte';
import DrawingInput from './DrawingInput.svelte';

export interface MonitorSpec {
	component: Component<any>;
	/** extra props passed to the component (besides nodeId + stream). */
	props?: (stream: any) => Record<string, any>;
	/** which armed stream this monitor binds to (by local_id); default: first. */
	streamLocalId?: string;
	/** interactive input surfaces don't bind to a data stream. */
	input?: boolean;
}

const BY_ADAPTER: Record<string, MonitorSpec> = {
	eeg_muse: { component: ArrayMonitor },
	ecg_serial: { component: ScalarTraceMonitor, props: () => ({ field: 'raw' }) },
	audio_mic: { component: AudioMonitor, input: true },          // no data stream; reads status RMS
	osc: { component: TableMonitor, props: () => ({ mode: 'osc' }) },
	midi: { component: LogMonitor },
	meteo: { component: TableMonitor, props: () => ({ mode: 'meteo' }) },
	text: { component: TextInput, input: true },
	drawing: { component: DrawingInput, input: true, streamLocalId: 'pentrace' },
};

export function monitorFor(adapterId: string): MonitorSpec | null {
	return BY_ADAPTER[adapterId] ?? null;
}
