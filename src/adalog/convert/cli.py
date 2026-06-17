"""adalog-convert console entry point: migrate legacy adalog sessions to the v1 format."""
from __future__ import annotations

import argparse
from pathlib import Path

from . import convert_session


def main() -> None:
    p = argparse.ArgumentParser(prog="adalog-convert", description="Convert legacy adalog sessions to v1")
    p.add_argument("session_dir", type=Path, help="legacy session dir (…/<user>/<timestamp>/)")
    p.add_argument("out_root", type=Path, help="output sessions root")
    p.add_argument("--user", default="phil")
    args = p.parse_args()
    m = convert_session(args.session_dir, args.out_root, user=args.user)
    print(f"converted -> {args.out_root}/{args.user}/{m.session_id}/manifest.json  "
          f"({len(m.streams)} streams, {m.duration_s:.1f}s)")


if __name__ == "__main__":
    main()
