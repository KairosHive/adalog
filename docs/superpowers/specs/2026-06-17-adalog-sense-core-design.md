# adalog-sense — Core Recorder Design Spec

- **Status:** Draft for review
- **Date:** 2026-06-17
- **Scope:** Spec 1 of 3 for the adalog rework. This spec covers the **standalone core recorder**: the recording spine, the device-adapter SDK, the 8 launch device adapters, the standalone web UI, and the legacy-data converter. Two follow-on specs are explicitly deferred: **Spec 2 — Google Drive sync & collective dataset platform**, and **Spec 3 — goofi-pipe co-hosting (Mode B)**.
- **Supersedes:** the entire current `adalog` codebase (full ground-up rework; the old code is a reference, not a base).

> **One sentence.** adalog-sense is a small, lint-enforced, **goofi-free recording spine** (one master clock + a lossless, crash-safe sink + a manifest contract) wrapped in a **declarative device-adapter SDK** whose adapters never touch the clock or disk, served standalone by a tiny web backend that reuses goofi-next's Svelte panel shell and leaf viewers — producing self-describing, ML-ready multimodal session directories.

This design is the output of a deep exploration of the existing `adalog` and `goofi-next/goofi-pipe` repos, followed by an adversarial generate→critique→merge of five competing architectures. It grafts the strongest idea from each proposal and fixes seven fatal flaws the critics surfaced (see **§18, Appendix A**). All facts about the existing code and data were verified against the live trees and the real `adalog-sessions/phil/*` data.

---

## 1. Goals & non-goals

### 1.1 Goals
1. **Plug-and-play standalone recorder.** `uvx adalog-sense` (or equivalent) boots a local web app; a technical user is recording the current device set within seconds, with zero config and zero network.
2. **Synchronized multimodal capture.** All modalities share one master session clock so EEG↔text↔audio↔drawing align *by construction*, not by post-hoc nearest-match.
3. **Lossless, crash-safe recording.** No silent frame drops; no OOM; a `kill -9` mid-session leaves a fully readable, aligned session.
4. **A purpose-built, self-describing data standard.** A session directory + `manifest.json` where every stream is stored in its natural format and declares its own timing/provenance. The manifest is the single contract consumed by the inspector, the converter, the future sync layer, and downstream ML.
5. **A device-adapter SDK that makes adding devices trivial and safe.** Extendable templates (LSL, Serial, Audio, REST, WebSocket, UI-source) plus a from-scratch base; declarative output + config; per-adapter error isolation; out-of-tree third-party adapters via entry-points.
6. **Reuse goofi-next's UI shell, not fork it.** Reuse the extracted pure workspace shell + GOOF decode + leaf viewers; adalog *authors all of its own panels*.
7. **Migrate existing data.** A converter turns the current `adalog-sessions` trees into the new format, honestly representing every measured pathology.
8. **A foundation for engine & play.** The manifest + clock + envelope are the lingua franca the later apps build on; this spec defines their attachment points without building them (**§14**).

