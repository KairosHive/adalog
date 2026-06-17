# adalog-sense Core Recorder — Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD. Steps use checkbox (`- [ ]`) syntax. Spec: `docs/superpowers/specs/2026-06-17-adalog-sense-core-design.md`.

**Goal:** A standalone, goofi-free, lossless, crash-safe multimodal recorder that captures the 8 launch devices into self-describing session directories governed by one master clock, served by a web UI, plus a legacy-data converter.

**Architecture:** A goofi-free Python recording spine (`adalog.core`) — one monotonic `SessionClock`, per-stream `DeviceClock` mappers, a chunk-grained `StreamPacket` envelope, a bounded-buffer lossless `RecordingCore` with format-aware crash recovery, and a versioned `manifest.json` contract. A declarative device-adapter SDK (`adalog.adapters`) with templates. A standalone runtime (`adalog.sense`) whose aiohttp `sense-bridge` serves a Svelte SPA over a normative control/data/status WS protocol. A `adalog.convert` legacy migrator.

**Tech Stack:** Python 3.12, `numpy<2`, `pyarrow` (Arrow IPC stream), `msgpack`, `soundfile`/`sounddevice`, `pylsl`, `pyserial`, `mido`/`python-rtmidi`, `oscpy`, `aiohttp`, `pydantic` v2, `blake3`, `ulid`, `platformdirs`, `keyring`, `requests`; pytest + pytest-asyncio; `import-linter`; SvelteKit/Svelte 5 frontend.

## Global Constraints (verbatim from spec)
- **Invariant #1:** session time derives only from a monotonic source; UTC enters as anchor pairs; no `datetime.now()/utcnow()/time.time()` outside `adalog.core.clock`.
- **Invariant #2:** adapters produce; the Core stamps + writes. Adapters never open files / read wall clock.
- **Invariant #3:** lossless until a *bounded* buffer overflows, then *counted* drops; never silent, never OOM.
- **Invariant #4:** crash-safe by append + journal + format-aware recover.
- **Invariant #5:** the manifest is THE contract; timing-provenance is first-class per file.
- **Invariant #6:** `adalog.core`, `adalog.schema`, `adalog.adapters`, `adalog.store`, `adalog.convert`, `adalog.bridge_codec` import nothing from `goofi`, `torch`, `iceoryx2` (CI import-linter).
- **Invariant #7:** recording plane ⊥ monitor plane.
- **Invariant #8:** record 100% locally first; sync (Spec 2) never in the record path.
- Timing modes enum: `{per_sample, anchored, anchored_irregular, event}`. `anchored_irregular` requires per-sample device timestamps.
- GOOF codec version == 2. Power-cut loss bound ≤ 250 ms. anchored_irregular round-trip ε = 1 µs.

---

## Phase 0 — Repo skeleton & tooling

### Task 0.1 — Package scaffold, pyproject, import-linter, CI guards
**Files:** Create `pyproject.toml` (replace), `src/adalog/__init__.py`, `importlinter.ini`, `tests/conftest.py`, `.github/workflows/ci.yml`. Delete legacy: `adalog.py`, old `src/adalog/*` modules, `src/adalog/modalities/`, `src/adalog/scripts/`.
**Produces:** the `adalog` distribution with layered subpackages `adalog.{core,schema,adapters,store,sense,convert,bridge_codec}`; `pytest` + `lint-imports` runnable.
- [ ] Write `pyproject.toml` (deps above; extras `[dev]`, `[goofi]` placeholder; console script `adalog-sense = "adalog.sense.cli:main"`).
- [ ] `uv sync`; confirm `pytest` collects 0 tests cleanly.
- [ ] `importlinter.ini`: forbidden contract (core/schema/adapters/store/convert/bridge_codec ↛ goofi/torch/iceoryx2) + layered contract (core ← adapters ← sense). Run `lint-imports` → passes (empty pkgs).
- [ ] Commit.

---

## Phase 1 — The recording spine (`adalog.core`), TDD-first

