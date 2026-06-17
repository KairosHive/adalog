"""adalog-sense console entry point."""
from __future__ import annotations

import argparse
from pathlib import Path

from .app import run


def main() -> None:
    p = argparse.ArgumentParser(prog="adalog-sense", description="adalog-sense multimodal recorder")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8137)
    p.add_argument("--sessions-root", type=Path, default=None)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = p.parse_args()
    run(host=args.host, port=args.port, sessions_root=args.sessions_root, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
