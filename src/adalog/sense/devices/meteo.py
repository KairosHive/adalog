"""NOAA space-weather poller (RestPoll, per_sample). Merges mag + plasma feeds."""
from __future__ import annotations

from ...adapters.base import AdapterInfo
from ...adapters.templates import RestPollDevice
from ...core.spec import ENC_CSV_TS, TIMING_PER_SAMPLE, Channel, StreamSpec

MAG_URL = "https://services.swpc.noaa.gov/products/solar-wind/mag-1-day.json"
PLASMA_URL = "https://services.swpc.noaa.gov/products/solar-wind/plasma-1-day.json"
_COLS = ["bx_gsm", "by_gsm", "bz_gsm", "bt", "density", "speed", "temperature"]


class MeteoAdapter(RestPollDevice):
    info = AdapterInfo(id="meteo", title="Space weather (NOAA)", category="environment")
    default_interval_s = 10.0

    def declare_streams(self):
        return [StreamSpec(id="meteo", modality="environment", encoding=ENC_CSV_TS,
                           timing_mode=TIMING_PER_SAMPLE, channels=[Channel(c) for c in _COLS])]

    def dedup_key(self, record):
        return record.get("time_tag")

    def _get_json(self, url):
        import requests
        return requests.get(url, timeout=10).json()

    def fetch(self) -> list[dict]:
        mag = self._get_json(MAG_URL)
        plasma = self._get_json(PLASMA_URL)
        return [self._merge(mag, plasma)] if (mag and plasma) else []

    def _merge(self, mag, plasma) -> dict:
        mh, mr = mag[0], mag[-1]              # header, latest row
        ph, pr = plasma[0], plasma[-1]
        mi = {k: i for i, k in enumerate(mh)}
        pi = {k: i for i, k in enumerate(ph)}
        def g(row, idx, key):
            try:
                return float(row[idx[key]])
            except (KeyError, ValueError, TypeError):
                return None
        return {
            "time_tag": mr[mi.get("time_tag", 0)],
            "bx_gsm": g(mr, mi, "bx_gsm"), "by_gsm": g(mr, mi, "by_gsm"), "bz_gsm": g(mr, mi, "bz_gsm"),
            "bt": g(mr, mi, "bt"),
            "density": g(pr, pi, "density"), "speed": g(pr, pi, "speed"), "temperature": g(pr, pi, "temperature"),
        }
