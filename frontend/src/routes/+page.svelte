<script lang="ts">
	import { onMount } from 'svelte';
	import WorkspaceTabs from '$lib/workspace/WorkspaceTabs.svelte';
	import WorkspaceView from '$lib/workspace/WorkspaceView.svelte';
	import { workspace } from '$lib/workspace/workspace.svelte';
	import { listPanelTypes } from '$lib/workspace/registry';
	import { setupWorkspace } from '$lib/app/panels';
	import { recorder } from '$lib/app/session.svelte';

	let ready = $state(false);
	let error = $state<string | null>(null);
	let toast = $state<string | null>(null);
	let addOpen = $state(false);

	onMount(async () => {
		setupWorkspace();
		// Safety net: surface any stray rejection (e.g. a failed control call) as a toast
		// instead of an "Uncaught (in promise)" in the console.
		window.addEventListener('unhandledrejection', (e) => {
			const m = (e.reason && (e.reason.message || e.reason)) ?? 'Unexpected error';
			showToast(String(m));
		});
		try {
			await recorder.init();
		} catch (e) {
			error = 'Could not reach the recorder backend. Is `adalog-sense` running?';
		}
		ready = true;
	});

	function showToast(msg: string) {
		toast = msg;
		setTimeout(() => (toast = null), 5000);
	}

	const ws = workspace();
	const panelTypes = $derived(listPanelTypes().filter((t) => t.id !== 'empty'));

	function addPanel(typeId: string) {
		addOpen = false;
		const active = ws.activePanelId;
		if (!active) return;
		ws.split(active, 'row', false, typeId); // new panel of the chosen type, to the right
	}
</script>

<div class="shell">
	<header class="topbar">
		<div class="brand">
			<span class="logo mono">adalog<span class="accent">·sense</span></span>
			<span class="eyebrow">multimodal recorder</span>
		</div>
		<div class="actions">
			<div class="add-wrap">
				<button class="add-panel" onclick={() => (addOpen = !addOpen)} title="Add a panel to the workspace">
					＋ Add panel
				</button>
				{#if addOpen}
					<div class="add-menu" role="menu">
						{#each panelTypes as t (t.id)}
							<button class="add-item" role="menuitem" onclick={() => addPanel(t.id)}>
								<span class="ic">{t.icon ?? '▢'}</span>{t.title}
							</button>
						{/each}
					</div>
				{/if}
			</div>
			<div class="conn">
				<span class="dot" class:on={recorder.connected}></span>
				<span class="mono">{recorder.connected ? 'backend connected' : 'offline'}</span>
			</div>
		</div>
	</header>

	{#if error}<div class="banner">{error}</div>{/if}

	<div class="tabs"><WorkspaceTabs /></div>
	<main class="work">
		{#if ready}<WorkspaceView />{/if}
	</main>

	{#if toast}<div class="toast">{toast}</div>{/if}
</div>

<style>
	.shell { display: flex; flex-direction: column; height: 100vh; background: var(--ink); }
	.topbar { display: flex; align-items: center; justify-content: space-between;
		padding: 10px 16px; border-bottom: 1px solid var(--line); gap: 16px; }
	.brand { display: flex; align-items: baseline; gap: 12px; }
	.logo { font-size: 17px; font-weight: 700; letter-spacing: 0.02em; }
	.logo .accent { color: var(--signal); }
	.actions { display: flex; align-items: center; gap: 16px; }
	.add-wrap { position: relative; }
	.add-panel { background: var(--surface-2); border-color: var(--line-bright); font-weight: 600; }
	.add-menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 200;
		background: var(--surface-2); border: 1px solid var(--line-bright); border-radius: var(--r);
		box-shadow: var(--shadow-2); padding: 6px; display: flex; flex-direction: column; gap: 2px; min-width: 180px; }
	.add-item { display: flex; align-items: center; gap: 10px; justify-content: flex-start;
		background: transparent; border: none; min-height: 34px; width: 100%; text-align: left; }
	.add-item:hover { background: var(--surface-3); }
	.add-item .ic { color: var(--signal); width: 18px; text-align: center; }
	.conn { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--muted); }
	.conn .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--bad); }
	.conn .dot.on { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
	.banner { background: rgba(255,92,108,0.12); border-bottom: 1px solid var(--bad);
		color: var(--text); padding: 8px 16px; font-size: 13px; }
	.tabs { border-bottom: 1px solid var(--line); }
	.work { flex: 1; min-height: 0; }
	.toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 300;
		background: var(--surface-3); border: 1px solid var(--bad); color: var(--text);
		padding: 10px 16px; border-radius: var(--r); box-shadow: var(--shadow-2); font-size: 13px; max-width: 70vw; }
</style>