### Task 1.1 — SessionClock
**Files:** Create `src/adalog/core/clock.py`, `tests/core/test_clock.py`.
**Produces:** `SessionClock` with `t0_mono_ns:int`, `t0_utc_ns:int`, `now_s()->float`, `mono_to_utc_ns(mono_ns)->int`, `reanchor()->ClockAnchor`, `anchors:list[ClockAnchor]`, `host_drift_ppm`, `boottime_used:bool`, `wall_uncertainty_s`. `ClockAnchor{t,mono_ns,utc_ns}`. Uses `clock_gettime(CLOCK_BOOTTIME)` on Linux with per-OS fallback + suspend detection.
**Tests:** `now_s` monotonic & increasing; `mono_to_utc_ns` round-trips an anchor within ns; reanchor appends; a simulated wall-jump-without-mono-jump (fallback path, via injected clock fns) records a suspend marker; `boottime_used` reflects platform. Use dependency-injected clock functions so tests are deterministic (no real sleep).
- [ ] Test → fail → implement → pass → commit.

### Task 1.2 — DeviceClock mappers
**Files:** Create `src/adalog/core/device_clock.py`, `tests/core/test_device_clock.py`.
**Produces:** `DeviceClock(session_clock)` with `update(device_ts_ns, recv_mono_ns)`, `map(device_ts_ns)->session_mono_ns` using a robust median-of-offsets + skew fit; `provenance:str`. Variants/labels: `device_lsl`, `device_portaudio`, `browser`, `host_arrival`, `nominal`, `reconstructed`.
**Tests:** with synthetic device clock = session clock + constant offset + linear skew + noise, `map` recovers session time within tolerance; robust to outliers (inject backwards stamps); provenance set correctly.
- [ ] Test → fail → implement → pass → commit.

### Task 1.3 — StreamPacket envelope + StreamSpec/SDK types
**Files:** Create `src/adalog/core/envelope.py` (StreamPacket), `src/adalog/adapters/base.py` (StreamSpec, Channel, FileRole, AdapterInfo, AdapterStatus, DiscoveredSource, ReconfigResult — dataclasses per spec §6.6), `tests/core/test_envelope.py`.
**Produces:** `StreamPacket` (spec §5.3, incl. `per_sample_ts`); the closed SDK dataclasses (spec §6.6).
**Tests:** `anchored_irregular`/`per_sample` packet with `per_sample_ts is None` is rejected by a validator helper; StreamSpec defaults match spec; round-trip of dataclass → dict → dataclass.
- [ ] Test → fail → implement → pass → commit.

### Task 1.4 — Manifest models + validate/reconcile
**Files:** Create `src/adalog/core/manifest.py`, `tests/core/test_manifest.py`.
**Produces:** pydantic v2 models `Manifest`, `StreamEntry`, `FileEntry`, `Timing` (author-declared + core-reconstructed fields, spec §4.3), `ClockBlock`, `Provenance`, `Derivation`; `Manifest.validate()`, `Manifest.reconcile(journals)` asserting `produced_seq == persisted_rows == n_samples`; `timing.confidence ∈ {exact,measured,approximate,nominal}`; timing mode enum incl `event`.
**Tests:** a valid manifest validates; missing `event` mode rejected pre-fix / accepted post; reconcile flags a seq/row mismatch; confidence/clock_provenance enums enforced; JSON round-trip stable.
- [ ] Test → fail → implement → pass → commit.

### Task 1.5 — ids + hashing
**Files:** Create `src/adalog/core/ids.py`, `tests/core/test_ids.py`.
**Produces:** `new_session_id(salt)->str` (salted ULID, time-sortable), `blake3_file(path)->str` ("b3:..."), `blake3_bytes(b)->str`.
**Tests:** ULIDs sortable by creation order; salt changes tail not order; blake3 matches known vector.
- [ ] Test → fail → implement → pass → commit.

### Task 1.6 — StreamWriter base + registry
**Files:** Create `src/adalog/core/recorder/writers/base.py`, `tests/core/recorder/test_writer_base.py`.
**Produces:** `StreamWriter` ABC (`open(path, spec)`, `write(packet)`, `flush()`, `close()->FileEntry`, `recover(path)->FileEntry`); `WRITER_REGISTRY: dict[str, type[StreamWriter]]` keyed by encoding; `register_writer`.
**Tests:** registry resolves a fake writer; ABC enforces methods.
- [ ] Test → fail → implement → pass → commit.