### 1.2 Non-goals (this spec)
- **Google Drive / cross-user sync / collective discovery** → Spec 2. (Spec 1 ships a `BlobStore`/`Index` *interface* with a local-filesystem implementation only.)
- **Running inside goofi-pipe as nodes/panels (Mode B), the GoofiStream adapter, EmbeddedGoofi** → Spec 3. (Spec 1's SDK is designed so Mode B drops in without rework.)
- **adalog-engine and adalog-play** (offline analysis, online models, biofeedback) → future. Only their attachment points are specified here (**§14**).
- **A privacy/consent model for publishing personal data** → required before any collective feature ships (Spec 2).

---

## 2. Invariants (mechanically enforced)

These eight invariants govern every decision and are enforced by lint rules, CI import-guards, a manifest validator, and a cross-host conformance suite — not by discipline.

1. **One monotonic master clock per session.** Session time derives only from a monotonic source. Wall-clock UTC enters as periodically re-sampled `(mono_ns, utc_ns)` *anchor pairs*, never per-sample. Any use of `datetime.now()`/`utcnow()`/`time.time()` outside the clock module is a lint error. Where `CLOCK_BOOTTIME` is available the monotonic source includes suspend time, so a suspend appears as a *real elapsed gap in the data*, not as a clock jump event (see **§5.1** and should-fix (h)).
2. **Adapters produce; the Core stamps and writes.** An adapter hands the Core a payload plus *the best native timestamp it has*. The Core is the sole writer and the sole mapper of device→session time. Adapters never open files and never read the wall clock.
3. **Lossless, or a counted, manifest-recorded drop — never silent, never OOM.** Bounded per-stream buffers with an explicit, declared back-pressure regime. No latest-wins on the recording path. "Lossless" precisely means *lossless until a bounded buffer overflows, after which losses are COUNTED and recorded in the manifest `drops`* — for **all** transport classes (**§5.4**).
4. **Crash-safe by append + journal.** Append-only data files + per-stream journal + incrementally-written manifest + format-aware recovery.
5. **The manifest is THE contract.** Downstream never re-derives timing from filenames or column order. Timing-provenance is a first-class, honest, per-stream field.
6. **The goofi-free import boundary is enforced in CI.** `adalog.core`, `adalog.schema`, `adalog.adapters` import nothing from `goofi`, `torch`, or `iceoryx2`. An import-linter contract fails the build otherwise. goofi is an opt-in extra (Spec 3).
7. **Recording plane ⊥ monitor plane.** Live viewers may drop frames (latest-wins, cheap). The recording path never drops. Both fan out from one envelope source *after* the Core's ingest.
8. **Record-100%-locally-first.** A valid, complete session directory is produced with zero network and zero auth. Sync (Spec 2) is a separate, resumable, never-blocking background concern.

---

## 3. Repository & package structure

adalog remains its **own repository** (`KairosHive/adalog`). It depends on goofi-next only as published/packaged dependencies — never as a monorepo or vendored fork. Internally it is a single Python distribution `adalog` with **layered subpackages**, plus a SvelteKit frontend.

```
adalog/                                   # the existing repo
├── pyproject.toml                        # one distribution `adalog`; extras: [goofi] (Spec 3), [dev]
├── importlinter.ini                      # CI-enforced layered/forbidden contracts (invariant #6)
├── src/adalog/
│   ├── core/                             # ★ goofi-FREE recording spine
│   │   ├── clock.py                      # SessionClock (monotonic-first, BOOTTIME) + anchors
│   │   ├── device_clock.py               # DeviceClock mappers (LSL / PortAudio / browser / nominal)
│   │   ├── envelope.py                   # StreamPacket (chunk-grained) + timing provenance
│   │   ├── session.py                    # Session FSM (arm/start/pause/resume/stop/recover) + segments
│   │   ├── manifest.py                   # pydantic models, versioned schema, validate(), reconcile()
│   │   ├── config_store.py               # ★ persisted config (§8): device/session/app scopes + keyring
│   │   ├── status.py                     # ★ typed status/telemetry payloads (§11.5)
│   │   ├── recorder/
│   │   │   ├── core.py                   # RecordingCore: per-stream ring + writer threads + fan-out
│   │   │   ├── ringbuffer.py             # bounded ring + lock-free handoff + spill-to-disk WAL + back-pressure
│   │   │   ├── journal.py                # per-stream journal.ndjson + crash recovery + format repair
│   │   │   └── writers/                  # StreamWriter registry keyed by encoding
│   │   │       ├── base.py arrow_ipc.py wav.py csv_ts.py jsonl.py png.py pentrace.py midi.py
│   │   ├── ids.py                        # ULID session ids (salted), blake3 hashing
│   │   └── reader.py                     # inverse of writers: manifest -> aligned Stream objects
│   ├── schema/                           # ★ goofi-FREE Field/Param system (mirrors goofi Param)
│   │   └── fields.py                     # Str/Int/Float/Bool/Enum/Secret + JSONSchema export
│   ├── adapters/                         # ★ device-adapter SDK (templates goofi-FREE)
│   │   ├── base.py                       # DeviceAdapter ABC + StreamSpec + AdapterContext + AdapterInfo + status types
│   │   ├── supervisor.py                 # AdapterSupervisor: isolation, restart, stall watchdog
│   │   ├── registry.py                   # builtin list + entry-points discovery (group "adalog.adapters")
│   │   └── templates/                    # lsl.py serial.py audio.py rest_poll.py websocket.py ui_source.py
│   ├── store/                            # ★ BlobStore/Index INTERFACE + local backend only (Drive=Spec 2)
│   │   ├── base.py                       # BlobStore, Index protocols
│   │   └── local.py                      # filesystem-backed implementation
│   ├── sense/                            # the recorder application
│   │   ├── cli.py app.py service.py      # RecorderService = the shared brain
│   │   ├── bridge/                       # standalone sense-bridge (impersonates goofi wire protocol)
│   │   │   ├── server.py control.py data.py status.py shim.py ops.py   # op-registry + data/status planes
│   │   └── devices/                      # the 8 launch adapters
│   │       └── eeg_muse.py ecg_serial.py audio_mic.py drawing.py text.py midi.py osc.py meteo.py
│   ├── convert/                          # legacy v0 -> v1 converter
│   └── bridge_codec/                     # server-side GOOF encode (pure numpy+msgpack+struct) + envelope
├── frontend/                             # SvelteKit SPA (Svelte 5). Built bundle shipped inside the wheel.
│   ├── package.json                      # deps: @goofi/workspace-shell, @goofi/bridge-client (external)
│   └── src/lib/{panels,viewers-adapters,control,stores}/ + routes/
├── docs/superpowers/specs/
└── tests/                                # unit + conformance + fault-injection + fixture + e2e regression
```

### 3.1 Import-guard contracts (invariant #6)
`importlinter.ini` declares:
- **Forbidden:** `adalog.core`, `adalog.schema`, `adalog.adapters`, `adalog.store`, `adalog.convert`, `adalog.bridge_codec` may not import `goofi*`, `torch`, `iceoryx2`.
- **Layered:** `adalog.core` ← `adalog.adapters` ← `adalog.sense` (lower layers must not import higher). `adalog.schema` and `adalog.bridge_codec` are leaf layers imported by many but importing none of the others.
- The `[goofi]` extra (Spec 3) will add `adalog.goofi_client` and `adalog.sense.goofi_mode`, the *only* modules permitted to import `goofi`.

### 3.2 Cross-repo dependency on goofi-next (prerequisite)
The frontend depends on two TypeScript packages **extracted from goofi-pipe and published from there** (adalog consumes, does not own):
- `@goofi/workspace-shell` — the pure panel-tree shell (verified to import only `svelte`, `svelte/action`, `vitest`, and relatives). Extraction is the *entire* `frontend/src/lib/workspace/` directory (all files, including `workspace.svelte.ts`, `panelState.ts`, `panels.ts`, `menu.ts`, `PanelHeader.svelte`, `EmptyPanel.svelte`) with one behavioral change: layout persistence injected via a `LayoutPersistence` adapter (adalog → localStorage / `/api/layout`).
- `@goofi/bridge-client` — the GOOF `decode.ts` + leaf viewer components (uPlot `ArrayViewer`, topomap, pen-trace canvas, etc.) + WS client patterns, with an **injected** `subscribe(node, slot, cb)` and parametrized base URL (no goofi singleton import).

These are consumed as versioned dependencies (git URL or registry). A CI codec-version contract test asserts the GOOF header `version == 2` to prevent vendoring/protocol drift. If goofi-pipe cannot publish these in time, adalog vendors a pinned snapshot behind the same package names — the dependency direction never reverses.

> **One wire format, two ends (should-fix g).** `bridge_codec/` (Python, server-side **encode**, pure `numpy`/`msgpack`/`struct`, goofi-free) and `@goofi/bridge-client` (TS, browser-side **decode**) are the two ends of **one** wire format, version-locked by the GOOF `version == 2` CI contract test. Neither end imports goofi at runtime.

---

## 4. The data standard

### 4.1 Session directory
```
sessions/<user>/<session_id>/            # session_id = salted ULID (time-sortable, cross-host unique)
├── manifest.json                         # THE contract — small, fully describes the session
├── manifest.lock                         # present while status=recording (crash detection)
├── events.ndjson                         # tags / pause-resume / markers / clock / error events, session-clock t
└── streams/
    ├── eeg/eeg.arrow      eeg/eeg.timing.ndjson
    ├── ecg/ecg.arrow      ecg/ecg.timing.ndjson      ecg/hrv.ndjson
    ├── audio/audio.wav
    ├── drawing/snapshot.png  drawing/pentrace.ndjson
    ├── text/text.ndjson
    ├── midi/perf.mid      midi/perf.ndjson
    ├── osc/osc.ndjson
    └── meteo/meteo.ndjson
```

### 4.2 `manifest.json` — field by field
```jsonc
{
  "manifest_version": "1.0",
  "session_id": "01J8ZQK3...A1B2",         // ULID: time-sortable prefix + host/user-salted random tail
  "status": "complete",                     // recording | complete | recovered | aborted
  "label": "intuitive writing #3",
  "subject":   { "id": "subj_phil", "attributes": {"handedness":"R"} },   // pseudonymous cross-individual key
  "provenance":{ "user_id":"u_local", "app":"adalog-sense", "app_version":"1.0.0",
                 "host":"tuxedo", "os":"linux-6.17", "created_with":"standalone" },
  "clock": {
    "source": "monotonic_ns",
    "t0_anchor": { "mono_ns": 81234567890, "utc_ns": 1750170600123000000 },
    "reanchors": [ {"t":10.0,"mono_ns":91234567890,"utc_ns":1750170610123010000} ],   // ~every 10s
    "host_drift_ppm": 2.1,
    "boottime_used": true,                  // CLOCK_BOOTTIME: suspend counts as elapsed time (no jump event)
    "wall_uncertainty_s": 0.05,             // best-effort NTP-grade bound (cross-host alignment confidence)
    "tz": "Europe/Berlin"
  },
  "duration_s": 612.84,
  "pauses": [ {"from_t":120.0,"to_t":135.2} ],
  "tags": ["eeg","writing","intuitive","german"],
  "collection_refs": [],                    // populated by Spec 2
  "events_file": "events.ndjson",
  "streams": [ /* see 4.3 */ ]
}
```

> **Spec-1 boundary note (should-fix d).** `subject`, `clock.host_drift_ppm`, `clock.wall_uncertainty_s`, and `collection_refs` are **recorded best-effort in Spec 1** but are **not consumed** here. Cross-host alignment, drift correlation across hosts, and collections are Spec 2 concerns. Spec 1 only needs them written honestly; it does not act on them.

### 4.3 Per-stream entry & the four timing modes
Every stream **file/role** declares exactly one timing mode. Timing lives **per file/role** (so a multi-file stream like drawing can mix modes). The mode `anchored_irregular` is the fix for real rate-bearing-but-drifty hardware; the mode `event` covers artifacts with no rate at all (a PNG snapshot, an OSC `_store` write).

```jsonc
{
  "id": "eeg", "modality": "eeg",
  "adapter": { "id":"eeg_muse", "version":"1.2.0", "template":"lsl" },
  "device":  { "name":"Muse-1234", "model":"Muse 2" },
  "schema":  { "channels":["TP9","AF7","AF8","TP10"], "units":"uV", "dtype":"float32" },
  "derivation": null,                        // non-null only for derived streams; see "Derived streams" below
  "files": [
    { "role":"data", "path":"streams/eeg/eeg.arrow", "encoding":"arrow_ipc_stream",
      "blake3":"b3:...", "bytes":2457600,
      "timing": {
        // --- AUTHOR-DECLARED (carried from StreamSpec.timing_mode + declarative params) ---
        "mode": "anchored_irregular",        // AUTHOR-DECLARED: per_sample | anchored | anchored_irregular | event
        "sfreq_nominal": 256.0,              // AUTHOR-DECLARED
        // --- CORE-RECONSTRUCTED (composed by RecordingCore at finalize) ---
        "sfreq_effective": 246.31,           // CORE-RECONSTRUCTED: MEASURED from device timestamps
        "t_start": 0.281,                    // CORE-RECONSTRUCTED: session seconds of sample index 0
        "n_samples": 161353,                 // CORE-RECONSTRUCTED
        "index_to_t": "sidecar",             // CORE-RECONSTRUCTED: exact map reconstructable from the timing sidecar
        "gaps": [ {"index":40960,"t":160.41,"duration_s":2.43,"reason":"lsl_dropout"} ],  // CORE-RECONSTRUCTED
        "clock_provenance": "device_lsl",    // CORE-RECONSTRUCTED: device_lsl|device_portaudio|host_arrival|browser|nominal|reconstructed
        "confidence": "measured",            // CORE-RECONSTRUCTED: exact|measured|approximate|nominal (see below)
        "wall_uncertainty_s": 0.05,          // CORE-RECONSTRUCTED: per-file UTC bound (defaults to clock-level)
        "drops": []                          // CORE-RECONSTRUCTED: counted drops with seq/t ranges (never silent)
      } },
    { "role":"timing", "path":"streams/eeg/eeg.timing.ndjson", "encoding":"jsonl" }
  ],
  "segments": 1,                             // >1 after reconfigure / restart-with-continuity
  "status": "complete"                       // complete | degraded(+reason) | failed(+reason)
}
```

**Author-declared vs Core-reconstructed.** The adapter author declares only `mode` (the `StreamSpec.timing_mode`, see **§6.6**) plus declarative params such as `sfreq_nominal`. *Everything else in the `timing` object is composed by the RecordingCore at finalize* from the StreamPacket flow and the timing sidecar. Adapters never write `sfreq_effective`, `t_start`, `gaps`, `index_to_t`, `clock_provenance`, `confidence`, or `drops`.

**The four timing modes (normative enum `{per_sample, anchored, anchored_irregular, event}`):**
- **`per_sample`** — each row carries its own session-time `t` (text, OSC, MIDI mirror, meteo, drawing pen-trace).
- **`anchored`** — `t(i) = t_start + i / sfreq_effective` where the host **owns and measures** the clock (audio DAC). Always carries `sfreq_effective`, never just nominal. (should-fix (c): the formula uses `sfreq_effective`, not nominal.)
- **`anchored_irregular`** — rate-bearing but drift-prone hardware (LSL EEG/ECG). Data is written contiguously (gap-free index space) **plus** a per-sample device-timestamp sidecar, from which `sfreq_effective`, the exact `index_to_t` map, and `gaps` are *reconstructed*, never asserted. This makes `round((t − t_start) * sfreq_effective)` epoching exact instead of drifting tens of samples over a session. See **§5.4a** for the sidecar contract that makes this exact without assuming uniform intra-chunk spacing.
- **`event`** — artifacts with no intrinsic rate. Each occurrence carries its own session-time `t`; the file declares `timing:{mode:"event","events":[{"t":...}]}`. Used by Drawing `snapshot.png` and the OSC `_store/<name>` side-channel.

**The `index_to_t` field (should-fix e).** The exact-name field is `index_to_t` (value `"sidecar"` when reconstructed from the timing sidecar, or `"uniform"` for pure `anchored`). In prose we may speak of "the index→t map"; the *field name* is always written `index_to_t`.

**`confidence` (must-fix 3).** `confidence ∈ {exact, measured, approximate, nominal}` is a single coherent uncertainty summary for a file's timing, derived from `clock_provenance` and `wall_uncertainty_s`:
- `exact` — every sample's `t` is carried explicitly and is authoritative (`per_sample` with a trusted device/browser clock; `clock_provenance ∈ {device_lsl, device_portaudio, browser-with-good-handshake}` and `wall_uncertainty_s` small).
- `measured` — `t` derived from a *measured* device clock (`anchored`/`anchored_irregular` with `clock_provenance ∈ {device_portaudio, device_lsl}` and a healthy drift fit). The within-session spacing is trustworthy; cross-host UTC is bounded by `wall_uncertainty_s`.
- `approximate` — `t` reconstructed from heuristics (e.g. the converter rebuilding `sfreq_effective` from drifty stamps, `clock_provenance:"reconstructed"`).
- `nominal` — only the declared nominal rate is trustworthy; the effective rate could not be measured (`clock_provenance:"nominal"` or `"host_arrival"`).

Relationship rule: `confidence` is a *function of* `clock_provenance` (how the time was obtained) and `wall_uncertainty_s` (how well UTC is pinned). They are one uncertainty story: `clock_provenance` is the mechanism, `wall_uncertainty_s` the cross-host bound, and `confidence` the human-readable rollup the inspector and ML consumers read first.

**Derived streams (should-fix f).** A stream computed from another (e.g. `hrv` from `ecg`) declares a `derivation` block instead of relying on an undefined `window` field:
```jsonc
"derivation": {
  "source_stream": "ecg",          // id of the source stream in this session
  "method": "rr_interval",         // analytic identifier
  "window": { "kind":"event", "basis":"R-R" }   // window semantics: event-driven R-to-R, sliding{seconds}, etc.
}
```
`derivation` is a schema/provenance field: it records *what the stream is derived from and with what window semantics*, so the inspector and downstream ML never guess. Derived analytics that are *recorded* are first-class streams; live-only derived analytics are monitors (**§12**).

### 4.4 Hashing & dedupe honesty
Per-file `blake3` serves (a) integrity, (b) the pull-plan for Spec 2, (c) dedupe. Hashes are computed over the **canonical file at finalize**, after the manifest is reconciled against journals (never over fsync-lagged or truncated tails). For `kill -9`-recovered sessions, **hashes are computed AFTER recovery truncation, over the salvaged canonical file**, and a `status:"recovered"` manifest carries those salvaged-file hashes (should-fix j). Dedupe is claimed only for **byte-identical** files (idempotent re-push, copied shared stimuli) — never for "same hardware, different t0".

---

## 5. The recording spine (`adalog.core`, goofi-free)

### 5.1 SessionClock
Captures `(t0_mono_ns, t0_utc_ns)` once; re-samples anchor pairs ~every 10s into the manifest. Session time = `(monotonic_ns() − t0_mono_ns) / 1e9` — monotonic, unaffected by NTP steps. UTC is reconstructed from the nearest anchor pair (drift-fit) on read, never stored per sample. `wall_uncertainty_s` records a best-effort bound for cross-host alignment confidence (used by Spec 2).

**Suspend handling, per-OS (should-fix h; invariant #1).**
- On Linux/Android we use `time.clock_gettime(time.CLOCK_BOOTTIME)`: suspend time **silently elapses** as real time. A laptop suspend therefore shows up as a *genuine gap in the data* (no samples arrived) with **no synthetic clock-jump event** — the gap is real, not an artifact. `boottime_used:true`.
- On macOS, `CLOCK_BOOTTIME` is unavailable; we use `mach_absolute_time` / `CLOCK_UPTIME_RAW`, which **stops during sleep**. On Windows, `QueryPerformanceCounter` likewise does not advance through sleep on most systems. In these fallback cases `boottime_used:false`: a suspend manifests as a near-zero monotonic delta across a large wall-clock delta, which we **detect at the next re-anchor and record as an explicit clock event** (a suspend marker in `events.ndjson`), and the affected interval is marked as a gap with `reason:"suspend"`.
- `boottime_used:false` means cross-host UTC confidence is weaker across any suspend: `wall_uncertainty_s` for spans crossing a detected suspend is widened, and `confidence` for those spans cannot exceed `measured`.

### 5.2 DeviceClock domain mappers
A first-class SDK concept (the layer all five proposals omitted): each adapter supplies its **native** timestamps, and a per-stream `DeviceClock` maps them into the session monotonic domain via a continuously-updated robust offset+skew fit (median-of-offsets, drift-resistant):
- **LSL** — `pull_chunk(timestamp=True)` (returns **per-sample** timestamps) + `inlet.time_correction()` refreshed periodically (not once at open). *(goofi's `lslclient.py` discards LSL timestamps — verified; adalog's LSL template re-enables them.)*
- **PortAudio** — `time.inputBufferAdcTime` captured in the callback so audio `t_start` is the true ADC instant, not callback wakeup. *(goofi's `audiostream.py` discards it — verified.)*
- **browser** (Drawing/Text) — an NTP-style offset handshake (`browser performance.now() ↔ server monotonic`) measured on connect and refreshed; word-onset/pen `t` is reconciled to the master clock, not stamped at WS arrival. Target onset uncertainty **< 50 ms**. The handshake op and cadence are normative in **§11.4**.
- **nominal/reconstructed** — explicitly labeled in `clock_provenance` so downstream knows the confidence.

`DeviceClock` receives native timestamps two ways (must-fix 14): **pull** templates hand them per-pull (LSL `pull_chunk`), **push/callback** templates hand them in the realtime callback (PortAudio ADC time, MIDI message time); either way they ride on the `StreamPacket` (see **§5.3**) and the mapper updates its offset/skew fit incrementally.

### 5.3 The stream envelope
```python
@dataclass(slots=True)
class StreamPacket:
    stream_id: str
    seq: int                      # per-stream monotonic packet counter (gap DETECTION)
    payload: Any                  # ndarray(chunk) | dict | str | bytes | PIL.Image | mido.Message
    n_samples: int                # >1 for chunked arrays, 1 for events
    device_ts_ns: int | None      # native device time of the chunk's FIRST sample (mapped via DeviceClock)
    recv_mono_ns: int             # SessionClock monotonic at Core ingest (drift/jitter audit)
    per_sample_ts: list[int] | None   # REQUIRED for anchored_irregular and per_sample with explicit times
```
This is the time/seq/provenance layer the GOOF codec lacks (verified: GOOF header carries none). Chunk grain + `n_samples` + `device_ts_ns` (first sample) removes the "is `t` the first or last sample?" ambiguity.

**`anchored_irregular` requires per-sample device timestamps (must-fix 5).** `device_ts_ns` alone (the chunk's first sample) would force *uniform intra-chunk spacing* on reconstruction — the exact interpolation lie this spec exists to kill. Therefore for `anchored_irregular` (and for `per_sample` arrays) the packet **must** carry per-sample device times in one of two equivalent forms:
- `per_sample_ts: [t0, t1, ..., t_{k-1}]` — one native timestamp per sample in the chunk (this is what pylsl `pull_chunk(timestamp=True)` returns); or
- the compact `(first_ts, count, raw_ts[])` form — `device_ts_ns = first_ts`, `n_samples = count`, and `per_sample_ts = raw_ts[]` carrying the *raw, unmodified* per-sample device timestamps.

An adapter emitting `anchored_irregular` with `per_sample_ts is None` is a contract violation caught by the conformance suite (**§15**).

### 5.4 Lossless pipeline & back-pressure
Each stream gets a **bounded ring buffer** drained by a dedicated writer thread (GIL released during I/O). The back-pressure regime is **declared per stream and pre-chosen by the template's transport class**, removing the most dangerous decision from device authors. **Across all three classes, "lossless" means lossless until a bounded buffer overflows, after which losses are COUNTED and recorded in manifest `drops`** — never silent, never unbounded OOM.

- **callback/realtime sources** (audio, MIDI, OSC) → **`SPILL`**:
  - The realtime callback writes **only** into a **lock-free, BOUNDED handoff buffer** (a single-producer/single-consumer ring). It **never** fsyncs, never blocks, never allocates unboundedly, and never opens a file from the callback thread.
  - A dedicated **writer thread drains** the handoff buffer into the WAL / canonical file with its own fsync cadence (**§5.5**, should-fix i).
  - **The bound is the handoff buffer**, sized so that `handoff_capacity ≥ max_expected_callback_burst × writer_drain_margin`. Default policy: size the handoff buffer to hold **≥ 2 seconds** of the stream's nominal data rate (configurable per template); a SPILL stream additionally has a disk **WAL ring file** the writer uses when the canonical sink temporarily can't keep up.
  - **On sustained overrun** (handoff buffer full when the callback tries to push), the callback increments an atomic **counted-drop counter** and records the dropped sample range; at finalize this becomes a `drops` entry `{from_seq,to_seq,from_t,to_t,count,reason:"handoff_overflow"}`. **Drop detection** is by handoff-push-failure count cross-checked against `seq`/`n_samples` arithmetic.
- **pull-loop hardware** (LSL, serial) → **`BACKPRESSURE`**: the pull loop slows; if the device's own buffer (liblsl `max_buflen`, serial OS buffer) is about to overflow, that is detected by sequence/sample-count arithmetic and recorded as a **counted gap**, never assumed contiguous. If the bounded ring still overflows under sustained writer stall, the overflow is counted into `drops` exactly as for SPILL.
- **poll APIs** (meteo) → **`BLOCK`** is safe (low rate). Even here, a bounded ring guards against a hung writer; overflow counts into `drops`.

Truthful guarantee: lossless until disk genuinely can't keep up, at which point SPILL streams spill to a bounded WAL and *then* count-and-record drops with a reason; pull/poll streams count-and-record drops directly — never silently, never unbounded OOM. A **watchdog** converts a persistent writer stall (full disk, fsync hang) into a surfaced `WriterLag` error (**§11.5**) and a controlled stream-degrade, not a frozen session. A pre-flight free-disk check runs at arm time.

### 5.4a Timing sidecar contract for `anchored_irregular` (must-fix 5)
The canonical `.arrow` file holds samples in a **contiguous, gap-free index space**. The exact `index_to_t` map is reconstructed entirely from the **timing sidecar** (`*.timing.ndjson`), which the writer appends **per record batch**:
```jsonc
// one sidecar record per Arrow record batch (record batch = the writer's flush unit)
{ "batch": 412,            // record-batch ordinal
  "first_index": 105472,   // sample index of this batch's first row in the contiguous index space
  "count": 256,            // number of samples in this batch
  "device_ts_ns": [ ... ], // EXACTLY `count` raw per-sample device timestamps (mapped to session monotonic)
  "seq": 412 }             // StreamPacket.seq for gap detection
```
`reader.py` builds `index_to_t` by concatenating the sidecar's per-batch `device_ts_ns` arrays in index order — **no uniform intra-chunk spacing is ever assumed**. `sfreq_effective` is a robust regression over the full `(index, t)` set; `gaps` are intervals where consecutive device timestamps exceed a drift-aware threshold (see **§13**, gap-threshold definition). If a sidecar batch is lost to a crash but its data batch is durable (or vice-versa), `recover()` reconciles both to the common flush point (**§5.5**).

**Round-trip exactness test (normative).** For a synthetic `anchored_irregular` stream with known per-sample LSL timestamps `t_orig`, after write → `recover()`(no-op) → `reader.py`, the reconstructed `index_to_t` must satisfy `max_i |t_recon[i] − t_orig[i]| ≤ ε` with `ε = 1 µs` (timestamp storage rounding), i.e. exactly the original LSL timestamps within rounding tolerance. This is run on both the all-complete path and the post-`kill -9` salvaged path.

### 5.5 Crash safety (format-aware)
- `start()`: the **session directory already exists** (created by `session_create`, **§7**); `start()` writes `manifest.lock` + draft `manifest.json` (status `recording`), creates `streams/` and per-stream subdirs, opens journals, and **for every Arrow stream writes and fsyncs the schema (head) message before the first record batch** — an Arrow IPC stream is unreadable without its leading schema message, so this fsync is mandatory and ordered before any data batch.
- Each writer: **write data → fsync → append journal record → fsync** (strict ordering, so the journal never claims bytes that aren't durable).
- **fsync / flush cadence policy (should-fix i).** The default is **fsync every record batch OR every 250 ms, whichever first** (configurable per stream via the config store, **§8**). The explicit durability bound is: **on a power-cut, at most one flush interval of data is lost** — i.e. **≤ 250 ms** by default (or ≤ one record batch). `recover()` tests target exactly this bound.
- Arrays use the **Arrow IPC stream format** explicitly (a sequence of length-prefixed encapsulated messages: schema, then dictionary/record-batch messages) — **not** footer-finalized Parquet (a footerless Parquet is unreadable) and **not** Parquet "row-groups" (those are a Parquet concept and do not exist in Arrow IPC; we say **record batch / encapsulated message** throughout). A crash loses at most the last incomplete record batch; the stream is readable as a forward scan with no footer.
- `recover()`: replay journals; **format-aware repair**:
  - **Arrow IPC stream torn-tail recovery (precise):** scan forward from the schema message over framed encapsulated messages. Each message is `[0xFFFFFFFF continuation marker][int32 little-endian metadata length][metadata (flatbuffer)][body]`, **8-byte aligned**. Accept up to and including the **last COMPLETE message that is fully present and correctly aligned**; truncate everything after it. If the schema (head) message itself is incomplete, the file is unrecoverable and marked `failed` (this is why **§5.5** fsyncs the schema in `start()`).
  - WAV: rewrite the RIFF header from the recovered frame count.
  - NDJSON: truncate to the last complete newline-terminated line.
  - reconcile data ↔ timing sidecar to the common flush point; recompute `n_samples`/`blake3` over the salvaged file (should-fix j); write `status:"recovered"`.
  - **Automatic on next launch** when a `manifest.lock` is found (no hidden flag).
- `manifest.reconcile()` asserts `produced-seq == persisted-rows == declared n_samples` per stream; a mismatch is recorded (as `drops`/`gaps`), not hidden.

### 5.6 Reader
`reader.py` is the exact inverse of the writers: given a manifest it returns aligned `Stream` objects (arrays with an exact `index_to_t` map from the timing sidecar; per-sample frames with their `t`). It is the single API engine/play/converter-tests consume; downstream never parses raw files directly.

---

## 6. The device-adapter SDK (`adalog.adapters`)

### 6.1 The base ABC and `AdapterContext`
```python
class DeviceAdapter(ABC):
    info: AdapterInfo                          # id (stable string, NO filename magic), title, category, multi, requires

    # ---- discovery (cheap, fast; lazy-imports heavy libs INSIDE; returns [] never raises) ----
    @staticmethod
    def discover() -> list[DiscoveredSource]: ...

    # ---- declarative config (mirrors goofi Param; auto-generates UI in the host) ----
    @staticmethod
    def config_schema() -> ConfigSchema: ...                # adalog.schema Fields, GROUPED by section

    # ---- output contract: static declared + runtime-resolved (the escape hatch) ----
    def declare_streams(self) -> list[StreamSpec]: ...       # statically knowable pre-connect
    def resolve_streams(self) -> list[StreamSpec]: ...       # AFTER open(): true channels/sfreq filled in
    # dynamic adapters (OSC) declare a stream TEMPLATE and call ctx.register_stream(spec) at runtime

    # ---- lifecycle (run inside the supervised worker; thread by default, opt-in process) ----
    def open(self, ctx: AdapterContext) -> None: ...         # acquire device; lazy-import HERE
    def start(self) -> None: ...                             # produce via ctx.emit(...)
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...                             # idempotent teardown (always called)

    # ---- health / monitoring (drives UI; distinguishes failure modes) ----
    def status(self) -> AdapterStatus: ...

    # ---- hot-reconfigure (mirrors goofi {group}_{param}_changed) ----
    def reconfigure(self, group: str, name: str, value) -> ReconfigResult: ...
```

**Config access — ONE way (must-fix 4).** `config_schema()` returns Fields **grouped** by section (`{ "<group>": { "<field>": Field, ... }, ... }`). Before `open()` is called, the **template** populates a typed config object on the adapter: `ctx.config` (the raw resolved dict) is mapped to attribute access `self.cfg.<group>.<field>`. **Adapters read config exclusively via `self.cfg.<group>.<field>`.** `ctx.config` is the raw form available to templates that build `self.cfg`; adapter authors do not read `ctx.config` directly. (This resolves the prior `ctx.config` vs `self.cfg.lsl.source` inconsistency; the worked example in **§6.7** uses `self.cfg.lsl.source`.)

The grouped-`ConfigSchema` → `self.cfg` mapping is: `config_schema()["lsl"]["source"]` (a `StrField`) → user/persisted value → `self.cfg.lsl.source` (a plain typed attribute). `Secret` fields are resolved from the keyring at this step, never persisted in plaintext (**§8**).

**`AdapterContext` — full method set (must-fix 14):**
```python
class AdapterContext:
    config: dict                         # raw resolved config (templates build self.cfg from this)
    clock: ReadOnlyClock                 # read-only SessionClock view (now_ns / now_t); NEVER wall clock
    device_clock: DeviceClock            # the native->session mapper for this adapter's streams
    log: Logger                          # structured logger -> events.ndjson on warn/error

    def emit(self, packet: StreamPacket) -> None: ...        # hand a packet to the Core (see thread-safety)
    def register_stream(self, spec: StreamSpec) -> None: ... # runtime/dynamic stream registration (OSC)
    def report(self, status: AdapterStatus) -> None: ...     # push a status sample (optional; status() polled too)
```

**Thread-safety notes (must-fix 14).**
- `ctx.emit()` **MUST be callable from realtime callback threads** and is **lock-free** on the hot path: it pushes the packet into the stream's bounded **handoff buffer** (**§5.4**) and returns immediately; it never fsyncs, allocates unboundedly, or blocks. This is what makes a PortAudio/MIDI callback safe.
- `ctx.register_stream()` is **not** required to be callable from a realtime callback; it is called from the adapter's open/start/pull-loop context. It is internally serialized by the Core and updates the manifest live.
- `ctx.device_clock` receives native timestamps either by **pull** (timestamps handed in per `pull_chunk`) or by **push** (timestamps captured in the realtime callback and carried on the emitted packet); the mapper updates its offset/skew fit incrementally and is safe under concurrent emit.

Adapters never see disk, the manifest, or which host they run in.

### 6.2 Templates
Each template prefills transport **and** the correct timing + back-pressure regime, so a device author writes only device-specific parsing/config.

| Template | Owns | Author fills | Preset (`timing_mode`, transport) |
|---|---|---|---|
| `LSLDevice` | resolve/reconnect, `pull_chunk(timestamp=True)` (per-sample ts) + `time_correction`, multi-substream (e.g. Muse EEG/PPG/ACC ⇒ N StreamSpecs) | `default_query()`, `map_channels()` | `anchored_irregular`, BACKPRESSURE |
| `SerialDevice` | open/baud/reconnect, framing | `parse(frame) -> packets` | `per_sample`/`anchored_irregular`, BACKPRESSURE |
| `AudioDevice` | sounddevice stream, **captures ADC time**, WAV chunking, RMS monitor | usually zero code | `anchored` (measured sfreq), SPILL |
| `RestPollDevice` | poll loop, interval, backoff, ETag/last-tag dedupe, backfill | `fetch() -> packets` | `per_sample`, BLOCK |
| `WebSocketDevice` | connect, reconnect, heartbeat | `on_message() -> packets` | `per_sample`, SPILL |
| `UiSourceDevice` | **browser-fed** base: control-plane `device_ingest` RPC + browser↔server clock handshake; no hardware `open()` | `on_ingest(msg) -> packets` | `per_sample` (reconciled); `event` for snapshots |
| `DeviceAdapter` (base) | nothing | everything | author-declared |

`UiSourceDevice` is the answer to "Drawing and Text have no backend device": their device is the browser; samples arrive via a control-plane `device_ingest` RPC carrying a browser timestamp, reconciled to the master clock. Declared `info.requires="browser"` (so Mode B, Spec 3, marks them unavailable). The full `device_ingest` path is normative in **§11.4**.

### 6.3 Dynamic-schema (OSC) escape hatch
OSC declares a stream *template* (`modality:"osc", dynamic:true`) and calls `ctx.register_stream(StreamSpec(...))` when a new address appears at runtime; the RecordingCore opens a sink and the **manifest is updated live**. The OSC `_store/<name>` side-channel becomes a first-class declared **`event`-mode** file stream, not an undeclared write.

### 6.4 Registry & entry-points
```python
BUILTIN = [EegMuseAdapter, EcgSerialAdapter, AudioMicAdapter, DrawingAdapter,
           TextAdapter, MidiAdapter, OscAdapter, MeteoAdapter]
# third-party via importlib.metadata.entry_points(group="adalog.adapters"); each load() try/excepted
```
`pip install adalog-devices-foo` ⇒ a new device appears in the catalog with auto-generated config, zero edits to adalog. **Security stance (honest):** out-of-tree adapters are trusted code running with the user's privileges; `config_schema()` runs at catalog time; a subprocess is not a sandbox. We surface a clear "third-party adapter" notice and keep capability declarations purely informational — no false "trust prompt = safe" theater.

### 6.5 Error isolation, restart, hot-reconfigure, late joiners, pause
The `AdapterSupervisor` runs each adapter in its own supervised **thread** by default (process only opt-in for crash-prone native libs — avoiding the pickle tax that would endanger losslessness). An exception is caught, logged to `events.ndjson` and surfaced on the status channel (**§11.5**), the stream marked `degraded`/`failed`, and **every other stream keeps recording** (fixes "one raise aborts all"). The watchdog distinguishes `errored_transient` (reconnect with backoff), `errored_fatal` (surface, no spin-restart), and `stalled` (alive but no data — detected via expected-vs-observed rate). A restart resumes as a **new segment** (same `stream_id`, `segments++`, recorded gap). A reconfigure that changes the contract (sfreq/channels) closes the current segment and opens a new `StreamSpec` revision; cosmetic params reconfigure in place. **Late joiners** anchor `t_start` at their first packet's session time — automatically aligned because session time is global. **Pause** writes `PAUSE`/`RESUME` markers and records the pause as an explicit gap interval in anchored streams.

### 6.6 SDK contract types (closed)
The full typed contract (must-fix 14):
```python
@dataclass
class Channel:
    name: str
    units: str
    dtype: str                          # "float32" | "int16" | ...

@dataclass
class StreamSpec:
    id: str                             # stream id, becomes the manifest stream "id" and the shim slot id
    modality: str                       # "eeg" | "audio" | "text" | "osc" | ...
    channels: list[Channel]             # for array streams; [] for event/text streams
    units: str | None = None            # convenience when all channels share units
    dtype: str | None = None            # convenience default dtype
    encoding: str = "arrow_ipc_stream"  # writer registry key: arrow_ipc_stream|wav|jsonl|png|pentrace|midi|csv_ts
    timing_mode: str = "per_sample"     # AUTHOR-DECLARED enum: per_sample|anchored|anchored_irregular|event
    sfreq_nominal: float | None = None  # declarative; required for anchored/anchored_irregular
    roles: list[FileRole] | None = None # multi-file streams (e.g. drawing: snapshot.png[event] + pentrace[per_sample])
    dynamic: bool = False               # True for runtime-registered templates (OSC)

@dataclass
class FileRole:
    role: str                           # "data" | "timing" | "snapshot" | ...
    encoding: str
    timing_mode: str                    # a multi-file stream may mix modes per role

@dataclass
class DiscoveredSource:
    id: str                             # stable per-source id (e.g. LSL source_id, serial port)
    label: str                          # human label for the device card
    detail: dict | None = None          # extra info shown on the card (model, rate, address)

@dataclass
class AdapterStatus:
    state: str                          # streaming | stalled | errored_transient | errored_fatal | idle | paused
    rate_est: float | None = None       # observed samples/s (for stall detection + dashboard)
    quality: dict | None = None         # typed per-modality quality (e.g. {"hsi":[1,1,2,1]} for Muse)
    last_error: str | None = None

@dataclass
class ReconfigResult:
    applied: bool                       # True if applied in place
    requires_segment: bool = False      # True if the change closed a segment and opened a new StreamSpec revision
    message: str | None = None
```
`AdapterInfo`: `id: str`, `title: str`, `category: str`, `multi: bool = False` (multiple instances allowed), `requires: str | None = None` (e.g. `"browser"`).

**`timing_mode` vs manifest `timing` (must-fix 1).** The StreamSpec attribute is `timing_mode: str` (the author-declared mode). The RecordingCore composes the manifest `timing` **object** (**§4.3**) at finalize, filling `sfreq_effective`, `gaps`, `index_to_t`, `confidence`, etc. The author never declares an object; the Core never asks the author for reconstructed fields.

### 6.7 Worked example — Muse EEG
```python
# adalog/sense/devices/eeg_muse.py
from adalog.adapters.templates.lsl import LSLDevice
from adalog.adapters.base import StreamSpec, Channel, AdapterInfo
from adalog.schema.fields import StrField

class EegMuseAdapter(LSLDevice):
    info = AdapterInfo(id="eeg_muse", title="Muse EEG (LSL)", category="neuro")

    @staticmethod
    def config_schema():
        return {"lsl": {"source": StrField("Muse", doc="LSL source id")}}   # grouped: group "lsl", field "source"

    def default_query(self):                        # template resolves + dedups Muse multi-outlet by source_id
        return {"source": self.cfg.lsl.source}      # config via self.cfg.<group>.<field>

    def resolve_streams(self):                       # called AFTER open(): true channels/rates from inlet.info()
        out = [StreamSpec(id="eeg", modality="eeg",
                          channels=[Channel(c, "uV", "float32") for c in self.ch_names("EEG")],
                          encoding="arrow_ipc_stream", timing_mode="anchored_irregular",
                          sfreq_nominal=self.nominal("EEG"))]
        if self.has("PPG"):
            out.append(StreamSpec(id="ppg", modality="ppg", channels=self.ch_specs("PPG"),
                                  encoding="arrow_ipc_stream", timing_mode="anchored_irregular",
                                  sfreq_nominal=self.nominal("PPG")))
        return out
    # start()/emit pumping, time_correction refresh, gap detection all live in LSLDevice.
```

---

## 7. Session lifecycle & configuration (must-fix 11)

A session is created **before** `start()`; **§5.5**'s `start()` assumes the directory already exists, and this section closes that gap.

### 7.1 Session-create input
`session_create` takes:
- **`sessions_root`** — resolved in priority order: explicit CLI flag `--sessions-root` → UI-chosen path → persisted last-used (config store, **§8**) → default `~/adalog-sessions`. The resolved value is recorded in the run log (not the manifest; the manifest path is implied by location).
- **`user`** — `provenance.user_id`; from config store (single-user local default `"u_local"`), overridable in UI.
- **`subject`** — `{ id, attributes }` (e.g. `{handedness:"R"}`); from subject defaults (config store) + UI edits.
- **`label`**, **`tags[]`** — free text from UI.
- **`devices[]`** — the selected/armed device set (each an `{adapter_id, instance_id, config}`).

### 7.2 FSM and transition guards
States: `created → armed → recording → (paused ↔ recording) → stopped`; plus `recovering` (entered automatically when a `manifest.lock` is found at launch) → `recovered`.

| Transition | Guard |
|---|---|
| `create` | `sessions_root` writable; free-disk pre-flight passes |
| `arm` | ≥1 device selected; **every selected device's `open()` succeeds** (or is explicitly skipped); `config_schema` required fields satisfied; Secrets resolvable from keyring |
| `start` | state `armed`; session dir + `manifest.lock` written; all armed adapters `start()`-ed |
| `pause` | state `recording`; writes `PAUSE` marker + opens pause interval |
| `resume` | state `paused`; writes `RESUME` marker + closes pause interval |
| `stop` | state `recording`/`paused`; all adapters `stop()`/`close()`; `reconcile()`; finalize hashes; `status:"complete"`; remove `manifest.lock` |
| `recover` | `manifest.lock` present at launch; runs `recover()` (**§5.5**); `status:"recovered"` |

**Arm preconditions and device addition.** All devices that must be in the dataset are armed before `start`. After `start`, the only devices that may join are **late joiners** (**§6.5**) — adapters armed-then-started mid-session, anchored at their first packet's session time. Adding a *new, unarmed* adapter type mid-session is not supported in Spec 1 (it would require re-arming guards mid-recording); the supported path is arm-before-start or late-join an already-armed instance.

### 7.3 Provenance field sources
Every `provenance`/`clock` field ties to a concrete source:

| Field | Source |
|---|---|
| `provenance.user_id` | config store `user` (default `"u_local"`) |
| `provenance.app` | constant `"adalog-sense"` |
| `provenance.app_version` | package `__version__` (from `importlib.metadata`) |
| `provenance.host` | `socket.gethostname()` |
| `provenance.os` | `platform.system()` + release |
| `provenance.created_with` | `"standalone"` here; `"goofi"` in Spec 3 |
| `clock.tz` | OS local tz at `start()` |
| `clock.host_drift_ppm` | measured by SessionClock anchor regression |
| `clock.boottime_used` | whether `CLOCK_BOOTTIME` was used (**§5.1**) |
| `clock.wall_uncertainty_s` | best-effort NTP-grade bound at anchor time |
| `subject` | config store subject defaults + UI |

---

## 8. Configuration persistence (must-fix 12)

A small config store (`adalog.core.config_store`) underpins the "record in seconds on 2nd launch" goal.

- **Location.** A platform config dir (`platformdirs.user_config_dir("adalog")`), e.g. `~/.config/adalog/config.json` on Linux. Sessions data is separate (**§7.1**); config never lives inside session dirs.
- **Schema.** A single versioned JSON document with three scopes:
  - **app-level:** `user_id`, `sessions_root`, `window_layout` (mirrors `/api/layout`), UI theme token override, fsync-cadence overrides.
  - **per-session defaults:** subject defaults (`subject.id`, `attributes`), default tags.
  - **per-device config:** keyed by `adapter_id` (+ `instance_id` for multi), the resolved non-secret `config_schema` values, plus the **last-used selected device set**.
- **Read/write points.** Read at app boot (to pre-populate the device catalog, layout, subject defaults) and at `arm`/`start` (to resolve device config). Written on: device configure/apply, session stop (last-used device set + subject defaults), layout change, and explicit settings edits.
- **Persists across restarts:** device configs, last-used selected device set, subject defaults, window layout, `sessions_root`, theme. **Does not persist:** live session state, transient discovery results, runtime status, anything time-varying.
- **Secrets (must never be plaintext).** `Secret` fields (**§3** `fields.py`) are stored in the **OS keyring** (`keyring` library) keyed by `adalog/<adapter_id>/<field>`; the JSON config stores only a *reference marker*, never the value. Resolution happens at `arm` (**§6.1**). If the keyring is unavailable, the field is treated as unset and the user is prompted — never silently written to disk.

---

## 9. The 8 launch adapters

1. **EEG (Muse/DSI)** — `LSLDevice`; `anchored_irregular`; re-enabled LSL **per-sample** timestamps + `time_correction`; multi-substream (EEG + optional PPG/ACC at distinct rates); `arrow_ipc_stream` + per-batch timing sidecar (**§5.4a**); signal-quality in `status().quality`.
2. **ECG** — `SerialDevice`; raw `anchored_irregular` from device frames; a **derived `hrv` stream** declared `per_sample` with a `derivation` block (`source_stream:"ecg", method:"rr_interval", window:{kind:"event",basis:"R-R"}`, **§4.3**) — derived analytics that are *recorded* are first-class streams; live HRV that is *not* recorded is a monitor. Serial port + baud + sfreq exposed in config (no hardcoded COM5).
3. **Audio** — `AudioDevice`; `anchored` with **measured** `sfreq_effective` + true ADC `t_start`; mono float32 48k WAV; SPILL; RMS is monitor-only.
4. **Drawing** — `UiSourceDevice`; two files in one stream: `snapshot.png` (`event`) + `pentrace.ndjson` (`per_sample`: `t,x,y,pressure,stroke_id`). (Fixes the old full-canvas-snapshot redundancy and double-write bug.)
5. **Text** — `UiSourceDevice`; `per_sample` word-onset (`t,word`), onset reconciled via the browser handshake; handles edits/backspacing (no append-only assumption). (Fixes the old double-write bug.)
6. **MIDI** — from-scratch; writes a `per_sample` `midi.ndjson` mirror through the crash-safe append path (always recoverable) **and** a `.mid` SMF finalized at stop, rebuildable from the mirror on recovery (resolves "finalize-at-stop vs append-only"). Preserves true timing (no 120-BPM-grid quantization). MIDI message time is captured in the callback (push) and rides on the packet (**§5.2**).
7. **OSC** — dynamic `per_sample` via `ctx.register_stream`; goofi-compatible wildcard address binding; structured/list values stored as JSON (not `str()`); `_store` side-channel as a declared `event`-file stream; configurable port.
8. **Meteo** — `RestPollDevice`; NOAA space-weather ~10s poll **off the UI thread**; `per_sample`; ETag dedupe; backfilled rows (`ts < last`) handled by the per-sample writer and flagged; errors surfaced, not swallowed.

---

## 10. Standalone runtime (`adalog.sense`)

Both this spec's standalone mode and Spec 3's goofi mode drive the same `adalog.sense.service.RecorderService` (owns adapters, `Session`, `RecordingCore`, store handle, config store). No recording logic is duplicated.

The **sense-bridge** is a tiny aiohttp daemon-thread server (the verified goofi `BridgeServer` pattern, minus Manager/iceoryx2/node-processes). It:
- serves the **prebuilt static SvelteKit bundle shipped inside the Python wheel** (no Node at runtime; goofi's dev-only `npm run build` path is removed for adalog's wheel);
- speaks a **control plane**, a **data plane**, and a **status plane** over WS, via a **shim** that projects each adapter instance as a "node" whose output "slots" are its declared streams — so the reused frontend's shell and leaf viewers render device cards, params, and viewers (**§11**);
- refactors goofi's hardcoded control if-chain (verified in `control.py:_dispatch`) into an **op-registry** so adalog registers `session_*` / `device_*` / `discover` / `device_ingest` / `layout_*` ops cleanly.

**Cold-boot budget.** The hot path imports only `aiohttp` / `numpy` / `msgpack`. `pylsl` / `sounddevice` / `mido` / device libs are **lazy-imported inside `open()`/`discover()`** in worker threads. A CI import-budget guard fails the build if a heavy lib appears on the hot path. Realistic target: **record-ready UI fast (a few hundred ms), device discovery streams in asynchronously** — not a hard sub-second wall, which `aiohttp+numpy` startup and LSL network resolution make brittle.

---

## 11. The Bridge Protocol (normative)

This is the load-bearing "ready to record" contract between the frontend and `RecorderService`. It is normative: the op-registry + shim are validated by a **fixture-based conformance contract** (a recorded set of request/response/error fixtures the server must satisfy and the client must accept; **§15**).

### 11.1 Transport & framing
Two WS endpoints (the data plane is separated so monitor backpressure never touches control):
- **Control/status plane** `/ws/control` — JSON request/response + server-pushed status events.
- **Data plane** `/ws/data` — binary GOOF v2 frames for the monitor plane.

Control messages are JSON objects:
```jsonc
// request
{ "op": "session_arm", "id": "req-7", "args": { ... } }
// response (success)
{ "id": "req-7", "ok": true, "result": { ... } }
// response (error)
{ "id": "req-7", "ok": false, "error": { "code": "PRECONDITION", "message": "no devices armed", "detail": {...} } }
```
Error `code ∈ {BAD_REQUEST, PRECONDITION, NOT_FOUND, DEVICE_ERROR, INTERNAL}`.

### 11.2 Control ops (session + device + layout)
Session ops:
```jsonc
"session_create"  args:{ sessions_root?, user?, subject?, label?, tags?, devices?[] }   result:{ session_id, state:"created" }
"session_arm"     args:{ }                                                              result:{ state:"armed", devices:[{instance_id,state}] }
"session_start"   args:{ }                                                              result:{ state:"recording", t0_utc_ns }
"session_pause"   args:{ }                                                              result:{ state:"paused", at_t }
"session_resume"  args:{ }                                                              result:{ state:"recording", at_t }
"session_stop"    args:{ }                                                              result:{ state:"complete", manifest_path, duration_s }
```
Device ops:
```jsonc
"device_discover"  args:{ adapter_id? }              result:{ sources:[ DiscoveredSource ] }          // streams in async
"device_arm"       args:{ adapter_id, source_id?, config? }  result:{ instance_id, node_id, streams:[StreamSpec] }
"device_configure" args:{ instance_id, group, name, value }  result:{ ReconfigResult }
"device_start"     args:{ instance_id }              result:{ state:"streaming" }
"device_stop"      args:{ instance_id }              result:{ state:"idle" }
"device_ingest"    args:{ instance_id, batch }       result:{ accepted:int, dropped:int }             // §11.4
```
Layout ops (back the injected `LayoutPersistence`):
```jsonc
"layout_get"  args:{ }            result:{ layout: <opaque shell tree> }
"layout_set"  args:{ layout }     result:{ ok:true }
```

### 11.3 Data-plane wire frame & deterministic id mapping
GOOF v2 carries **no time/seq** (verified). The data-plane frame therefore wraps each GOOF payload in an **envelope header** that does:
```
data frame = [ envelope header (msgpack) ][ GOOF v2 payload (binary) ]
envelope header = {
  "node_id":   str,     // deterministic, see below
  "slot_id":   str,     // deterministic, see below
  "stream_id": str,     // == StreamSpec.id
  "seq":       int,     // StreamPacket.seq (monitor-plane gap visibility)
  "t":         float,   // session-time of the frame's first sample
  "device_ts_ns": int|null,
  "timing_mode": str    // for viewer hinting
}
```
**Deterministic node-id / slot-id naming.** `node_id = adapter instance_id` (`"<adapter_id>#<n>"`, stable for the session). `slot_id = StreamSpec.id`. So a Muse instance `eeg_muse#0` exposes slots `eeg`, `ppg`, `acc`. **Live mutation:** a reconfigure that opens a new StreamSpec revision keeps `node_id`/`slot_id` stable but bumps a `revision` in the shim's slot descriptor (the shell re-renders the viewer); a new **segment** keeps the same ids (continuity); a **late join** adds a new `node_id` and is announced via a `node_added` status event (**§11.5**); a dynamic OSC `register_stream` adds a new `slot_id` under the existing OSC `node_id`, announced via `slot_added`.

### 11.4 Browser→UiSource `device_ingest` path (must-fix 10)
This is the **sole acquisition route** for Drawing and Text, so it is fully specified.

**Clock-offset handshake** (control op, refreshed on a cadence so the <50 ms onset target holds):
```jsonc
"clock_handshake" args:{ instance_id, client_perf_now_ns, client_send_ns }
                  result:{ server_mono_ns, server_recv_ns }   // client computes offset + RTT/2; repeats
```
Cadence: on connect, then every **5 s** (and on visibility-regain). The client maintains a smoothed offset; `DeviceClock` (browser) uses it to reconcile each sample's `t_browser` into session time.

**`device_ingest` payloads** (single or batched; batched is preferred for high-rate pen data):
```jsonc
// pen sample (drawing pentrace, per_sample)
{ "kind":"pen",  "t_browser_ns": 1234567, "x":0.42, "y":0.61, "pressure":0.8, "stroke_id":7 }
// word onset (text, per_sample)
{ "kind":"word", "t_browser_ns": 1234999, "word":"intuition" }
// batched form
{ "instance_id":"drawing#0", "batch":[ {pen...}, {pen...}, {word...} ] }
```
The `UiSourceDevice.on_ingest(msg)` parses these into `StreamPacket`s with `per_sample_ts` reconciled via the handshake offset; the snapshot upload (`kind:"snapshot"`, base64 PNG or binary side-upload) emits an `event` packet.

**Binding.** A `UiSourceDevice` instance is bound to a specific browser **panel/connection**: `device_arm` returns `instance_id`; the panel includes that `instance_id` on every `device_ingest`. If the bound connection drops, the instance goes `stalled`; a new panel may rebind via `device_arm` with the same `source_id` (re-uses the instance).

**Recording-state gating.** When the session is **not recording** (created/armed/stopped), `device_ingest` samples are **dropped** with `result.dropped` counted (live preview still renders via the monitor plane). When **paused**, samples are **dropped** and counted (pause is an explicit gap). Only while **recording** are samples written. This prevents pre-roll/paused keystrokes from polluting the dataset while keeping the UI live.

**End-to-end test (normative).** Text panel `keydown` → `device_ingest{kind:"word"}` → `on_ingest` → `StreamPacket(per_sample_ts=[reconciled t])` → writer → `text.ndjson` + manifest, with the reconciled `t` within the <50 ms onset bound of the simulated true onset.

### 11.5 Status / telemetry plane (must-fix 13)
Status reaches the frontend by **server push over the control/status WS** (`/ws/control`), not by polling. The server emits status events at a cadence of **~2 Hz** (and immediately on any error/state change). `status()`/watchdog results and caught adapter exceptions both flow here.

**Typed integrity-dashboard payload** (`adalog.core.status`):
```jsonc
// per-stream sample (cadence ~2 Hz)
{ "kind":"stream_status", "node_id":"eeg_muse#0", "stream_id":"eeg",
  "seq_rate": 245.9,           // packets/s
  "ring_depth": 3, "wal_depth": 0, "handoff_depth": 12,
  "drops": 0, "drift_ppm": 2.1, "gaps": 1,
  "last_error": null, "state": "streaming" }
// session-level event (immediate)
{ "kind":"session_event", "event":"paused"|"resumed"|"writer_lag"|"node_added"|"slot_added"|"recovered",
  "at_t": 160.41, "detail": {...} }
// adapter error (immediate)
{ "kind":"adapter_error", "node_id":"ecg_serial#0", "code":"errored_transient",
  "message":"serial read timeout", "at_t": 88.2 }
```
**Relation to `events.ndjson`.** Live status is the *real-time view*; the **durable record** of the same facts lives in `events.ndjson` (clock/suspend events, `PAUSE`/`RESUME`, adapter errors, `WriterLag`). The status plane is ephemeral and lossy (monitor-class); `events.ndjson` is the crash-safe, replayable source of truth. The dashboard reads the status plane live and the session inspector reads `events.ndjson` after the fact.

---

## 12. UI & panels (frontend)

**What is reused vs written new (must-fix 8).** adalog makes **zero changes to the shared shell and introduces no new low-level framework**, but **adalog authors all of its own panels.** Precisely:

- **Reused (from `@goofi/workspace-shell` / `@goofi/bridge-client`):** the workspace shell (panel tree, split/resize, panel chrome via `PanelHeader`/`EmptyPanel`, the `registerPanel` seam), the GOOF `decode.ts`, the leaf **viewer components** (uPlot `ArrayViewer`, topomap, pen-trace canvas, etc.), the WS client patterns, and the injected `subscribe(node, slot, cb)` seam.
- **Written new by adalog (all panels):** RecorderPanel, DevicePanel, MonitorPanel, FeatureMonitorPanel, SessionInspectorPanel — including the **auto-generated Field/param UI**, the **device cards**, and the panel-level state. The leaf viewers are dropped *into* adalog's MonitorPanel; the panel itself is adalog code.

(The earlier claim "zero new frontend framework code" overstated reuse and is dropped; the honest claim is the bolded one above.)

All panels register via the existing `registerPanel({id,title,component,defaultState,chrome,acceptsNode})` seam with `PanelProps {panelId,state,setState,active}` — no edits to the shared shell.

- **RecorderPanel** (default, chromeless) — record/stop/**pause/resume**, subject + tags, master-clock elapsed, and the **integrity dashboard** fed by the status plane (**§11.5**): per-stream seq-rate, ring/WAL/handoff depth, `drops` (red if nonzero), drift ppm, gaps, last-error badge. The single source of truth for "is my recording healthy".
- **DevicePanel** — auto-discovered source cards (from `device_discover`), grouped by category; arm/configure with the auto-generated Field UI; `status()` (streaming/stalled/errored_transient/errored_fatal) with one-click reconnect. Error isolation is *visible*: a red adapter does not stop the session.
- **Per-device MonitorPanel** — live preview via the latest-wins monitor plane (data WS, **§11.3**) + reused goofi viewer components (uPlot traces, topomap, audio RMS, pen-trace canvas, OSC address tree, meteo gauges), opened only while visible (IntersectionObserver). Decoupled from recording.
- **FeatureMonitorPanel** — downstream/derived monitors (band-power, HRV, word-rate) computed live for QA; monitor-only unless declared as a recorded stream. The seam adalog-play (future) reuses for online models. Heavy DSP here lazy-loads and stays off the recorder hot path.
- **SessionInspectorPanel** — open a local session, show manifest/streams/timing/provenance + `events.ndjson`, scrub the aligned timeline. (The cross-user *discovery* catalog is Spec 2.)

Default first-launch layout: Recorder top, Devices left, Monitor center, FeatureMonitor strip — devices and a record button visible immediately. Visual identity is a single CSS-custom-property token override (goofi's theming is `:root` tokens).

---

## 13. Legacy → new converter (`adalog.convert`)

Reads old `adalog-sessions/<user>/<dir>/` trees and emits v1 sessions. Verified pathologies it must absorb (the EEG/text/tags pathologies are pinned to `phil/2025-05-31T23-09-11-481969`; see should-fix (l) note below):
- **EEG goofi `WriteCsv`**: `eeg-TP9..` columns + ISO `timestamp`, filename-LOCAL time, nominal 256 but **246.3 Hz effective, 983 backwards stamps, 2.43 s max gap, 161,353 samples (~147.6k+) with many sharing the back-computed dt = 1/256** ⇒ emit `anchored_irregular` `eeg.arrow` + reconstructed timing sidecar, measure `sfreq_effective`, record real gaps, mark `clock_provenance:"reconstructed"`, `confidence:"approximate"`.
  - **Gap threshold (should-fix k).** A "gap" is a consecutive-timestamp `dt` exceeding the threshold `gap_thresh = 2 × (1 / sfreq_effective)`. Under this definition a re-measure of the fixture finds **1,649 gaps** at `> 2×` nominal `dt` (the previously cited "1017 gaps" used an undefined threshold and is **illustrative only** / superseded). The converter records the threshold it used in the stream's provenance so the figure is reproducible.
- **No master clock** ⇒ synthesize `t0` = earliest credible UTC across modalities; re-base all to session seconds.
- **`tags.csv`** (append-on-edit) ⇒ reduced to `events.ndjson` + manifest `tags`.
- **text/drawing double-writes** ⇒ dedupe by `(t, content)`.
- **git-LFS audio** ⇒ `audio.wav` with `anchored` `t0` from first stamp; **skip-with-warning if only an LFS pointer is present** (verified: audio files in the `phil/2025-05-25T*` dirs are 134-byte LFS pointer stubs, not media).
- Writes a `provenance` block flagging every reconstructed/inferred value. A CI test converts the real `phil/*` fixtures and asserts the manifest validates **and** the eeg2txt `timestamp→index(0.2 s)` alignment still resolves — the regression gate.

> **Fixture pinning (should-fix l).** For CI reproducibility, the cited pathologies are pinned to specific directories: **EEG / text-double-write / tags** ⇒ `phil/2025-05-31T23-09-11-481969` (verified to contain `Eeg/eeg_20250531_190911.csv`, `Text/`, `tags.csv`). **git-LFS audio** ⇒ `phil/2025-05-25T00-06-33-934420` (and sibling `2025-05-25T*` dirs), whose `Audio/*.wav` are LFS pointer stubs. **Drawing** has **no fixture in this tree**: the drawing/pen-trace converter test fixtures **must be pinned during implementation** and are marked **illustrative** until then. The converter test config records the exact pinned dir per pathology so the regression gate is reproducible.

---

## 14. Engine & play attachment points (informational — not built here)

- **adalog-engine** (offline) will depend on `adalog.core.reader` (manifest → aligned `Stream` objects) + (Spec 2) the discovery/catalog. eeg2txt becomes `idx = round((word.t − eeg.t_start) * eeg.sfreq_effective)` — exact, gap-aware, no 0.2 s nearest-match. Engine never depends on `adalog.sense`.
- **adalog-play** (online) will instantiate the same `DeviceAdapter`s for live streams, run engine models on the `StreamPacket` flow, and (Spec 3) use the goofi client for DSP-heavy experiences. It can **record while it runs** by routing live adapters through the same Core — an experience is also a dataset.
- The **manifest + clock + envelope + reader** are the shared lingua franca. This spec must not add anything that blocks those uses.

---

## 15. Testing strategy

- **TDD on the spine first.** A `FakeClock` + synthetic adapters drive tests for: clock monotonicity & suspend handling; `anchored_irregular` `index_to_t` exactness against the real 246.3 Hz fixture (the round-trip exactness test, **§5.4a**, `ε = 1 µs`); gap accounting; drop counting; manifest validate/reconcile.
- **Fault injection.** `kill -9` mid-write for each writer; full-disk; fsync hang → watchdog degrade; **partial Arrow record batch (torn-tail), truncated NDJSON, headerless WAV → `recover()` salvages and marks `recovered`** (and the schema-message-missing case → `failed`). Assert the **≤ 250 ms power-cut loss bound** (should-fix i).
- **Lossless stress.** 48 kHz audio + 256 Hz EEG + bursty OSC concurrently for an extended run; assert zero *uncounted* loss, that all overruns appear as counted `drops`, and bounded memory (handoff buffer + ring stay within their declared bounds).
- **Conformance suite.** Every adapter runs through a host harness asserting it honors the contract (declares streams, emits valid packets incl. `per_sample_ts` for `anchored_irregular`, isolates errors, reconfigures). The same suite re-runs under Mode B in Spec 3.
- **Bridge & frontend integration (should-fix o).**
  - **Bridge control-op contract test** — the fixture-based conformance contract (**§11**): the server must satisfy a recorded set of request/response/error fixtures for every op, and the client must accept them.
  - **Browser e2e (Playwright or equivalent)** — the record flow (arm → record → stop) plus **text and drawing `device_ingest`** end-to-end, including the clock handshake.
  - **Panel-renders-from-shim smoke test** — each adalog panel renders from a stubbed shim/data-plane fixture without a live backend.
- **Fixture regression.** The converter runs on the pinned real `phil/*` sessions in CI (**§13**); eeg2txt alignment math is re-validated; the gap-threshold figure is asserted against the pinned EEG dir.
- **Import-guard & codec-version contracts** run in CI (invariant #6; GOOF `version == 2`; one-wire-format lock, should-fix g).
- **DriftEstimator validation** against real Muse/DSI/ECG/audio hardware captures (not only the legacy fixture) before EEG/ECG ship as `complete`-grade.
- **Multi-day / suspend clock tests with a numeric bound (should-fix p).** Over an **N-hour run (target ≥ 8 h) including at least one suspend**, assert: reconstructed UTC error at any anchor **≤ 50 ms** (within `wall_uncertainty_s`), and `index_to_t` reconstruction error for `anchored_irregular` **≤ 2 ms** end-to-end (excluding the real suspend gap itself, which must appear as a `reason:"suspend"` gap, not drift).

---

## 16. Residual risks & validation requirements

1. **`anchored_irregular` reconstruction** must robustly distinguish device drift vs buffer-coalesced back-computed timestamps vs real dropouts (the real data shows ~147k+ identical dt + 983 backwards stamps). A bad fit corrupts `sfreq_effective` or shatters a stream into spurious gaps. → Tolerances validated against real hardware; conservative fallback to `clock_provenance:"reconstructed"`/`nominal` with `confidence:"approximate"`/`"nominal"` (**§4.3**).
2. **Arrow record-batch crash-safety** — the reader must salvage a torn-tail / last-record-batch-truncated Arrow IPC stream at the chosen chunk grain (**§5.5**); flush cadence trades durability vs throughput at 256 Hz + 48 kHz. → Fault-injection-tested; flush cadence tuned to the ≤ 250 ms bound.
3. **Browser onset accuracy** (Text/Drawing) is bounded by the clock handshake + WS jitter; these are the modalities eeg2txt aligns against. → Target < 50 ms; capture at keydown via `performance.now()` and batch-send; refresh handshake every 5 s (**§11.4**); surface measured uncertainty.
4. **Cold-boot** is "record-ready fast, discovery async", guarded by a CI import budget — not a hard sub-second SLA.
5. **Workspace-shell / bridge-client extraction** depends on goofi-pipe publishing the packages; mitigated by a pinned vendored snapshot fallback behind the same package names.

---

## 17. Build / milestone order (Spec 1)

1. `adalog.core` clock (BOOTTIME + per-OS fallbacks, anchors) + `DeviceClock` mappers + `StreamPacket` (incl. `per_sample_ts`) + manifest schema (incl. `timing` object, `confidence`, `derivation`) + validate/reconcile. **Write the correctness test suite first.**
2. Writers (Arrow IPC stream + per-batch timing sidecar, CSV/NDJSON, WAV) + bounded ring + lock-free handoff + WAL spill + journal + format-aware `recover()` (torn-tail Arrow, fsync-cadence bound). `kill -9` + auto-recover test green.
3. `adalog.schema` Fields + JSONSchema export. `config_store` (incl. keyring Secrets).
4. `DeviceAdapter` ABC + full SDK types (**§6.6**) + `AdapterSupervisor` (isolation, stall-watchdog, restart-segments, late-join, pause) + `Session` FSM (**§7**) + `RecorderService`; prove a session records + finalizes headlessly with a synthetic adapter.
5. Registry + entry-points + an out-of-tree dummy adapter package (proves extensibility).
6. Templates in order: `RestPollDevice` (meteo) → `LSLDevice` (EEG) → `AudioDevice` → `SerialDevice` (ECG) → `UiSourceDevice` (drawing/text, **stubbed here**) → `WebSocketDevice`. Then the hardware launch adapters. **`UiSourceDevice` templates are stubbed at step 6 and validated end-to-end at step 8** (they need `device_ingest`, which lands with the bridge); a **headless `device_ingest` harness** exercises `on_ingest` round-trips at step 6 so the template is not untested (should-fix n).
7. `store` interface + local backend; `reader.py`.
8. **Bridge + frontend, split into separately-gated sub-milestones (should-fix m):**
   - **8a — Bridge protocol + op-registry + headless control conformance.** Implement `/ws/control` op-registry and all session/device/layout ops; the status plane.
     *Acceptance:* the fixture-based control-op contract test (**§11**, **§15**) passes headlessly (no browser): `session_create→arm→start→stop` and `device_*` round-trips match recorded fixtures.
   - **8b — Shim + data plane + one monitor viewer.** Implement the shim (adapter→node/slots), `/ws/data` envelope frames, and wire one reused viewer.
     *Acceptance:* a synthetic adapter's frames decode in the browser and render in one MonitorPanel viewer (panel-renders-from-shim smoke test green).
   - **8c — Recorder + Device panels: arm → record → stop.** Author RecorderPanel + DevicePanel; integrity dashboard from the status plane.
     *Acceptance:* Playwright drives arm → record → stop and the produced session validates; EEG end-to-end against the notebook math.
   - **8d — UiSource (text) e2e with <50 ms onset check.** Wire `device_ingest` + clock handshake for Text/Drawing.
     *Acceptance:* Playwright keydown → `device_ingest` → manifest with reconciled `t` within **< 50 ms** of simulated true onset (**§11.4** e2e test).
9. `adalog.convert` + CI fixture regression against eeg2txt (pinned dirs, **§13**).
10. Harden: lossless stress + fault injection, manifest conformance, multi-day/suspend clock tests (≥ 8 h, numeric bounds, **§15**), import-budget + import-guard CI.

This front-loads the contract + clock + losslessness (the reason adalog exists), and delivers a delightful goofi-free standalone recorder by step 8 (gated as 8a–8d), with migration in step 9. Spec 2 (Drive sync) and Spec 3 (goofi co-hosting) then layer onto this stable spine.

---

## 18. Appendix A — The seven fatal flaws and their fixes (should-fix a)

The adversarial generate→critique→merge surfaced seven fatal flaws across the five candidate architectures. Each is fixed and located here:

1. **No master clock / per-sample wall stamps** (NTP steps and cross-modal drift corrupt alignment). → Fixed by the one-monotonic-clock invariant and anchor-pair UTC reconstruction: invariant #1, **§5.1**.
2. **Adapters touching disk / the wall clock** (re-introduces interpolation lies and races). → Fixed by "adapters produce, Core stamps and writes": invariant #2, **§5.2–§5.3**, **§6.1**.
3. **Silent frame drops or unbounded OOM under load** (block-free + drop-free + bounded is impossible). → Fixed by the bounded-buffer + counted-drop pipeline for all transport classes: invariant #3, **§5.4**.
4. **Crash leaves an unreadable/footerless file** (footer-finalized Parquet, no journal). → Fixed by Arrow IPC stream + journal + format-aware torn-tail `recover()`: invariant #4, **§5.5**, **§5.4a**.
5. **Timing re-derived from filenames/column order** (the legacy `WriteCsv` pathology). → Fixed by "the manifest is THE contract" with first-class per-file timing/provenance and the four timing modes: invariant #5, **§4.3**.
6. **goofi/torch/iceoryx2 leaking into the recording spine** (kills the goofi-free, fast-boot, Spec-3-ready design). → Fixed by the CI import-guard boundary: invariant #6, **§3.1**, **§10**.
7. **One adapter raise aborts the whole session** (no error isolation). → Fixed by per-adapter supervised isolation + counted/recorded degrade: invariant #7, **§6.5**, surfaced via the status plane **§11.5**.
