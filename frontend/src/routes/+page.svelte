<script lang="ts">
	import { onMount } from 'svelte';
	import WorkspaceTabs from '$lib/workspace/WorkspaceTabs.svelte';
	import WorkspaceView from '$lib/workspace/WorkspaceView.svelte';
	import { setupWorkspace } from '$lib/app/panels';
	import { recorder } from '$lib/app/session.svelte';

	let ready = $state(false);
	let error = $state<string | null>(null);

	onMount(async () => {
		setupWorkspace();
		try {
			await recorder.init();
		} catch (e) {
			error = 'Could not reach the recorder backend. Is `adalog-sense` running?';
		}
		ready = true;
	});
</script>

<div class="shell">
	<header class="topbar">
		<div class="brand">
			<span class="logo mono">adalog<span class="accent">·sense</span></span>
			<span class="eyebrow">multimodal recorder</span>
		</div>
		<div class="conn">
			<span class="dot" class:on={recorder.connected}></span>
			<span class="mono">{recorder.connected ? 'backend connected' : 'offline'}</span>
		</div>
	</header>

	{#if error}
		<div class="banner">{error}</div>
	{/if}

	<div class="tabs"><WorkspaceTabs /></div>
	<main class="work">
		{#if ready}<WorkspaceView />{/if}
	</main>
</div>

<style>
	.shell { display: flex; flex-direction: column; height: 100vh; background: var(--ink); }
	.topbar { display: flex; align-items: center; justify-content: space-between;
		padding: 10px 16px; border-bottom: 1px solid var(--line); }
	.brand { display: flex; align-items: baseline; gap: 12px; }
	.logo { font-size: 17px; font-weight: 700; letter-spacing: 0.02em; }
	.logo .accent { color: var(--signal); }
	.conn { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--muted); }
	.conn .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--bad); }
	.conn .dot.on { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
	.banner { background: rgba(255,92,108,0.12); border-bottom: 1px solid var(--bad);
		color: var(--text); padding: 8px 16px; font-size: 13px; }
	.tabs { border-bottom: 1px solid var(--line); }
	.work { flex: 1; min-height: 0; }
</style>