### Task 1.7 — Writers (parallelizable: fan out subagents)
**Files:** Create `arrow_chunk.py` (Arrow IPC stream + per-batch timing sidecar, spec §5.4a), `wav.py`, `jsonl.py` (per_sample + event), `csv_ts.py`, `png.py`, `pentrace.py`, `midi.py` under `src/adalog/core/recorder/writers/`; matching tests.
**Produces:** concrete writers; each with `recover()` (torn-tail repair). Arrow writer: schema message fsynced before first batch; reader-side `index_to_t` from sidecar with NO uniform-spacing assumption; round-trip ε ≤ 1 µs.
**Tests per writer:** normal write→close→read round-trip; **torn-tail** (truncate file mid-batch) → recover salvages last complete unit; arrow: per-sample timestamp exactness ε=1µs incl. post-truncation; wav: headerless-recover rewrites RIFF from frame count; jsonl: truncate to last newline.
- [ ] For each writer: Test → fail → implement → pass → commit. (Dispatch one subagent per writer in parallel after base lands.)

### Task 1.8 — Bounded ring + lock-free handoff + WAL spill
**Files:** Create `src/adalog/core/recorder/ringbuffer.py`, `tests/core/recorder/test_ringbuffer.py`.
**Produces:** `BoundedRing(capacity)` (drop-counting), `HandoffBuffer(capacity)` (SPSC lock-free-ish, callback-safe push that never blocks/allocs, returns False on full), `WalRing(path)`; back-pressure regimes `SPILL|BACKPRESSURE|BLOCK`; counted-drop accounting.
**Tests:** handoff push from a "callback" thread never blocks; overflow returns False and increments a counter; drain order FIFO; WAL spill+drain round-trips; counted drops surface as ranges.
- [ ] Test → fail → implement → pass → commit.

### Task 1.9 — Journal + crash recovery orchestration
**Files:** Create `src/adalog/core/recorder/journal.py`, `tests/core/recorder/test_journal.py`.
**Produces:** `Journal(path)` append `write→fsync→journal→fsync`; `recover(stream_dir, spec)` driving the writer's format-aware repair + reconcile; fsync cadence policy (every batch or 250ms) with ≤250ms power-cut bound.
**Tests:** journal replay reconstructs persisted count; simulated `kill -9` (write partial then drop) → recover yields readable file + correct n_samples; ordering guarantee (journal never ahead of durable bytes).
- [ ] Test → fail → implement → pass → commit.

### Task 1.10 — RecordingCore (the integrator)
**Files:** Create `src/adalog/core/recorder/core.py`, `tests/core/recorder/test_core.py`.
**Produces:** `RecordingCore(session_dir, clock)` with `add_stream(spec)`, `ingest(packet)` (routes to ring→writer thread; updates DeviceClock), `monitor_tap(stream_id, cb)` (latest-wins fan-out, separate plane), `finalize()->Manifest` (reconcile + compose timing objects incl sfreq_effective/gaps/confidence + hashes post-finalize). Writer threads per stream; release GIL on I/O.
**Tests:** ingest N synthetic anchored_irregular packets → finalize → manifest timing reconstructed exactly (ε=1µs), gaps detected at `2×1/sfreq` threshold; monitor_tap drops under load while recording stays lossless; finalize hashes match files.
- [ ] Test → fail → implement → pass → commit.

### Task 1.11 — Reader
**Files:** Create `src/adalog/core/reader.py`, `tests/core/test_reader.py`.
**Produces:** `read_session(manifest_path)->Session` exposing aligned `Stream` objects (`array`, `index_to_t`, `t`, per_sample frames). Inverse of writers.
**Tests:** write a multi-stream session via RecordingCore → read back → arrays + index_to_t match; eeg2txt-style `round((word_t - t_start)*sfreq_effective)` resolves a known epoch.
- [ ] Test → fail → implement → pass → commit.

### Task 1.12 — SessionClock/Session FSM + config store
**Files:** Create `src/adalog/core/session.py` (Session FSM, spec §7.2), `src/adalog/core/config_store.py` (spec §8, platformdirs + keyring), tests.
**Produces:** `Session(created→armed→recording↔paused→stopped, recovering→recovered)` with guard checks; `session_create(...)` builds dir + lock + draft manifest; pause/resume markers to `events.ndjson`; auto-recover on launch. `ConfigStore` (app/session-defaults/per-device scopes; Secret via keyring).
**Tests:** FSM guard rejections; create writes dir+lock; stop finalizes+removes lock; recover path on found lock; config persists/loads; secret never in JSON.
- [ ] Test → fail → implement → pass → commit.

**Phase 1 acceptance:** `pytest tests/core` green; a synthetic end-to-end session records anchored_irregular + per_sample + event streams, survives a simulated kill, and reads back exactly. `lint-imports` green.

---

## Phase 2 — Schema + adapter SDK

