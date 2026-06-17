"""Serve-time frontend resolution + auto-rebuild (mirrors goofi-pipe's pattern).

In a dev checkout, `maybe_build_frontend()` rebuilds the SvelteKit SPA whenever its
sources are newer than the emitted `frontend/build` bundle, so `adalog-sense` always
serves the current UI without a manual `pnpm build`. It is a no-op for wheel installs
(no `frontend/` source), when the bundle is already fresh, or when opted out via
`$ADALOG_NO_FRONTEND_BUILD`. Missing tooling or a failed build degrade gracefully to
serving whatever bundle already exists.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Optional

log = logging.getLogger("adalog.sense.bridge")

ENV_BUILD = "ADALOG_FRONTEND_BUILD"     # override the served static root
ENV_NO_BUILD = "ADALOG_NO_FRONTEND_BUILD"  # opt out of auto-rebuild

# Source inputs whose mtime gates staleness (dirs walked recursively).
_BUILD_INPUTS = (
    "src", "static", "package.json", "pnpm-lock.yaml", "package-lock.json",
    "svelte.config.js", "tsconfig.json", "vite.config.ts",
)


def resolve_static_root() -> Optional[Path]:
    """Find the built SPA. Order: $ADALOG_FRONTEND_BUILD → dev `frontend/build`
    → packaged `adalog/sense/web` (wheel)."""
    env = os.environ.get(ENV_BUILD)
    if env:
        p = Path(env)
        if (p / "index.html").is_file():
            return p

    dev = _repo_frontend() / "build"
    if (dev / "index.html").is_file():
        return dev

    try:
        with resources.as_file(resources.files("adalog.sense").joinpath("web")) as p:
            if (p / "index.html").is_file():
                return Path(p)
    except (ModuleNotFoundError, FileNotFoundError):
        pass
    return None


def _repo_frontend() -> Path:
    # src/adalog/sense/bridge/frontend_build.py → <repo>/frontend
    return Path(__file__).resolve().parents[4] / "frontend"


def _frontend_source_dir() -> Optional[Path]:
    """The repo `frontend/` source tree — only present in a dev checkout."""
    if os.environ.get(ENV_BUILD):
        return None
    frontend = _repo_frontend()
    if (frontend / "package.json").is_file() and (frontend / "src").is_dir():
        return frontend
    return None


def _newest_input_mtime(frontend: Path) -> float:
    newest = 0.0
    for name in _BUILD_INPUTS:
        p = frontend / name
        if not p.exists():
            continue
        items = [p, *p.rglob("*")] if p.is_dir() else [p]
        for item in items:
            try:
                newest = max(newest, item.stat().st_mtime)
            except OSError:
                pass
    return newest


def frontend_is_stale(frontend: Path) -> bool:
    index = frontend / "build" / "index.html"
    if not index.is_file():
        return True
    try:
        built = index.stat().st_mtime
    except OSError:
        return True
    return _newest_input_mtime(frontend) > built


def _build_command(frontend: Path) -> Optional[list[str]]:
    """Prefer pnpm (the lockfile is pnpm), fall back to npm. None if neither."""
    pnpm = shutil.which("pnpm")
    if pnpm:
        return [pnpm, "build"]
    npm = shutil.which("npm")
    if npm:
        return [npm, "run", "build"]
    return None


def maybe_build_frontend() -> None:
    """Rebuild the SPA when its sources are newer than the emitted bundle (dev checkout)."""
    if os.environ.get(ENV_NO_BUILD):
        return
    frontend = _frontend_source_dir()
    if frontend is None or not frontend_is_stale(frontend):
        return

    cmd = _build_command(frontend)
    if cmd is None:
        log.warning("frontend bundle is stale but neither pnpm nor npm is on PATH — "
                    "serving the existing build. Run `pnpm build` in frontend/ to refresh.")
        return
    if not (frontend / "node_modules").is_dir():
        log.warning("frontend bundle is stale but deps are missing — run `pnpm install` in "
                    "frontend/. Serving the existing build.")
        return

    log.info("frontend sources changed — rebuilding (%s)…", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=str(frontend), check=True)
        log.info("frontend rebuilt.")
    except subprocess.CalledProcessError as e:
        log.warning("frontend build failed (exit %s) — serving the previous build.", e.returncode)
