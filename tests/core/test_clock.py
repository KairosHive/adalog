from adalog.core.clock import SessionClock


def make_clock(fake, **kw):
    return SessionClock(mono_fn=fake.monotonic_ns, utc_fn=fake.utc_ns, **kw)


def test_now_s_monotonic_increasing(fake_clock):
    clk = make_clock(fake_clock)
    t0 = clk.now_s()
    assert t0 == 0.0
    fake_clock.tick(500_000_000)  # +0.5s
    t1 = clk.now_s()
    fake_clock.tick(250_000_000)  # +0.25s
    t2 = clk.now_s()
    assert t1 > t0 and t2 > t1
    assert abs(t1 - 0.5) < 1e-9
    assert abs(t2 - 0.75) < 1e-9


def test_mono_to_utc_roundtrips_t0(fake_clock):
    clk = make_clock(fake_clock)
    assert clk.mono_to_utc_ns(clk.t0_mono_ns) == clk.t0_utc_ns


def test_mono_to_utc_interpolates_after_reanchor(fake_clock):
    clk = make_clock(fake_clock)
    fake_clock.tick(10_000_000_000)  # +10s, utc advances equally
    clk.reanchor()
    # midpoint mono -> midpoint utc
    mid_mono = clk.t0_mono_ns + 5_000_000_000
    expected_utc = clk.t0_utc_ns + 5_000_000_000
    assert abs(clk.mono_to_utc_ns(mid_mono) - expected_utc) <= 1


def test_drift_ppm_detected_when_utc_runs_fast(fake_clock):
    clk = make_clock(fake_clock)
    # mono advances 10s, but utc advances 10s + 10ms => +1000 ppm
    fake_clock.tick(10_000_000_000, utc_ns=10_010_000_000)
    clk.reanchor()
    assert clk.host_drift_ppm > 900  # ~1000 ppm
    # reconstructed utc at the new anchor matches the (faster) wall clock
    assert abs(clk.mono_to_utc_ns(clk.anchors[-1].mono_ns) - clk.anchors[-1].utc_ns) <= 2


def test_suspend_detected_on_fallback_path(fake_clock):
    clk = make_clock(fake_clock, use_boottime=False)
    # 0.1s of real mono progress but 60s of wall progress => suspend on fallback
    fake_clock.tick(100_000_000, utc_ns=60_000_000_000)
    clk.reanchor()
    assert len(clk.suspend_events) == 1
    assert abs(clk.suspend_events[0].gap_s - 59.9) < 0.1


def test_no_suspend_event_when_boottime(fake_clock):
    clk = make_clock(fake_clock, use_boottime=True)
    # With BOOTTIME, mono already accounts for elapsed time: mono and utc move together.
    fake_clock.tick(60_000_000_000)
    clk.reanchor()
    assert clk.suspend_events == []
    assert clk.boottime_used is True


def test_real_clock_smoke():
    # Real platform path: must construct and read without injected fns.
    clk = SessionClock()
    assert clk.now_s() >= 0.0
    assert clk.mono_to_utc_ns(clk.t0_mono_ns) == clk.t0_utc_ns
