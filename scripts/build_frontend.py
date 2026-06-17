#!/usr/bin/env python
"""Build the SvelteKit frontend and stage it into the wheel at src/adalog/sense/web.

Run before `uv build` / `pip wheel` so the packaged bridge serves the SPA with no Node
at runtime. Requires pnpm + a Node toolchain (build-time only).
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
BUILD = FRONTEND / "build"
DEST = ROOT / "src" / "adalog" / "sense" / "web"


def main() -> int:
    if not (FRONTEND / "package.json").exists():
        print("no frontend/ to build", file=sys.stderr)
        return 1
    subprocess.run(["pnpm", "install", "--frozen-lockfile"], cwd=FRONTEND, check=False)
    subprocess.run(["pnpm", "build"], cwd=FRONTEND, check=True)
    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(BUILD, DEST)
    print(f"staged frontend bundle -> {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
