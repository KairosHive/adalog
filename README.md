<p align="center">
  <img src="https://github.com/user-attachments/assets/4dcdb86c-61b9-46f9-a337-43bb1a4265c6" alt="logo" width="300">
</p>

# adalog — multimodal data-recording platform

adalog merges modalities — devices, APIs, and human input — into one **synchronized, self-describing, lossless** dataset. The framework handles the boilerplate: clock synchronization, data formatting, crash-safe saving, and (later) cross-user sync.

This repository is undergoing a **ground-up rework** (June 2026). The full design and plan live in:

- Spec: [`docs/superpowers/specs/2026-06-17-adalog-sense-core-design.md`](docs/superpowers/specs/2026-06-17-adalog-sense-core-design.md)
- Plan: [`docs/superpowers/plans/2026-06-17-adalog-sense-core.md`](docs/superpowers/plans/2026-06-17-adalog-sense-core.md)

## Three apps

- **adalog-sense** — the recorder (the focus of the current rework). Standalone, goofi-free core; a web UI; records the launch device set (EEG/Muse, ECG, audio, drawing, text, MIDI, OSC, space-weather) into synchronized session directories.
- **adalog-engine** — offline analysis, dataset exploration, downstream model building (future).
- **adalog-play** — running models online for live experiences (biofeedback, dream incubation), deeply integrated with goofi (future).

## The data standard

A session is a directory + `manifest.json` (the single contract). Each stream is stored in its **natural format** (Arrow IPC for high-rate signals, WAV for audio, PNG + pen-trace for drawing, NDJSON for text/OSC/meteo, MIDI). One **monotonic master clock** governs alignment; every stream declares its timing mode (`per_sample` / `anchored` / `anchored_irregular` / `event`) and carries honest timing provenance.

## Architecture (enforced layers)

```
adalog.core        goofi-free recording spine (clock, envelope, manifest, recorder, reader)
adalog.schema      declarative Field/config system
adalog.adapters    device-adapter SDK (base, supervisor, registry, templates)
adalog.store       BlobStore/Index interface + local backend
adalog.bridge_codec  vendored GOOF wire codec (goofi-free)
adalog.convert     legacy v0 -> v1 session converter
adalog.sense       standalone recorder app (bridge + devices + CLI)
```

The goofi-free boundary (`adalog.core/schema/adapters/store/convert/bridge_codec` import nothing from `goofi`/`torch`/`iceoryx2`) is enforced in CI by import-linter.

## Running the recorder

```bash
# build the web UI once (Node + pnpm, build-time only) and stage it into the package
python scripts/build_frontend.py

# install device backends (LSL, serial, audio, MIDI, OSC) and launch
uv sync --extra devices
uv run adalog-sense                 # opens http://127.0.0.1:8137 in your browser
```

Then: **New session** → tap devices to arm them → **● Record** → **■ Stop**. Sessions land
under `~/adalog-sessions/<user>/<session_id>/` as a `manifest.json` plus one natural-format
file per stream.

Convert legacy sessions to the new format:

```bash
uv run adalog-convert path/to/old/<user>/<timestamp> ~/adalog-sessions --user phil
```

## Development

```bash
uv sync --extra dev                              # core + test deps
uv run pytest -q -m "not e2e"                    # backend tests
uv run lint-imports --config importlinter.ini    # goofi-free + layering guard
cd frontend && pnpm install && pnpm build        # frontend
```

Browser end-to-end test (needs a built frontend + Playwright chromium):

```bash
uv run pytest -m e2e
```

## License

TODO