### Task 2.1 — adalog.schema Fields
**Files:** Create `src/adalog/schema/fields.py`, tests.
**Produces:** `StrField, IntField, FloatField, BoolField, EnumField, SecretField` with `to_jsonschema()`, grouping; `ConfigSchema` = `dict[group, dict[name, Field]]`; `bind(values)->Cfg` giving `cfg.<group>.<field>` attribute access.
**Tests:** jsonschema export shape; bind attribute access; Secret marked.
- [ ] Test → fail → implement → pass → commit.

### Task 2.2 — DeviceAdapter ABC + AdapterContext
**Files:** Create `src/adalog/adapters/__init__.py` (ABC already partly in base.py), `src/adalog/adapters/context.py`, tests.
**Produces:** `DeviceAdapter` ABC (spec §6.1 signatures); `AdapterContext` (`emit`, `clock`, `device_clock`, `register_stream`, `log`, `config`/bound `cfg`); `emit` thread-safe / callback-safe.
**Tests:** a minimal synthetic adapter emits valid packets; emit callable from a thread; register_stream adds a dynamic stream.
- [ ] Test → fail → implement → pass → commit.

### Task 2.3 — AdapterSupervisor
**Files:** Create `src/adalog/adapters/supervisor.py`, tests.
**Produces:** `AdapterSupervisor` running each adapter in a supervised thread; error isolation (one raise → that stream degraded, others continue); stall watchdog (expected-vs-observed rate); restart-as-new-segment; late-join; pause/resume fan-out.
**Tests:** one adapter raising doesn't stop others; stall detected; restart bumps segment; late joiner anchored at first packet.
- [ ] Test → fail → implement → pass → commit.

### Task 2.4 — Registry + entry-points
**Files:** Create `src/adalog/adapters/registry.py`, `tests/adapters/test_registry.py`, plus a dummy out-of-tree adapter package under `tests/fixtures/adalog-dummy-device/`.
**Produces:** `BUILTIN` list, `discover_adapters()` merging entry-points group `adalog.adapters` (each load try/excepted).
**Tests:** builtin present; installed dummy appears; broken entry-point skipped not fatal.
- [ ] Test → fail → implement → pass → commit.

### Task 2.5 — Templates (parallelizable: fan out subagents)
**Files:** Create `src/adalog/adapters/templates/{rest_poll,lsl,audio,serial,ui_source,websocket}.py`, matching tests.
**Produces:** each template prefills transport + timing_mode + back-pressure regime per spec §6.2; authors fill only device-specific hooks.
**Tests (mock transports):** rest_poll polls + dedupes; lsl maps per-sample timestamps via DeviceClock; audio captures ADC time; serial frames→packets; ui_source on_ingest reconciles via handshake; websocket reconnect. Use fakes for hardware libs.
- [ ] Per template: Test → fail → implement → pass → commit. (Subagent per template after Task 2.2/2.3.)

**Phase 2 acceptance:** `pytest tests/adapters` green; conformance harness validates a synthetic adapter end-to-end through RecordingCore.

---

## Phase 3 — The 8 launch device adapters

### Task 3.1–3.8 — eeg_muse, ecg_serial, audio_mic, drawing, text, midi, osc, meteo
**Files:** Create `src/adalog/sense/devices/<name>.py` + tests (mock hardware).
**Produces:** the 8 device-specific adapters per spec §9, each subclassing a template, declaring streams/config.
**Tests:** each declares correct StreamSpec(s)/timing_mode; meteo parses NOAA fixture; osc serializes lists as JSON + `_store` event stream; midi ndjson mirror + .mid; drawing/text via ui_source; eeg multi-substream.
- [ ] Per device: Test → fail → implement → pass → commit. (Subagent per device after templates.)

**Phase 3 acceptance:** `device_discover`/`device_arm` round-trips for all 8 against mocked hardware; meteo records live (real HTTP) into a valid session.

---

## Phase 4 — Local store + converter

