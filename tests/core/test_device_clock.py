import random

from adalog.core.device_clock import DeviceClock, PROV_LSL


def test_offset_only_recovers_constant_offset():
    dc = DeviceClock(PROV_LSL)
    # device clock = session_mono - 5_000_000 ns (device started 5ms "before" host ref)
    offset = -5_000_000
    for i in range(8):  # < min_skew_samples -> offset-only path
        session_mono = 1_000_000_000 + i * 4_000_000
        device_ts = session_mono + offset
        dc.update(device_ts, session_mono)
    # mapping a device ts back should recover session mono within ns
    session_mono = 1_000_000_000 + 100 * 4_000_000
    device_ts = session_mono + offset
    assert abs(dc.map(device_ts) - session_mono) <= 2


def test_recovers_skew_and_offset_with_noise_and_outliers():
    rng = random.Random(42)
    dc = DeviceClock(PROV_LSL)
    # True relationship: session_mono = 1.0005 * device_rel + base   (i.e. ~500ppm skew)
    base = 2_000_000_000
    skew = 1.0005
    dev0 = 50_000_000_000
    samples = []
    for i in range(200):
        device_ts = dev0 + i * 4_000_000  # ~250Hz device clock
        true_mono = base + round(skew * (device_ts - dev0))
        recv = true_mono + rng.randint(-50_000, 50_000)  # ±50us jitter
        # inject occasional backwards/garbage stamps (outliers)
        dev_used = device_ts
        if i % 37 == 0:
            dev_used = device_ts - 1_000_000_000  # 1s backward glitch
        dc.update(dev_used, recv)
        samples.append((device_ts, true_mono))
    # Evaluate mapping accuracy on clean device timestamps
    errs = [abs(dc.map(d) - m) for d, m in samples[-50:]]
    assert max(errs) < 200_000  # within 200us despite outliers + jitter
    assert abs(dc.drift_ppm - 500) < 150  # recovered ~500ppm skew


def test_provenance_recorded():
    dc = DeviceClock(PROV_LSL)
    assert dc.provenance == PROV_LSL
