<script lang="ts">
	import { recorder } from '$lib/app/session.svelte';

	let { nodeId }: { nodeId: string } = $props();
	let value = $state('');
	let prev = '';
	let wordStartNs: number | null = null;
	let fullTimer: ReturnType<typeof setTimeout> | undefined;
	const active = $derived(recorder.sessionState === 'recording');

	// reset the editor at the start of each recording (matches the old panel)
	let wasActive = false;
	$effect(() => {
		if (active && !wasActive) { value = ''; prev = ''; wordStartNs = null; }
		wasActive = active;
	});

	function nowNs() { return Math.round(performance.now() * 1e6); }

	// Capture each word with its ONSET time (first keystroke of the word — what EEG↔text
	// alignment needs), emitted the moment the word is completed by whitespace.
	function onInput(e: Event) {
		const val = (e.target as HTMLTextAreaElement).value;
		const now = nowNs();
		if (val.length > prev.length) {
			const ch = val[val.length - 1];
			const prevCh = prev[prev.length - 1] ?? ' ';
			if (!/\s/.test(ch) && /\s/.test(prevCh)) wordStartNs = now;           // new word started
			if (/\s/.test(ch) && prev && !/\s/.test(prevCh)) {                    // word just completed
				const words = prev.trim().split(/\s+/);
				const w = words[words.length - 1];
				if (w) recorder.ingest(nodeId, [{ kind: 'word', word: w, t_browser_ns: wordStartNs ?? now }]);
			}
		}
		prev = val;
		value = val;
		scheduleFull();   // keep the full-text dump current as the user types
	}

	// debounced full-text snapshot to the text_full stream — the analog of text_final.txt,
	// kept live so even a trailing partial word is captured before Stop.
	function scheduleFull() {
		clearTimeout(fullTimer);
		fullTimer = setTimeout(() => {
			if (active && value) recorder.ingest(nodeId, [{ kind: 'final', text: value, t_browser_ns: nowNs() }]);
		}, 300);
	}

	const wordCount = $derived(value.trim() ? value.trim().split(/\s+/).length : 0);
</script>

<textarea
	value={value}
	oninput={onInput}
	placeholder={active ? 'type — each completed word is timestamped at its onset…' : 'recording not started'}
	disabled={!active}
	data-testid={`text-input-${nodeId}`}
></textarea>
<span class="rd mono">{wordCount} words{value ? ' · full text captured' : ''}</span>

<style>
	textarea { width: 100%; min-height: 160px; resize: vertical; background: var(--ink); color: var(--text);
		border: 1px solid var(--line); border-radius: var(--r); padding: 10px; font-family: var(--sans); font-size: 14px; }
	textarea:focus { border-color: var(--signal); outline: none; }
	.rd { font-size: 11px; color: var(--muted); }
</style>
