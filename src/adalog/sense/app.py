"""Standalone adalog-sense application: wire RecorderService + SenseBridge and run."""
from __future__ import annotations

import asyncio
import logging
import webbrowser
from pathlib import Path
from typing import Optional

from .bridge import SenseBridge
from .service import RecorderService


async def _serve(host: str, port: int, sessions_root: Optional[Path], open_browser: bool) -> None:
    service = RecorderService(sessions_root=sessions_root)
    bridge = SenseBridge(service, host=host, port=port)
    url = await bridge.start()
    logging.getLogger("adalog.sense").info("recording-ready at %s", url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    # run forever
    await asyncio.Event().wait()


def run(host: str = "127.0.0.1", port: int = 8137, sessions_root: Optional[Path] = None,
        open_browser: bool = True) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        asyncio.run(_serve(host, port, sessions_root, open_browser))
    except KeyboardInterrupt:
        pass
