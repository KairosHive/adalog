from adalog.core.config_store import ConfigStore


def test_app_and_session_defaults_persist(tmp_path):
    p = tmp_path / "config.json"
    cs = ConfigStore(p)
    cs.set_app("sessions_root", str(tmp_path / "sess"))
    cs.set_session_defaults(subject_id="subj_phil", tags=["eeg"])
    cs.set_last_used_devices(["eeg_muse#0", "audio_mic#0"])

    cs2 = ConfigStore(p)  # reload
    assert cs2.get_app("sessions_root") == str(tmp_path / "sess")
    assert cs2.get_session_defaults()["subject_id"] == "subj_phil"
    assert cs2.get_last_used_devices() == ["eeg_muse#0", "audio_mic#0"]


def test_device_config_roundtrip(tmp_path):
    cs = ConfigStore(tmp_path / "config.json")
    cs.set_device("ecg_serial", {"port": "/dev/ttyUSB0", "baud": 256}, instance_id="0")
    assert cs.get_device("ecg_serial")["port"] == "/dev/ttyUSB0"


def test_secret_never_in_plaintext(tmp_path):
    p = tmp_path / "config.json"
    cs = ConfigStore(p)
    cs.set_device("api_thing", {"endpoint": "https://x", "api_key": "SECRET123"},
                  secret_keys=("api_key",))
    text = p.read_text()
    assert "SECRET123" not in text  # secret routed to keyring (or dropped), never plaintext
    assert "endpoint" in text
