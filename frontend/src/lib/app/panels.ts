/** Register adalog's panels + seed the default instrument layout. */
import { registerPanel } from '$lib/workspace/registry';
import { registerBuiltinPanels } from '$lib/workspace/panels';
import { workspace } from '$lib/workspace/workspace.svelte';
import { uid, type WorkspaceState } from '$lib/workspace/model';
import DevicePanel from '$lib/panels/DevicePanel.svelte';
import MonitorPanel from '$lib/panels/MonitorPanel.svelte';

let done = false;
export function setupWorkspace(): void {
	if (done) return;
	done = true;
	registerBuiltinPanels();
	// The recording transport (clock + controls) lives in the shell chrome, not a panel — so
	// the workspace holds only the content panels you arrange while recording.
	registerPanel({ id: 'devices', title: 'Devices', icon: '◧', component: DevicePanel as any });
	registerPanel({ id: 'monitor', title: 'Monitors', icon: '∿', component: MonitorPanel as any });

	const panel = (panelType: string) => ({ kind: 'panel' as const, id: uid('panel'), panelType });
	// Cockpit default: a Devices rail on the left, the Monitors taking the dominant area.
	const layout: WorkspaceState = {
		workspaces: [{
			id: uid('ws'), name: 'Record',
			root: {
				kind: 'split', id: uid('split'), direction: 'row', sizes: [0.3, 0.7],
				children: [panel('devices'), panel('monitor')]
			}
		}],
		activeWorkspaceId: ''
	};
	layout.activeWorkspaceId = layout.workspaces[0].id;
	workspace().state = layout;
}