### Task 4.1 — store interface + local backend
**Files:** Create `src/adalog/store/base.py` (`BlobStore`, `Index` protocols), `src/adalog/store/local.py`, tests.
**Produces:** local filesystem BlobStore/Index (the seam Spec 2's Drive backend slots into).
- [ ] Test → fail → implement → pass → commit.

### Task 4.2 — converter
**Files:** Create `src/adalog/convert/__init__.py` + submodules, `tests/convert/test_convert.py`, pin fixtures from `adalog-sessions/phil/2025-05-31T23-09-11-481969` (+ `2025-05-25T*` for LFS audio).
**Produces:** `convert_session(old_dir, out_dir)->Manifest` absorbing every spec §13 pathology; provenance flags; gap threshold `2×1/sfreq_effective`.
**Tests:** convert the pinned fixture → manifest validates; eeg2txt `timestamp→index(0.2s)` resolves; gap count reproducible; LFS-pointer audio skipped-with-warning; tags/double-writes reduced.
- [ ] Test → fail → implement → pass → commit.

**Phase 4 acceptance:** `pytest tests/convert` green; real `phil/*` sessions convert to valid v1 sessions.

---

## Phase 5 — bridge_codec + sense-bridge backend

### Task 5.1 — GOOF codec (vendored, goofi-free)
**Files:** Create `src/adalog/bridge_codec/codec.py`, tests.
**Produces:** GOOF v2 encode/decode (numpy+msgpack+struct), the data-plane envelope wrapper (spec §11.3), version==2 contract test.
- [ ] Test → fail → implement → pass → commit.

### Task 5.2 — sense-bridge: control + status planes (op-registry)
**Files:** Create `src/adalog/sense/bridge/{server,control,data,shim}.py`, `src/adalog/sense/service.py`, `src/adalog/sense/cli.py`, `src/adalog/sense/app.py`, tests (aiohttp test client; fixture-based op conformance).
**Produces:** `RecorderService` (the shared brain); aiohttp server with `/ws/control`, `/ws/data`, `/ws/status` (or status on control), op-registry implementing all spec §11.2 ops; shim projecting adapters→nodes/slots; serves static frontend bundle.
**Tests (headless, milestone 8a):** fixture-based control-op contract — `session_create→arm→start→stop` and `device_*` round-trips; status push schema; device_ingest gating.
- [ ] Test → fail → implement → pass → commit.

**Phase 5 acceptance (8a/8b):** headless control conformance green; a synthetic adapter's frames decode via the codec.

---

## Phase 6 — Frontend (SvelteKit SPA)

### Task 6.1 — Frontend scaffold + goofi package consumption
**Files:** Create `frontend/` (SvelteKit, adapter-static, Svelte 5); depend on `@goofi/workspace-shell` + `@goofi/bridge-client` (extract/publish from goofi-pipe, or vendor pinned snapshot). `frontend/src/lib/{control,stores,panels,viewers-adapters}`.
**Produces:** an SPA that connects to the sense-bridge, renders the workspace shell, registers adalog panels.
- [ ] Scaffold; build; commit.

### Task 6.2 — Panels (parallelizable)
**Files:** `frontend/src/lib/panels/{Recorder,Device,Monitor,FeatureMonitor,SessionInspector}.svelte`, control client, data subscription.
**Produces:** the 5 panels (spec §12) via `registerPanel`; integrity dashboard from the status plane; device_ingest + clock handshake for UiSource (Drawing/Text); monitor viewers from `@goofi/bridge-client`.
**Tests:** Playwright e2e — arm→record→stop produces a valid session; text/drawing device_ingest e2e with <50ms onset; panel-renders-from-shim smoke.
- [ ] Per panel + e2e: implement → test → commit. (Subagents per panel.)

**Phase 6 acceptance (8c/8d):** browser e2e arm→record→stop green; EEG+text end-to-end validated against the notebook math; UiSource <50ms onset check.

---

## Phase 7 — Harden & wheel
### Task 7.1 — packaging + CI
**Files:** wheel builds frontend bundle in; CI runs pytest + lint-imports + import-budget + Playwright + GOOF version + converter regression.
- [ ] Lossless stress + fault injection + multi-day/suspend clock tests (numeric bounds); import-budget guard; commit.

**Final acceptance:** `uvx adalog-sense` (from the wheel) boots the UI, records all 8 modalities (mocked where hardware absent; real for audio/meteo/text/drawing/osc/midi), produces valid lossless sessions; converter migrates real data; full test suite green.

## Self-review notes
- Every spec section maps to a phase: §4/§5→P1, §6→P2, §9→P3, §13/§store→P4, §11/§10→P5, §12→P6, §15/§16/§17→all+P7.
- Parallelizable tasks (writers, templates, devices, panels) are flagged for subagent fan-out after their base contracts land.
- TDD throughout; commits per task; deferred: Drive sync (Spec 2), goofi Mode B (Spec 3).
