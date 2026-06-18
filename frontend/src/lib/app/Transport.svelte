<script lang="ts">
	// The always-visible recording transport: master clock + state-aware controls, plus the
	// inline new-session form when idle. Lives in the shell chrome (not a workspace panel) so
	// it can never be squished — the clock and Record button are always reachable.
	import { recorder } from '$lib/app/session.svelte';

	let elapsed = $state(0);
	let raf: number;
	function tick() {
		if (recorder.sessionState === 'recording') elapsed = (performance.now() - recorder.t0) / 1000;
		raf = requestAnimationFrame(tick);
	}
	$effect(() => { raf = requestAnimationFrame(tick); return () => cancelAnimationFrame(raf); });

	function fmt(s: number): string {
		const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
		const ms = Math.floor((s % 1) * 1000);
		return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
	}

	const idle = $derived(recorder.sessionState === 'idle' || recorder.sessionState === 'complete');
	const live = $derived(recorder.sessionState === 'recording' || recorder.sessionState === 'paused');

	let tagInput = $state('');
	function addTag() {
		const t = tagInput.trim();
		if (t && !recorder.tags.includes(t)) recorder.tags = [...recorder.tags, t];
		tagInput = '';
	}
	function removeTag(t: string) { recorder.tags = recorder.tags.filter((x) => x !== t); }
</script>

<section class="transport" data-testid="transport">
	<div class="clock-block">
		<span class="eyebrow">{live ? 'session time' : 'master clock'}</span>
		<div class="clock mono" class:live data-rec={recorder.sessionState === 'recording'} data-testid="clock">
			{fmt(elapsed)}
		</div>
	</div>

	{#if idle}
		<form class="new" onsubmit={(e) => { e.preventDefault(); if (recorder.userValid) recorder.createSession(); }}>
			<label class="field" class:missing={!recorder.userValid}>
				<span class="eyebrow">user · names your dataset</span>
				<input bind:value={recorder.user} placeholder="e.g. phil" data-testid="username"
					autocomplete="off" spellcheck="false" />
			</label>
			<label class="field">
				<span class="eyebrow">session label</span>
				<input bind:value={recorder.label} placeholder="optional" />
			</label>
			<div class="field tags-field">
				<span class="eyebrow">tags</span>
				<div class="tags">
					{#each recorder.tags as t}<button type="button" class="tag" onclick={() => removeTag(t)}>{t} ✕</button>{/each}
					<input class="tag-input" bind:value={tagInput} list="recent-tags" placeholder="add tag…"
						onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), addTag())} />
					<datalist id="recent-tags">{#each recorder.recentTags as rt}<option value={rt}></option>{/each}</datalist>
				</div>
			</div>
		</form>
	{:else}
		<div class="session-id">
			<span class="eyebrow">session</span>
			<span class="mono name">{recorder.label || 'untitled'}</span>
			<span class="mono id">{recorder.sessionId}</span>
		</div>
	{/if}

	<div class="controls">
		{#if idle}
			<button class="primary" data-testid="new-session" disabled={!recorder.userValid}
				title={recorder.userValid ? '' : 'Enter a username first'}
				onclick={() => recorder.createSession()}>New session</button>
		{:else if recorder.sessionState === 'created'}
			<button class="rec" data-testid="record" disabled={recorder.armed.length === 0}
				onclick={() => recorder.start()}>● Record</button>
			<span class="hint">{recorder.armed.length} armed</span>
		{:else if recorder.sessionState === 'recording'}
			<button onclick={() => recorder.pause()}>Pause</button>
			<button class="danger" data-testid="stop" onclick={() => recorder.stop()}>■ Stop</button>
		{:else if recorder.sessionState === 'paused'}
			<button class="primary" onclick={() => recorder.resume()}>Resume</button>
			<button class="danger" data-testid="stop" onclick={() => recorder.stop()}>■ Stop</button>
		{/if}
		{#if recorder.sessionState === 'complete'}
			<button onclick={() => recorder.reset()}>Clear</button>
		{/if}
	</div>
</section>

<style>
	.transport {
		display: flex; align-items: center; gap: 22px; padding: 10px 18px;
		border-bottom: 1px solid var(--line); background: var(--surface); min-height: 64px;
	}
	.clock-block { display: flex; flex-direction: column; gap: 3px; flex: none; }
	.clock { font-size: 30px; font-weight: 600; letter-spacing: 0.02em; color: var(--muted); line-height: 1; }
	.clock.live { color: var(--text); }
	.clock[data-rec='true'] { color: var(--rec); text-shadow: 0 0 16px rgba(255, 77, 94, 0.4); }

	.new { display: flex; align-items: flex-end; gap: 14px; flex: 1; min-width: 0; flex-wrap: wrap; }
	.field { display: flex; flex-direction: column; gap: 4px; }
	.field input { min-width: 120px; }
	.field.missing input { border-color: var(--signal); }
	.tags-field { flex: 1; min-width: 160px; }
	.tags { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
	.tag { background: var(--surface-3); padding: 4px 9px; font-size: 12px; border-radius: 999px; min-height: 0; }
	.tag-input { flex: 1; min-width: 100px; }

	.session-id { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
	.session-id .name { font-size: 14px; color: var(--text); }
	.session-id .id { font-size: 11px; color: var(--faint); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

	.controls { display: flex; align-items: center; gap: 10px; flex: none; margin-left: auto; }
	.controls .rec { background: var(--rec); color: #2A0A0E; border-color: var(--rec); font-weight: 600; }
	.controls .rec:disabled { background: var(--surface-2); color: var(--text); border-color: var(--line); }
	.hint { color: var(--faint); font-size: 12px; }
</style>
