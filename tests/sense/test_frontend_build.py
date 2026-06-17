"""Auto-rebuild-on-run logic (mirrors goofi-pipe). Hermetic — no real pnpm in these tests."""
import os
import time

import pytest

from adalog.sense.bridge import frontend_build as fb


def _make_frontend(tmp_path, *, build=True):
    fe = tmp_path / "frontend"
    (fe / "src").mkdir(parents=True)
    (fe / "src" / "app.ts").write_text("export const x = 1;")
    (fe / "package.json").write_text("{}")
    (fe / "node_modules").mkdir()
    if build:
        (fe / "build").mkdir()
        (fe / "build" / "index.html").write_text("<html></html>")
    return fe


def test_stale_when_no_build(tmp_path):
    fe = _make_frontend(tmp_path, build=False)
    assert fb.frontend_is_stale(fe) is True


def test_fresh_when_build_newer_than_sources(tmp_path):
    fe = _make_frontend(tmp_path, build=True)
    # make the build clearly newer than every source
    future = time.time() + 10
    os.utime(fe / "build" / "index.html", (future, future))
    assert fb.frontend_is_stale(fe) is False


def test_stale_when_source_newer_than_build(tmp_path):
    fe = _make_frontend(tmp_path, build=True)
    future = time.time() + 10
    os.utime(fe / "src" / "app.ts", (future, future))
    assert fb.frontend_is_stale(fe) is True


def test_maybe_build_opt_out(tmp_path, monkeypatch):
    fe = _make_frontend(tmp_path, build=False)
    monkeypatch.setenv(fb.ENV_NO_BUILD, "1")
    monkeypatch.setattr(fb, "_frontend_source_dir", lambda: fe)
    called = []
    monkeypatch.setattr(fb.subprocess, "run", lambda *a, **k: called.append(a))
    fb.maybe_build_frontend()
    assert called == []  # opted out -> never builds


def test_maybe_build_noop_for_wheel_install(tmp_path, monkeypatch):
    # No dev source tree -> no-op (wheel install path)
    monkeypatch.setattr(fb, "_frontend_source_dir", lambda: None)
    called = []
    monkeypatch.setattr(fb.subprocess, "run", lambda *a, **k: called.append(a))
    fb.maybe_build_frontend()
    assert called == []


def test_maybe_build_runs_when_stale(tmp_path, monkeypatch):
    fe = _make_frontend(tmp_path, build=False)
    monkeypatch.delenv(fb.ENV_NO_BUILD, raising=False)
    monkeypatch.setattr(fb, "_frontend_source_dir", lambda: fe)
    monkeypatch.setattr(fb, "_build_command", lambda f: ["fake-build"])

    ran = []
    def fake_run(cmd, cwd, check):
        ran.append((cmd, cwd))
        (fe / "build").mkdir(exist_ok=True)
        (fe / "build" / "index.html").write_text("<html>built</html>")
    monkeypatch.setattr(fb.subprocess, "run", fake_run)

    fb.maybe_build_frontend()
    assert ran and ran[0][0] == ["fake-build"]
    assert (fe / "build" / "index.html").read_text() == "<html>built</html>"


def test_maybe_build_skips_when_fresh(tmp_path, monkeypatch):
    fe = _make_frontend(tmp_path, build=True)
    future = time.time() + 10
    os.utime(fe / "build" / "index.html", (future, future))
    monkeypatch.setattr(fb, "_frontend_source_dir", lambda: fe)
    ran = []
    monkeypatch.setattr(fb.subprocess, "run", lambda *a, **k: ran.append(a))
    fb.maybe_build_frontend()
    assert ran == []  # already fresh -> no rebuild


def test_maybe_build_degrades_without_tooling(tmp_path, monkeypatch):
    fe = _make_frontend(tmp_path, build=False)
    monkeypatch.setattr(fb, "_frontend_source_dir", lambda: fe)
    monkeypatch.setattr(fb, "_build_command", lambda f: None)  # no pnpm/npm
    ran = []
    monkeypatch.setattr(fb.subprocess, "run", lambda *a, **k: ran.append(a))
    fb.maybe_build_frontend()  # must not raise
    assert ran == []


def test_resolve_static_root_env_override(tmp_path, monkeypatch):
    root = tmp_path / "custom"
    root.mkdir()
    (root / "index.html").write_text("<html></html>")
    monkeypatch.setenv(fb.ENV_BUILD, str(root))
    assert fb.resolve_static_root() == root
